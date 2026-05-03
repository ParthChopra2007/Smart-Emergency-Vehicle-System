"""
Smart Emergency Vehicle Priority System - GPS Tracker Service
Handles real-time vehicle tracking, geofencing, route tracking,
and location history management for emergency vehicles
"""

import math
import json
import threading
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass, field
from collections import deque, defaultdict
from loguru import logger
import heapq

from geopy.distance import geodesic
from app.extensions import db, socketio, redis_client, cache

# ============================================
# DATA CLASSES
# ============================================

@dataclass
class GPSPoint:
    """Represents a single GPS point"""
    latitude: float
    longitude: float
    timestamp: datetime
    speed: float = 0.0
    heading: float = 0.0
    accuracy: float = 5.0  # meters
    altitude: float = 0.0
    
    def to_dict(self) -> Dict:
        return {
            'latitude': self.latitude,
            'longitude': self.longitude,
            'timestamp': self.timestamp.isoformat(),
            'speed': self.speed,
            'heading': self.heading,
            'accuracy': self.accuracy,
            'altitude': self.altitude
        }
    
    def distance_to(self, other: 'GPSPoint') -> float:
        """Calculate distance to another GPS point in kilometers"""
        return geodesic(
            (self.latitude, self.longitude),
            (other.latitude, other.longitude)
        ).kilometers


@dataclass
class VehicleTrack:
    """Represents complete track of a vehicle"""
    vehicle_id: int
    registration_number: str
    points: List[GPSPoint] = field(default_factory=list)
    start_time: datetime = None
    end_time: datetime = None
    total_distance_km: float = 0.0
    average_speed_kmh: float = 0.0
    max_speed_kmh: float = 0.0
    
    def add_point(self, point: GPSPoint):
        """Add a GPS point to the track"""
        if self.points:
            last_point = self.points[-1]
            distance = last_point.distance_to(point)
            self.total_distance_km += distance
            
            time_diff = (point.timestamp - last_point.timestamp).total_seconds()
            if time_diff > 0:
                speed = (distance / time_diff) * 3600
                if speed > self.max_speed_kmh:
                    self.max_speed_kmh = speed
        
        self.points.append(point)
        
        if not self.start_time:
            self.start_time = point.timestamp
        self.end_time = point.timestamp
        
        # Update average speed
        if self.start_time and self.end_time:
            total_time_hours = (self.end_time - self.start_time).total_seconds() / 3600
            if total_time_hours > 0:
                self.average_speed_kmh = self.total_distance_km / total_time_hours
    
    def get_path(self) -> List[Tuple[float, float]]:
        """Get path as list of (lat, lng) tuples"""
        return [(p.latitude, p.longitude) for p in self.points]
    
    def to_dict(self) -> Dict:
        return {
            'vehicle_id': self.vehicle_id,
            'registration_number': self.registration_number,
            'points': [p.to_dict() for p in self.points],
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'total_distance_km': round(self.total_distance_km, 2),
            'average_speed_kmh': round(self.average_speed_kmh, 1),
            'max_speed_kmh': round(self.max_speed_kmh, 1),
            'point_count': len(self.points)
        }


@dataclass
class Geofence:
    """Represents a geofence area"""
    id: int
    name: str
    center_lat: float
    center_lng: float
    radius_km: float
    points: List[Tuple[float, float]] = field(default_factory=list)  # For polygon
    is_active: bool = True
    created_at: datetime = None
    
    def contains_point(self, lat: float, lng: float) -> bool:
        """Check if a point is inside the geofence"""
        if self.points:
            # Polygon check (ray casting algorithm)
            return self._point_in_polygon(lat, lng, self.points)
        else:
            # Circle check
            distance = geodesic((self.center_lat, self.center_lng), (lat, lng)).kilometers
            return distance <= self.radius_km
    
    def _point_in_polygon(self, lat: float, lng: float, polygon: List[Tuple[float, float]]) -> bool:
        """Ray casting algorithm to check if point is inside polygon"""
        inside = False
        n = len(polygon)
        
        for i in range(n):
            x1, y1 = polygon[i]
            x2, y2 = polygon[(i + 1) % n]
            
            # Check if point is on the horizontal edge
            if (y1 > lng) != (y2 > lng):
                x_intersect = x1 + (lng - y1) * (x2 - x1) / (y2 - y1)
                if lat < x_intersect:
                    inside = not inside
        
        return inside


# ============================================
# GPS TRACKER SERVICE
# ============================================

class GPSTracker:
    """
    Main GPS tracking service for emergency vehicles
    Handles real-time location updates, track recording, and geofencing
    """
    
    def __init__(self, app=None):
        self.app = app
        self.active_tracks: Dict[int, VehicleTrack] = {}
        self.location_history: Dict[int, deque] = {}
        self.geofences: List[Geofence] = []
        self._tracking_thread = None
        self._is_running = False
        self._load_geofences()
        
        # Statistics
        self.stats = {
            'active_vehicles': 0,
            'total_updates_processed': 0,
            'total_distance_tracked_km': 0.0,
            'avg_update_frequency_seconds': 0
        }
        
        if app:
            self.start_tracking()
    
    def _load_geofences(self):
        """Load geofences from database or configuration"""
        # Predefined geofences for hospitals, fire stations, police stations
        self.geofences = [
            Geofence(
                id=1,
                name="AIIMS Hospital",
                center_lat=28.5675,
                center_lng=77.2100,
                radius_km=0.5
            ),
            Geofence(
                id=2,
                name="Central Fire Station",
                center_lat=28.6304,
                center_lng=77.2177,
                radius_km=0.3
            ),
            Geofence(
                id=3,
                name="Police Headquarters",
                center_lat=28.6426,
                center_lng=77.2306,
                radius_km=0.3
            ),
            Geofence(
                id=4,
                name="Emergency Control Room",
                center_lat=28.6139,
                center_lng=77.2090,
                radius_km=0.5
            )
        ]
        logger.info(f"Loaded {len(self.geofences)} geofences")
    
    def start_tracking(self):
        """Start background tracking thread"""
        if self._tracking_thread is None:
            self._is_running = True
            self._tracking_thread = threading.Thread(target=self._process_updates)
            self._tracking_thread.daemon = True
            self._tracking_thread.start()
            logger.info("GPS tracking service started")
    
    def stop_tracking(self):
        """Stop background tracking"""
        self._is_running = False
        if self._tracking_thread:
            self._tracking_thread.join(timeout=5)
            logger.info("GPS tracking service stopped")
    
    def _process_updates(self):
        """Background thread to process GPS updates"""
        while self._is_running:
            try:
                # Update active vehicles count
                from app.models.vehicle import EmergencyVehicle
                active_vehicles = EmergencyVehicle.query.filter(
                    EmergencyVehicle.current_latitude.isnot(None),
                    EmergencyVehicle.is_active == True
                ).count()
                self.stats['active_vehicles'] = active_vehicles
                
                # Clean up old tracks (older than 1 hour with no updates)
                self._cleanup_old_tracks()
                
                import time
                time.sleep(30)  # Update every 30 seconds
                
            except Exception as e:
                logger.error(f"GPS processing error: {e}")
                import time
                time.sleep(60)
    
    def _cleanup_old_tracks(self):
        """Clean up tracks that haven't been updated in over an hour"""
        now = datetime.utcnow()
        to_remove = []
        
        for vehicle_id, track in self.active_tracks.items():
            if track.points:
                last_update = track.points[-1].timestamp
                if (now - last_update).total_seconds() > 3600:  # 1 hour
                    to_remove.append(vehicle_id)
        
        for vehicle_id in to_remove:
            del self.active_tracks[vehicle_id]
            if vehicle_id in self.location_history:
                del self.location_history[vehicle_id]
        
        if to_remove:
            logger.debug(f"Cleaned up {len(to_remove)} inactive tracks")
    
    def update_location(self, vehicle_id: int, registration_number: str,
                        latitude: float, longitude: float,
                        speed: float = 0.0, heading: float = 0.0,
                        accuracy: float = 5.0) -> Dict:
        """
        Update vehicle location in real-time
        """
        try:
            point = GPSPoint(
                latitude=latitude,
                longitude=longitude,
                timestamp=datetime.utcnow(),
                speed=speed,
                heading=heading,
                accuracy=accuracy
            )
            
            # Update active track
            if vehicle_id not in self.active_tracks:
                self.active_tracks[vehicle_id] = VehicleTrack(
                    vehicle_id=vehicle_id,
                    registration_number=registration_number
                )
            
            track = self.active_tracks[vehicle_id]
            track.add_point(point)
            
            # Update location history (keep last 1000 points)
            if vehicle_id not in self.location_history:
                self.location_history[vehicle_id] = deque(maxlen=1000)
            self.location_history[vehicle_id].append(point)
            
            # Update statistics
            self.stats['total_updates_processed'] += 1
            
            # Check geofences
            geofence_alerts = self.check_geofences(latitude, longitude, vehicle_id)
            
            # Cache in Redis for fast access
            if redis_client:
                redis_client.setex(
                    f"vehicle:location:{vehicle_id}",
                    60,
                    json.dumps({
                        'lat': latitude,
                        'lng': longitude,
                        'speed': speed,
                        'heading': heading,
                        'timestamp': point.timestamp.isoformat()
                    })
                )
            
            # Emit real-time update via WebSocket
            self._emit_location_update(vehicle_id, registration_number, point, geofence_alerts)
            
            # Update vehicle in database
            self._update_vehicle_db(vehicle_id, latitude, longitude, speed, heading)
            
            return {
                'success': True,
                'vehicle_id': vehicle_id,
                'location': point.to_dict(),
                'geofence_alerts': geofence_alerts,
                'track_summary': {
                    'total_distance_km': round(track.total_distance_km, 2),
                    'duration_minutes': round(
                        (track.end_time - track.start_time).total_seconds() / 60
                    ) if track.start_time and track.end_time else 0,
                    'average_speed_kmh': round(track.average_speed_kmh, 1)
                }
            }
            
        except Exception as e:
            logger.error(f"Update location error for vehicle {vehicle_id}: {e}")
            return {'success': False, 'error': str(e)}
    
    def _emit_location_update(self, vehicle_id: int, registration_number: str,
                               point: GPSPoint, geofence_alerts: List[Dict]):
        """Emit real-time location update via WebSocket"""
        socketio.emit('vehicle_location_update', {
            'vehicle_id': vehicle_id,
            'registration_number': registration_number,
            'location': {
                'latitude': point.latitude,
                'longitude': point.longitude,
                'speed': point.speed,
                'heading': point.heading
            },
            'timestamp': point.timestamp.isoformat(),
            'geofence_alerts': geofence_alerts
        }, broadcast=True)
        
        # Also emit to specific room for this vehicle
        socketio.emit(f'vehicle:{vehicle_id}:location', {
            'latitude': point.latitude,
            'longitude': point.longitude,
            'speed': point.speed,
            'heading': point.heading,
            'timestamp': point.timestamp.isoformat()
        }, room=f'vehicle_{vehicle_id}')
    
    def _update_vehicle_db(self, vehicle_id: int, latitude: float, longitude: float,
                            speed: float, heading: float):
        """Update vehicle location in database"""
        try:
            from app.models.vehicle import find_vehicle_by_id
            from app.models.vehicle import VehicleLocationHistory
            
            vehicle = find_vehicle_by_id(vehicle_id)
            if vehicle:
                vehicle.update_location(latitude, longitude, speed, heading)
                
                # Record in history
                VehicleLocationHistory.record_location(vehicle_id, latitude, longitude, speed, heading)
                
        except Exception as e:
            logger.error(f"Database update error: {e}")
    
    def get_vehicle_track(self, vehicle_id: int, duration_minutes: int = 60) -> Optional[Dict]:
        """
        Get vehicle track for last N minutes
        """
        if vehicle_id not in self.location_history:
            return None
        
        cutoff = datetime.utcnow() - timedelta(minutes=duration_minutes)
        points = [p for p in self.location_history[vehicle_id] if p.timestamp >= cutoff]
        
        if not points:
            return None
        
        return {
            'vehicle_id': vehicle_id,
            'duration_minutes': duration_minutes,
            'points': [p.to_dict() for p in points],
            'point_count': len(points)
        }
    
    def get_all_active_vehicles(self) -> List[Dict]:
        """
        Get current location of all active vehicles
        """
        from app.models.vehicle import EmergencyVehicle
        
        vehicles = EmergencyVehicle.query.filter(
            EmergencyVehicle.current_latitude.isnot(None),
            EmergencyVehicle.is_active == True
        ).limit(100).all()
        
        result = []
        for vehicle in vehicles:
            result.append({
                'id': vehicle.id,
                'registration_number': vehicle.registration_number,
                'vehicle_type': vehicle.vehicle_type.value if vehicle.vehicle_type else None,
                'location': {
                    'latitude': vehicle.current_latitude,
                    'longitude': vehicle.current_longitude,
                    'speed': vehicle.current_speed,
                    'heading': vehicle.current_heading
                },
                'status': vehicle.status.value if vehicle.status else None,
                'last_update': vehicle.last_location_update.isoformat() if vehicle.last_location_update else None,
                'is_siren_active': vehicle.is_siren_active
            })
        
        return result
    
    def get_nearby_vehicles(self, latitude: float, longitude: float,
                            radius_km: float = 5.0,
                            vehicle_type: str = None) -> List[Dict]:
        """
        Find vehicles within a radius of a location
        """
        from app.models.vehicle import EmergencyVehicle, VehicleType
        
        query = EmergencyVehicle.query.filter(
            EmergencyVehicle.current_latitude.isnot(None),
            EmergencyVehicle.is_active == True
        )
        
        if vehicle_type:
            try:
                vtype = VehicleType(vehicle_type)
                query = query.filter_by(vehicle_type=vtype)
            except ValueError:
                pass
        
        vehicles = query.all()
        nearby = []
        
        for vehicle in vehicles:
            distance = geodesic(
                (latitude, longitude),
                (vehicle.current_latitude, vehicle.current_longitude)
            ).kilometers
            
            if distance <= radius_km:
                nearby.append({
                    'id': vehicle.id,
                    'registration_number': vehicle.registration_number,
                    'vehicle_type': vehicle.vehicle_type.value if vehicle.vehicle_type else None,
                    'distance_km': round(distance, 2),
                    'location': {
                        'latitude': vehicle.current_latitude,
                        'longitude': vehicle.current_longitude
                    },
                    'status': vehicle.status.value if vehicle.status else None,
                    'eta_seconds': int((distance / 40) * 3600) if distance else 0  # Assuming 40 km/h
                })
        
        nearby.sort(key=lambda x: x['distance_km'])
        return nearby
    
    def check_geofences(self, latitude: float, longitude: float,
                         vehicle_id: int = None) -> List[Dict]:
        """
        Check if a location is within any geofence
        """
        alerts = []
        
        for geofence in self.geofences:
            if geofence.contains_point(latitude, longitude):
                alert = {
                    'geofence_id': geofence.id,
                    'name': geofence.name,
                    'vehicle_id': vehicle_id,
                    'timestamp': datetime.utcnow().isoformat()
                }
                alerts.append(alert)
                
                # Emit geofence alert
                if vehicle_id:
                    socketio.emit('geofence_alert', alert, broadcast=True)
                    logger.info(f"Vehicle {vehicle_id} entered geofence: {geofence.name}")
        
        return alerts
    
    def calculate_route_distance(self, points: List[Tuple[float, float]]) -> float:
        """
        Calculate total distance of a route
        """
        if len(points) < 2:
            return 0.0
        
        total = 0.0
        for i in range(len(points) - 1):
            distance = geodesic(points[i], points[i + 1]).kilometers
            total += distance
        
        return round(total, 2)
    
    def estimate_arrival_time(self, start_lat: float, start_lng: float,
                               dest_lat: float, dest_lng: float,
                               vehicle_speed_kmh: float = 40.0) -> Dict:
        """
        Estimate arrival time based on distance and speed
        """
        distance = geodesic((start_lat, start_lng), (dest_lat, dest_lng)).kilometers
        
        if vehicle_speed_kmh <= 0:
            vehicle_speed_kmh = 40.0
        
        time_seconds = (distance / vehicle_speed_kmh) * 3600
        arrival_time = datetime.utcnow() + timedelta(seconds=time_seconds)
        
        return {
            'distance_km': round(distance, 2),
            'estimated_time_seconds': int(time_seconds),
            'estimated_time_minutes': round(time_seconds / 60, 1),
            'estimated_arrival': arrival_time.isoformat(),
            'assumed_speed_kmh': vehicle_speed_kmh
        }
    
    def get_vehicle_speed_estimate(self, vehicle_id: int, seconds: int = 30) -> Optional[float]:
        """
        Estimate vehicle speed based on recent location changes
        """
        if vehicle_id not in self.location_history:
            return None
        
        points = list(self.location_history[vehicle_id])
        if len(points) < 2:
            return None
        
        # Get points from last N seconds
        cutoff = datetime.utcnow() - timedelta(seconds=seconds)
        recent = [p for p in points if p.timestamp >= cutoff]
        
        if len(recent) < 2:
            return None
        
        # Calculate average speed
        total_distance = 0.0
        for i in range(len(recent) - 1):
            total_distance += recent[i].distance_to(recent[i + 1])
        
        time_diff = (recent[-1].timestamp - recent[0].timestamp).total_seconds()
        
        if time_diff > 0:
            speed_kmh = (total_distance / time_diff) * 3600
            return round(speed_kmh, 1)
        
        return None
    
    def get_stats(self) -> Dict:
        """Get service statistics"""
        return {
            'active_vehicles': self.stats['active_vehicles'],
            'active_tracks': len(self.active_tracks),
            'total_updates_processed': self.stats['total_updates_processed'],
            'total_distance_tracked_km': round(self.stats['total_distance_tracked_km'], 2),
            'geofences_loaded': len(self.geofences),
            'is_tracking': self._is_running
        }
    
    def health_check(self) -> bool:
        """Check if service is healthy"""
        return self._is_running


# ============================================
# LOCATION SERVICE
# ============================================

class LocationService:
    """
    Utility service for location-based operations
    """
    
    def __init__(self, gps_tracker: GPSTracker):
        self.gps_tracker = gps_tracker
    
    def geocode_address(self, address: str) -> Optional[Tuple[float, float]]:
        """
        Convert address to coordinates (would use Google Maps API in production)
        """
        # Placeholder - would integrate with Google Maps API
        # For demo, return some default coordinates
        logger.warning(f"Geocoding not implemented for address: {address}")
        return None
    
    def reverse_geocode(self, latitude: float, longitude: float) -> Optional[str]:
        """
        Convert coordinates to address
        """
        # Placeholder - would integrate with Google Maps API
        return f"Lat: {latitude}, Lng: {longitude}"
    
    def calculate_bearing(self, lat1: float, lng1: float, lat2: float, lng2: float) -> float:
        """
        Calculate bearing between two points in degrees
        """
        lat1_rad = math.radians(lat1)
        lat2_rad = math.radians(lat2)
        delta_lng = math.radians(lng2 - lng1)
        
        x = math.sin(delta_lng) * math.cos(lat2_rad)
        y = math.cos(lat1_rad) * math.sin(lat2_rad) - \
            math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(delta_lng)
        
        bearing = math.atan2(x, y)
        bearing_deg = math.degrees(bearing)
        
        return round((bearing_deg + 360) % 360, 1)


# ============================================
# GEOFENCE MANAGER
# ============================================

class GeofenceManager:
    """
    Manages geofences and triggers alerts
    """
    
    def __init__(self, gps_tracker: GPSTracker):
        self.gps_tracker = gps_tracker
        self.vehicle_geofence_status = {}  # vehicle_id -> set of active geofence_ids
        self.alert_history = deque(maxlen=1000)
    
    def add_geofence(self, name: str, center_lat: float, center_lng: float,
                     radius_km: float) -> Geofence:
        """
        Add a new geofence
        """
        geofence_id = len(self.gps_tracker.geofences) + 1
        geofence = Geofence(
            id=geofence_id,
            name=name,
            center_lat=center_lat,
            center_lng=center_lng,
            radius_km=radius_km,
            created_at=datetime.utcnow()
        )
        self.gps_tracker.geofences.append(geofence)
        logger.info(f"Geofence added: {name} at ({center_lat}, {center_lng}) radius {radius_km}km")
        return geofence
    
    def remove_geofence(self, geofence_id: int) -> bool:
        """Remove a geofence"""
        for i, gf in enumerate(self.gps_tracker.geofences):
            if gf.id == geofence_id:
                self.gps_tracker.geofences.pop(i)
                logger.info(f"Geofence {geofence_id} removed")
                return True
        return False
    
    def get_vehicles_in_geofence(self, geofence_id: int) -> List[Dict]:
        """
        Get all vehicles currently inside a geofence
        """
        geofence = None
        for gf in self.gps_tracker.geofences:
            if gf.id == geofence_id:
                geofence = gf
                break
        
        if not geofence:
            return []
        
        from app.models.vehicle import EmergencyVehicle
        vehicles = EmergencyVehicle.query.filter(
            EmergencyVehicle.current_latitude.isnot(None),
            EmergencyVehicle.is_active == True
        ).all()
        
        inside = []
        for vehicle in vehicles:
            if geofence.contains_point(vehicle.current_latitude, vehicle.current_longitude):
                inside.append({
                    'vehicle_id': vehicle.id,
                    'registration_number': vehicle.registration_number,
                    'vehicle_type': vehicle.vehicle_type.value if vehicle.vehicle_type else None,
                    'location': {
                        'latitude': vehicle.current_latitude,
                        'longitude': vehicle.current_longitude
                    }
                })
        
        return inside


# ============================================
# ROUTE TRACKING SERVICE
# ============================================

class RouteTrackingService:
    """
    Service for tracking vehicles along specific routes
    Useful for monitoring emergency vehicle progress
    """
    
    def __init__(self, gps_tracker: GPSTracker):
        self.gps_tracker = gps_tracker
        self.active_routes: Dict[int, Dict] = {}
    
    def start_route_tracking(self, vehicle_id: int, route_id: int,
                               waypoints: List[Tuple[float, float]]) -> bool:
        """
        Start tracking a vehicle along a specific route
        """
        self.active_routes[vehicle_id] = {
            'route_id': route_id,
            'waypoints': waypoints,
            'current_waypoint': 0,
            'started_at': datetime.utcnow(),
            'completed_at': None,
            'deviations': 0
        }
        logger.info(f"Started route tracking for vehicle {vehicle_id} on route {route_id}")
        return True
    
    def update_route_progress(self, vehicle_id: int, latitude: float, longitude: float) -> Dict:
        """
        Update vehicle progress along route
        """
        if vehicle_id not in self.active_routes:
            return {'error': 'Route not found for vehicle'}
        
        route = self.active_routes[vehicle_id]
        waypoints = route['waypoints']
        current_idx = route['current_waypoint']
        
        if current_idx >= len(waypoints):
            return {'completed': True}
        
        # Check distance to next waypoint
        next_wp = waypoints[current_idx]
        distance = geodesic((latitude, longitude), next_wp).kilometers
        
        # If within 50 meters, advance to next waypoint
        if distance <= 0.05:
            route['current_waypoint'] += 1
            logger.info(f"Vehicle {vehicle_id} reached waypoint {current_idx + 1}")
            
            # Check if route completed
            if route['current_waypoint'] >= len(waypoints):
                route['completed_at'] = datetime.utcnow()
                logger.info(f"Vehicle {vehicle_id} completed route {route['route_id']}")
                return {'completed': True, 'message': 'Route completed'}
        
        # Check for deviation (distance > 200 meters from route)
        min_distance = min(geodesic((latitude, longitude), wp).kilometers for wp in waypoints)
        if min_distance > 0.2:
            route['deviations'] += 1
            if route['deviations'] >= 3:
                socketio.emit('route_deviation_alert', {
                    'vehicle_id': vehicle_id,
                    'route_id': route['route_id'],
                    'deviation_km': round(min_distance, 2),
                    'timestamp': datetime.utcnow().isoformat()
                }, broadcast=True)
                logger.warning(f"Vehicle {vehicle_id} deviated from route")
        
        return {
            'completed': False,
            'current_waypoint': route['current_waypoint'] + 1,
            'total_waypoints': len(waypoints),
            'next_waypoint': waypoints[route['current_waypoint']] if route['current_waypoint'] < len(waypoints) else None,
            'distance_to_next_km': round(distance, 2),
            'progress_percentage': round((route['current_waypoint'] / len(waypoints)) * 100, 1),
            'deviations': route['deviations']
        }


# ============================================
# SERVICE FACTORY FUNCTIONS
# ============================================

_gps_tracker = None
_location_service = None
_geofence_manager = None
_route_tracking_service = None


def get_gps_service(app=None) -> GPSTracker:
    """Get or create GPS tracker service instance"""
    global _gps_tracker
    
    if _gps_tracker is None:
        _gps_tracker = GPSTracker(app)
    
    return _gps_tracker


def get_location_service(app=None) -> LocationService:
    """Get or create location service instance"""
    global _location_service
    
    if _location_service is None:
        gps_service = get_gps_service(app)
        _location_service = LocationService(gps_service)
    
    return _location_service


def get_geofence_manager(app=None) -> GeofenceManager:
    """Get or create geofence manager instance"""
    global _geofence_manager
    
    if _geofence_manager is None:
        gps_service = get_gps_service(app)
        _geofence_manager = GeofenceManager(gps_service)
    
    return _geofence_manager


def get_route_tracking_service(app=None) -> RouteTrackingService:
    """Get or create route tracking service instance"""
    global _route_tracking_service
    
    if _route_tracking_service is None:
        gps_service = get_gps_service(app)
        _route_tracking_service = RouteTrackingService(gps_service)
    
    return _route_tracking_service


def shutdown_gps_service():
    """Shutdown GPS service"""
    global _gps_tracker
    if _gps_tracker:
        _gps_tracker.stop_tracking()
        _gps_tracker = None
        logger.info("GPS service shut down")


# ============================================
# EXPORTS
# ============================================

__all__ = [
    'GPSTracker',
    'LocationService',
    'GeofenceManager',
    'RouteTrackingService',
    'GPSPoint',
    'VehicleTrack',
    'Geofence',
    'get_gps_service',
    'get_location_service',
    'get_geofence_manager',
    'get_route_tracking_service',
    'shutdown_gps_service'
]