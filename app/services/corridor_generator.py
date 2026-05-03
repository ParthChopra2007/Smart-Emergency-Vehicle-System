"""
Smart Emergency Vehicle Priority System - Corridor Generator Service
Handles green corridor generation, path optimization, signal coordination,
and real-time ETA calculation for emergency vehicles
"""

import math
import heapq
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass
from collections import defaultdict
from loguru import logger
import threading
import json

from geopy.distance import geodesic
from app.extensions import db, socketio, cache

# ============================================
# DATA CLASSES
# ============================================

@dataclass
class RoutePoint:
    """Represents a point on the route"""
    latitude: float
    longitude: float
    order: int
    is_signal: bool = False
    signal_id: int = None
    intersection_name: str = None

@dataclass
class SignalOnRoute:
    """Represents a traffic signal on the route"""
    id: int
    intersection_name: str
    latitude: float
    longitude: float
    distance_from_start: float
    estimated_arrival_time: datetime
    order: int

@dataclass
class CorridorPlan:
    """Complete corridor plan"""
    corridor_id: int
    vehicle_id: int
    start_point: Tuple[float, float]
    destination_point: Tuple[float, float]
    total_distance_km: float
    estimated_duration_seconds: int
    signals_on_route: List[SignalOnRoute]
    path_points: List[RoutePoint]
    priority_level: int

# ============================================
# PATH CALCULATOR
# ============================================

class PathCalculator:
    """
    Calculates optimal path for emergency vehicles
    Uses Dijkstra/A* algorithm with traffic data
    """
    
    def __init__(self):
        self.graph = {}  # Road network graph
        self.traffic_weights = {}  # Real-time traffic weights
        self._init_road_network()
    
    def _init_road_network(self):
        """Initialize road network graph (simplified - would use OSM in production)"""
        # In production, this would load from a map service or database
        # For demo, creating a simple graph
        self.graph = {
            # Intersection nodes with connections to signals
            1: {2: 1.5, 3: 2.0},   # Connaught Place
            2: {1: 1.5, 4: 1.8},   # India Gate
            3: {1: 2.0, 4: 2.2},   # Rajiv Chowk
            4: {2: 1.8, 3: 2.2, 5: 3.0},  # ITO
            5: {4: 3.0, 6: 2.5},   # AIIMS intersection
            6: {5: 2.5}            # AIIMS Hospital
        }
        logger.info("Road network initialized with 6 nodes")
    
    def update_traffic_weight(self, node_a: int, node_b: int, weight: float):
        """Update traffic weight between two nodes"""
        self.traffic_weights[(node_a, node_b)] = weight
        self.traffic_weights[(node_b, node_a)] = weight
        logger.debug(f"Traffic weight updated: {node_a}->{node_b} = {weight}")
    
    def get_traffic_multiplier(self, node_a: int, node_b: int) -> float:
        """Get traffic multiplier for edge (1.0 = normal, >1.0 = congested)"""
        weight = self.traffic_weights.get((node_a, node_b))
        if weight:
            return weight / 1.0  # Normalize
        return 1.0
    
    def calculate_shortest_path(self, start_lat: float, start_lng: float,
                                 dest_lat: float, dest_lng: float) -> Optional[List[int]]:
        """
        Calculate shortest path using Dijkstra's algorithm
        Returns list of node IDs
        """
        # Find nearest nodes to start and destination
        start_node = self._find_nearest_node(start_lat, start_lng)
        dest_node = self._find_nearest_node(dest_lat, dest_lng)
        
        if not start_node or not dest_node:
            logger.warning("Could not find nearest nodes for path calculation")
            return None
        
        # Dijkstra's algorithm
        distances = {node: float('inf') for node in self.graph}
        distances[start_node] = 0
        previous = {node: None for node in self.graph}
        pq = [(0, start_node)]
        
        while pq:
            current_dist, current = heapq.heappop(pq)
            
            if current == dest_node:
                break
            
            if current_dist > distances[current]:
                continue
            
            for neighbor, base_distance in self.graph.get(current, {}).items():
                traffic_mult = self.get_traffic_multiplier(current, neighbor)
                distance = base_distance * traffic_mult
                new_dist = current_dist + distance
                
                if new_dist < distances[neighbor]:
                    distances[neighbor] = new_dist
                    previous[neighbor] = current
                    heapq.heappush(pq, (new_dist, neighbor))
        
        # Reconstruct path
        path = []
        current = dest_node
        while current is not None:
            path.append(current)
            current = previous[current]
        
        path.reverse()
        return path if len(path) > 1 else None
    
    def _find_nearest_node(self, latitude: float, longitude: float) -> Optional[int]:
        """Find nearest graph node to given coordinates"""
        # Simplified - would use spatial indexing in production
        node_coords = {
            1: (28.6304, 77.2177),   # Connaught Place
            2: (28.6129, 77.2295),   # India Gate
            3: (28.6328, 77.2198),   # Rajiv Chowk
            4: (28.6265, 77.2355),   # ITO
            5: (28.5675, 77.2100),   # AIIMS intersection
            6: (28.5665, 77.2080)    # AIIMS Hospital
        }
        
        nearest = None
        min_distance = float('inf')
        
        for node_id, (lat, lng) in node_coords.items():
            distance = geodesic((latitude, longitude), (lat, lng)).kilometers
            if distance < min_distance:
                min_distance = distance
                nearest = node_id
        
        return nearest if min_distance < 5 else None  # Within 5 km
    
    def get_path_distance(self, path: List[int]) -> float:
        """Calculate total distance of a path in kilometers"""
        if not path or len(path) < 2:
            return 0.0
        
        total = 0.0
        for i in range(len(path) - 1):
            distance = self.graph.get(path[i], {}).get(path[i+1], 0)
            total += distance
        return total


# ============================================
# SIGNAL COORDINATOR
# ============================================

class SignalCoordinator:
    """
    Coordinates traffic signals for green corridor
    Manages signal activation timing and sequencing
    """
    
    def __init__(self):
        self.active_corridors = {}  # corridor_id -> corridor_data
        self.signal_activation_times = {}  # (corridor_id, signal_id) -> activation_time
        self._load_signals()
    
    def _load_signals(self):
        """Load traffic signals from database"""
        from app.models.traffic_signal import get_all_signals
        
        try:
            signals = get_all_signals()
            self.signals = {s.id: s for s in signals}
            logger.info(f"Loaded {len(self.signals)} traffic signals")
        except Exception as e:
            logger.error(f"Failed to load signals: {e}")
            self.signals = {}
    
    def get_signals_on_route(self, path: List[int]) -> List[SignalOnRoute]:
        """
        Get all traffic signals along the calculated path
        """
        signals_on_route = []
        
        # Map nodes to signal IDs (simplified mapping)
        node_signal_map = {
            1: 1,  # Connaught Place -> Signal 1
            2: 2,  # India Gate -> Signal 2
            3: 3,  # Rajiv Chowk -> Signal 3
            4: 4,  # ITO -> Signal 4
            5: 5   # AIIMS -> Signal 5
        }
        
        accumulated_distance = 0
        order = 0
        
        for i in range(len(path) - 1):
            edge_distance = self._get_edge_distance(path[i], path[i+1])
            accumulated_distance += edge_distance
            
            if path[i+1] in node_signal_map:
                signal_id = node_signal_map[path[i+1]]
                if signal_id in self.signals:
                    signal = self.signals[signal_id]
                    signals_on_route.append(SignalOnRoute(
                        id=signal.id,
                        intersection_name=signal.intersection_name,
                        latitude=signal.latitude,
                        longitude=signal.longitude,
                        distance_from_start=accumulated_distance,
                        estimated_arrival_time=datetime.utcnow(),
                        order=order
                    ))
                    order += 1
        
        return signals_on_route
    
    def _get_edge_distance(self, node_a: int, node_b: int) -> float:
        """Get distance between two nodes in kilometers"""
        from app.services.corridor_generator import PathCalculator
        calc = PathCalculator()
        return calc.graph.get(node_a, {}).get(node_b, 0.0)
    
    def calculate_activation_timings(self, corridor_id: int, signals: List[SignalOnRoute],
                                      vehicle_speed_kmh: float = 40.0) -> Dict[int, datetime]:
        """
        Calculate optimal activation times for each signal
        """
        activation_times = {}
        
        for signal in signals:
            # Time to reach this signal from start
            time_to_reach_hours = signal.distance_from_start / vehicle_speed_kmh
            time_to_reach_seconds = time_to_reach_hours * 3600
            
            # Activate signal 15 seconds before vehicle arrives
            activation_offset = max(0, time_to_reach_seconds - 15)
            activation_time = datetime.utcnow() + timedelta(seconds=activation_offset)
            
            activation_times[signal.id] = activation_time
            self.signal_activation_times[(corridor_id, signal.id)] = activation_time
        
        return activation_times
    
    def activate_signal(self, corridor_id: int, signal_id: int, vehicle_id: int, duration: int = 60) -> bool:
        """
        Activate green corridor on a specific signal
        """
        from app.models.traffic_signal import find_signal_by_id
        
        try:
            signal = find_signal_by_id(signal_id)
            if not signal:
                logger.error(f"Signal {signal_id} not found")
                return False
            
            # Activate green corridor
            signal.set_green_corridor(corridor_id, vehicle_id, duration)
            
            # Emit real-time update
            socketio.emit('signal_corridor_activated', {
                'corridor_id': corridor_id,
                'signal_id': signal_id,
                'intersection_name': signal.intersection_name,
                'duration_seconds': duration,
                'timestamp': datetime.utcnow().isoformat()
            }, broadcast=True)
            
            logger.info(f"Signal {signal.intersection_name} activated for corridor {corridor_id}")
            return True
            
        except Exception as e:
            logger.error(f"Activate signal error: {e}")
            return False
    
    def deactivate_corridor_signals(self, corridor_id: int):
        """
        Deactivate all signals for a corridor
        """
        from app.models.traffic_signal import find_signal_by_id
        
        for (corr_id, signal_id), activation_time in self.signal_activation_times.items():
            if corr_id == corridor_id:
                signal = find_signal_by_id(signal_id)
                if signal:
                    signal.deactivate_green_corridor()
        
        logger.info(f"All signals deactivated for corridor {corridor_id}")


# ============================================
# ETA CALCULATOR
# ============================================

class ETACalculator:
    """
    Calculates real-time ETA for emergency vehicles
    Considers traffic conditions, signal delays, and route updates
    """
    
    def __init__(self):
        self.traffic_speeds = defaultdict(lambda: 40.0)  # Default 40 km/h
        self._init_traffic_speeds()
    
    def _init_traffic_speeds(self):
        """Initialize traffic speeds for different road segments"""
        # Would load from real-time traffic API in production
        self.traffic_speeds = {
            'highway': 60.0,
            'arterial': 45.0,
            'local': 30.0,
            'congested': 15.0,
            'gridlock': 5.0
        }
    
    def get_speed_for_road(self, road_type: str, congestion_level: str = 'low') -> float:
        """
        Get estimated speed based on road type and congestion
        """
        base_speed = self.traffic_speeds.get(road_type, 40.0)
        
        # Apply congestion multiplier
        congestion_multipliers = {
            'low': 1.0,
            'medium': 0.7,
            'high': 0.4,
            'gridlock': 0.1
        }
        
        multiplier = congestion_multipliers.get(congestion_level, 1.0)
        return base_speed * multiplier
    
    def calculate_eta(self, distance_km: float, current_speed_kmh: float = None,
                      road_type: str = 'arterial', congestion: str = 'low') -> int:
        """
        Calculate ETA in seconds
        """
        if current_speed_kmh and current_speed_kmh > 0:
            speed = current_speed_kmh
        else:
            speed = self.get_speed_for_road(road_type, congestion)
        
        if speed <= 0:
            return 3600  # 1 hour default
        
        eta_seconds = (distance_km / speed) * 3600
        return int(eta_seconds)
    
    def calculate_eta_to_signal(self, distance_km: float, vehicle_speed_kmh: float,
                                 signal_delay_seconds: int = 0) -> int:
        """
        Calculate ETA to a specific signal
        """
        travel_time = (distance_km / vehicle_speed_kmh) * 3600 if vehicle_speed_kmh > 0 else 0
        return int(travel_time + signal_delay_seconds)


# ============================================
# CORRIDOR GENERATOR (Main Service)
# ============================================

class CorridorGenerator:
    """
    Main service for generating and managing green corridors
    Coordinates path calculation, signal activation, and real-time tracking
    """
    
    def __init__(self, app=None):
        self.app = app
        self.path_calculator = PathCalculator()
        self.signal_coordinator = SignalCoordinator()
        self.eta_calculator = ETACalculator()
        self.active_corridors = {}
        self._update_thread = None
        self._is_running = False
    
    def start_monitoring(self):
        """Start background monitoring for active corridors"""
        if self._update_thread is None:
            self._is_running = True
            self._update_thread = threading.Thread(target=self._monitor_corridors)
            self._update_thread.daemon = True
            self._update_thread.start()
            logger.info("Corridor monitoring started")
    
    def stop_monitoring(self):
        """Stop background monitoring"""
        self._is_running = False
        if self._update_thread:
            self._update_thread.join(timeout=5)
    
    def _monitor_corridors(self):
        """Background thread to monitor and update active corridors"""
        while self._is_running:
            try:
                from app.models.corridor import get_active_corridors
                
                active = get_active_corridors()
                for corridor in active:
                    if corridor.id not in self.active_corridors:
                        self.active_corridors[corridor.id] = corridor
                    
                    # Check if corridor expired
                    if corridor.corridor_active_until and corridor.corridor_active_until < datetime.utcnow():
                        self._handle_expired_corridor(corridor)
                
                # Send real-time updates
                self._broadcast_updates()
                
                import time
                time.sleep(5)  # Update every 5 seconds
                
            except Exception as e:
                logger.error(f"Corridor monitoring error: {e}")
                import time
                time.sleep(10)
    
    def _handle_expired_corridor(self, corridor):
        """Handle expired corridor"""
        corridor.expire()
        self.signal_coordinator.deactivate_corridor_signals(corridor.id)
        if corridor.id in self.active_corridors:
            del self.active_corridors[corridor.id]
        logger.info(f"Corridor {corridor.id} expired and removed")
    
    def _broadcast_updates(self):
        """Broadcast real-time corridor updates via WebSocket"""
        updates = []
        for corridor_id, corridor in self.active_corridors.items():
            updates.append({
                'corridor_id': corridor.id,
                'status': corridor.status.value if corridor.status else None,
                'progress_percentage': corridor.progress_percentage,
                'remaining_distance_km': corridor.remaining_distance_km,
                'remaining_time_seconds': corridor.remaining_time_seconds,
                'signals_passed': corridor.signals_passed,
                'signals_total': corridor.signals_total
            })
        
        if updates:
            socketio.emit('corridor_updates', {
                'corridors': updates,
                'timestamp': datetime.utcnow().isoformat()
            }, broadcast=True)
    
    def generate_corridor(self, vehicle_id: int, start_lat: float, start_lng: float,
                          dest_lat: float, dest_lng: float, priority_level: int = 1) -> Optional[CorridorPlan]:
        """
        Generate a complete green corridor plan
        """
        try:
            # Calculate optimal path
            path = self.path_calculator.calculate_shortest_path(start_lat, start_lng, dest_lat, dest_lng)
            
            if not path:
                logger.error(f"Could not calculate path for vehicle {vehicle_id}")
                return None
            
            # Get signals on route
            signals = self.signal_coordinator.get_signals_on_route(path)
            
            # Calculate total distance
            total_distance = self.path_calculator.get_path_distance(path)
            
            # Calculate estimated duration
            vehicle_speed = self._get_vehicle_speed(vehicle_id)
            estimated_duration = self.eta_calculator.calculate_eta(
                total_distance, vehicle_speed, 'arterial', 'low'
            )
            
            # Generate path points
            path_points = self._generate_path_points(start_lat, start_lng, dest_lat, dest_lng, signals)
            
            # Create corridor plan
            plan = CorridorPlan(
                corridor_id=0,  # Will be assigned after DB save
                vehicle_id=vehicle_id,
                start_point=(start_lat, start_lng),
                destination_point=(dest_lat, dest_lng),
                total_distance_km=total_distance,
                estimated_duration_seconds=estimated_duration,
                signals_on_route=signals,
                path_points=path_points,
                priority_level=priority_level
            )
            
            logger.info(f"Corridor generated for vehicle {vehicle_id}: {total_distance:.2f} km, {estimated_duration}s")
            return plan
            
        except Exception as e:
            logger.error(f"Generate corridor error: {e}")
            return None
    
    def _get_vehicle_speed(self, vehicle_id: int) -> float:
        """Get current speed of vehicle"""
        from app.models.vehicle import find_vehicle_by_id
        
        vehicle = find_vehicle_by_id(vehicle_id)
        if vehicle and vehicle.current_speed:
            return float(vehicle.current_speed)
        return 40.0  # Default speed
    
    def _generate_path_points(self, start_lat: float, start_lng: float,
                               dest_lat: float, dest_lng: float,
                               signals: List[SignalOnRoute]) -> List[RoutePoint]:
        """Generate detailed path points including signals"""
        points = [
            RoutePoint(latitude=start_lat, longitude=start_lng, order=0)
        ]
        
        # Add signal points
        for signal in signals:
            points.append(RoutePoint(
                latitude=signal.latitude,
                longitude=signal.longitude,
                order=signal.order + 1,
                is_signal=True,
                signal_id=signal.id,
                intersection_name=signal.intersection_name
            ))
        
        points.append(RoutePoint(
            latitude=dest_lat,
            longitude=dest_lng,
            order=len(points)
        ))
        
        return points
    
    def activate_corridor_signals(self, corridor_id: int, vehicle_id: int,
                                    signals: List[SignalOnRoute], vehicle_speed_kmh: float = 40.0):
        """
        Calculate and activate signals for a corridor
        """
        activation_times = self.signal_coordinator.calculate_activation_timings(
            corridor_id, signals, vehicle_speed_kmh
        )
        
        # Schedule signal activations
        for signal_id, activation_time in activation_times.items():
            delay = (activation_time - datetime.utcnow()).total_seconds()
            if delay <= 0:
                # Activate immediately
                self.signal_coordinator.activate_signal(corridor_id, signal_id, vehicle_id)
            else:
                # Schedule for later (would use Celery in production)
                threading.Timer(delay, self.signal_coordinator.activate_signal,
                                args=[corridor_id, signal_id, vehicle_id]).start()
                logger.info(f"Signal {signal_id} scheduled for activation in {delay:.1f}s")
    
    def update_corridor_progress(self, corridor_id: int, current_lat: float, current_lng: float) -> Dict:
        """
        Update real-time progress of a corridor
        """
        from app.models.corridor import find_corridor_by_id
        
        corridor = find_corridor_by_id(corridor_id)
        if not corridor:
            return {'error': 'Corridor not found'}
        
        # Update progress
        progress = corridor.update_progress(current_lat, current_lng)
        
        # Check if next signal needs activation
        if corridor.next_signal_id:
            distance_to_next = self._get_distance_to_signal(current_lat, current_lng, corridor.next_signal_id)
            
            # Activate next signal if within 500 meters and not yet activated
            if distance_to_next and distance_to_next <= 0.5:
                self.signal_coordinator.activate_signal(
                    corridor_id, corridor.next_signal_id, corridor.vehicle_id
                )
        
        return progress
    
    def _get_distance_to_signal(self, lat: float, lng: float, signal_id: int) -> Optional[float]:
        """Get distance from current position to a signal"""
        from app.models.traffic_signal import find_signal_by_id
        
        signal = find_signal_by_id(signal_id)
        if signal:
            return geodesic((lat, lng), (signal.latitude, signal.longitude)).kilometers
        return None
    
    def get_corridor_status(self, corridor_id: int) -> Optional[Dict]:
        """
        Get comprehensive status of a corridor
        """
        from app.models.corridor import find_corridor_by_id
        
        corridor = find_corridor_by_id(corridor_id)
        if not corridor:
            return None
        
        return {
            'corridor_id': corridor.id,
            'status': corridor.status.value if corridor.status else None,
            'progress_percentage': corridor.progress_percentage,
            'remaining_distance_km': corridor.remaining_distance_km,
            'remaining_time_seconds': corridor.remaining_time_seconds,
            'signals_activated': corridor.signals_activated,
            'signals_passed': corridor.signals_passed,
            'signals_total': corridor.signals_total,
            'next_signal': self._get_next_signal_info(corridor),
            'eta': corridor.get_eta(),
            'last_update': corridor.last_progress_update.isoformat() if corridor.last_progress_update else None
        }
    
    def _get_next_signal_info(self, corridor) -> Optional[Dict]:
        """Get information about next signal on route"""
        if corridor.next_signal_id:
            from app.models.traffic_signal import find_signal_by_id
            signal = find_signal_by_id(corridor.next_signal_id)
            if signal:
                return {
                    'id': signal.id,
                    'name': signal.intersection_name,
                    'latitude': signal.latitude,
                    'longitude': signal.longitude
                }
        return None
    
    def get_stats(self) -> Dict:
        """Get service statistics"""
        return {
            'active_corridors': len(self.active_corridors),
            'total_corridors_generated': sum(1 for _ in self.active_corridors),
            'is_monitoring': self._is_running,
            'path_calculator_ready': self.path_calculator is not None,
            'signal_coordinator_ready': self.signal_coordinator is not None
        }
    
    def health_check(self) -> bool:
        """Check if service is healthy"""
        return self.path_calculator is not None


# ============================================
# SERVICE FACTORY FUNCTIONS
# ============================================

_corridor_service = None


def get_corridor_service(app=None) -> CorridorGenerator:
    """Get or create corridor generator service instance"""
    global _corridor_service
    
    if _corridor_service is None:
        _corridor_service = CorridorGenerator(app)
        _corridor_service.start_monitoring()
    
    return _corridor_service


def shutdown_corridor_service():
    """Shutdown corridor service"""
    global _corridor_service
    if _corridor_service:
        _corridor_service.stop_monitoring()
        _corridor_service = None
        logger.info("Corridor service shut down")


# ============================================
# EXPORTS
# ============================================

__all__ = [
    'CorridorGenerator',
    'PathCalculator',
    'SignalCoordinator',
    'ETACalculator',
    'RoutePoint',
    'SignalOnRoute',
    'CorridorPlan',
    'get_corridor_service',
    'shutdown_corridor_service'
]