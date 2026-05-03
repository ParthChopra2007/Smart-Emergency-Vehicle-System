"""
Smart Emergency Vehicle Priority System - Live Tracking Socket Events
Handles real-time vehicle tracking, location updates, ETA broadcasts,
and corridor progress monitoring via WebSocket
"""

from flask_socketio import emit, join_room, leave_room
from flask_jwt_extended import decode_token
from datetime import datetime
from loguru import logger
import json

from app.extensions import db, cache

# Store active vehicle tracking subscriptions
vehicle_subscribers = {}  # vehicle_id -> list of session_ids
active_tracking_sessions = {}  # session_id -> vehicle_id

# Store last known locations for quick broadcast
last_known_locations = {}  # vehicle_id -> location_data


def register_tracking_events(socketio):
    """
    Register all vehicle tracking related WebSocket events
    """
    
    # ============================================
    # VEHICLE TRACKING SUBSCRIPTION
    # ============================================
    
    @socketio.on('subscribe_vehicle')
    def handle_subscribe_vehicle(data):
        """Subscribe to real-time updates for a specific vehicle"""
        session_id = request.sid
        vehicle_id = data.get('vehicle_id')
        
        if not vehicle_id:
            emit('vehicle_subscribed', {
                'success': False,
                'message': 'vehicle_id required'
            })
            return
        
        # Join vehicle-specific room
        join_room(f'vehicle_{vehicle_id}')
        
        # Track subscription
        if vehicle_id not in vehicle_subscribers:
            vehicle_subscribers[vehicle_id] = []
        if session_id not in vehicle_subscribers[vehicle_id]:
            vehicle_subscribers[vehicle_id].append(session_id)
        
        active_tracking_sessions[session_id] = vehicle_id
        
        # Send last known location immediately
        if vehicle_id in last_known_locations:
            emit('vehicle_location_update', {
                'vehicle_id': vehicle_id,
                'location': last_known_locations[vehicle_id],
                'is_replay': True,
                'timestamp': datetime.utcnow().isoformat()
            })
        
        emit('vehicle_subscribed', {
            'success': True,
            'vehicle_id': vehicle_id,
            'message': f'Subscribed to vehicle {vehicle_id} updates',
            'timestamp': datetime.utcnow().isoformat()
        })
        
        logger.debug(f"Session {session_id} subscribed to vehicle {vehicle_id}")
    
    @socketio.on('unsubscribe_vehicle')
    def handle_unsubscribe_vehicle(data):
        """Unsubscribe from vehicle updates"""
        session_id = request.sid
        vehicle_id = data.get('vehicle_id')
        
        if vehicle_id:
            leave_room(f'vehicle_{vehicle_id}')
            
            # Remove from subscribers
            if vehicle_id in vehicle_subscribers:
                if session_id in vehicle_subscribers[vehicle_id]:
                    vehicle_subscribers[vehicle_id].remove(session_id)
        
        if session_id in active_tracking_sessions:
            del active_tracking_sessions[session_id]
        
        emit('vehicle_unsubscribed', {
            'success': True,
            'vehicle_id': vehicle_id,
            'message': f'Unsubscribed from vehicle {vehicle_id} updates',
            'timestamp': datetime.utcnow().isoformat()
        })
    
    # ============================================
    # VEHICLE LOCATION UPDATE (from GPS device)
    # ============================================
    
    @socketio.on('vehicle_location_update')
    def handle_vehicle_location_update(data):
        """
        Receive location update from vehicle (authenticated drivers only)
        This is the main endpoint for real-time GPS data
        """
        # Get auth info
        token = request.headers.get('Authorization', '').replace('Bearer ', '')
        vehicle_id = data.get('vehicle_id')
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        speed = data.get('speed', 0)
        heading = data.get('heading', 0)
        accuracy = data.get('accuracy', 5)
        
        # Validate input
        if not all([vehicle_id, latitude, longitude]):
            emit('location_update_response', {
                'success': False,
                'message': 'Missing required fields: vehicle_id, latitude, longitude'
            })
            return
        
        # Verify authorization (in production, check token belongs to this vehicle)
        # For now, accept all valid data
        
        # Create location data object
        location_data = {
            'latitude': latitude,
            'longitude': longitude,
            'speed': speed,
            'heading': heading,
            'accuracy': accuracy,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Store last known location
        last_known_locations[vehicle_id] = location_data
        
        # Cache in Redis for quick access (if available)
        if hasattr(cache, 'redis_client') and cache.redis_client:
            cache.redis_client.setex(
                f'vehicle_location:{vehicle_id}',
                60,
                json.dumps(location_data)
            )
        
        # Broadcast to all subscribers of this vehicle
        emit('vehicle_location_update', {
            'vehicle_id': vehicle_id,
            'location': location_data,
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'vehicle_{vehicle_id}', include_self=False)
        
        # Also broadcast to control room for monitoring
        emit('realtime_vehicle_location', {
            'vehicle_id': vehicle_id,
            'location': location_data,
            'timestamp': datetime.utcnow().isoformat()
        }, room='control_room')
        
        # Update database in background (handled by services)
        # This would trigger GPS tracker service update
        
        emit('location_update_response', {
            'success': True,
            'message': 'Location updated',
            'timestamp': datetime.utcnow().isoformat()
        })
        
        logger.debug(f"Vehicle {vehicle_id} location updated: {latitude}, {longitude}, speed: {speed}km/h")
    
    # ============================================
    # BULK LOCATION UPDATE (for multiple vehicles)
    # ============================================
    
    @socketio.on('bulk_vehicle_locations')
    def handle_bulk_locations(data):
        """Receive bulk location updates from dispatch system"""
        locations = data.get('locations', [])
        
        if not locations:
            emit('bulk_locations_response', {
                'success': False,
                'message': 'No locations provided'
            })
            return
        
        updated_count = 0
        for loc in locations:
            vehicle_id = loc.get('vehicle_id')
            latitude = loc.get('latitude')
            longitude = loc.get('longitude')
            
            if vehicle_id and latitude and longitude:
                location_data = {
                    'latitude': latitude,
                    'longitude': longitude,
                    'speed': loc.get('speed', 0),
                    'heading': loc.get('heading', 0),
                    'timestamp': datetime.utcnow().isoformat()
                }
                
                last_known_locations[vehicle_id] = location_data
                emit('vehicle_location_update', {
                    'vehicle_id': vehicle_id,
                    'location': location_data
                }, room=f'vehicle_{vehicle_id}')
                updated_count += 1
        
        emit('bulk_locations_response', {
            'success': True,
            'updated_count': updated_count,
            'timestamp': datetime.utcnow().isoformat()
        })
    
    # ============================================
    # REQUEST VEHICLE LOCATION (pull)
    # ============================================
    
    @socketio.on('request_vehicle_location')
    def handle_request_location(data):
        """Request current location of a vehicle"""
        vehicle_id = data.get('vehicle_id')
        
        if not vehicle_id:
            emit('requested_location', {
                'success': False,
                'message': 'vehicle_id required'
            })
            return
        
        if vehicle_id in last_known_locations:
            emit('requested_location', {
                'success': True,
                'vehicle_id': vehicle_id,
                'location': last_known_locations[vehicle_id],
                'timestamp': datetime.utcnow().isoformat()
            })
        else:
            emit('requested_location', {
                'success': False,
                'vehicle_id': vehicle_id,
                'message': 'Location not available'
            })
    
    # ============================================
    # REQUEST ALL VEHICLE LOCATIONS
    # ============================================
    
    @socketio.on('request_all_locations')
    def handle_request_all_locations(data):
        """Request current locations of all active vehicles"""
        # Get vehicle IDs from last_known_locations
        vehicle_ids = list(last_known_locations.keys())
        
        locations = {}
        for vid in vehicle_ids:
            locations[vid] = last_known_locations[vid]
        
        emit('all_vehicle_locations', {
            'success': True,
            'vehicle_count': len(vehicle_ids),
            'locations': locations,
            'timestamp': datetime.utcnow().isoformat()
        })
    
    # ============================================
    # ETA REQUEST AND BROADCAST
    # ============================================
    
    @socketio.on('request_eta')
    def handle_eta_request(data):
        """Request ETA for a vehicle to destination"""
        vehicle_id = data.get('vehicle_id')
        destination_lat = data.get('destination_latitude')
        destination_lng = data.get('destination_longitude')
        
        if not all([vehicle_id, destination_lat, destination_lng]):
            emit('eta_response', {
                'success': False,
                'message': 'Missing required fields'
            })
            return
        
        # Get current location
        if vehicle_id not in last_known_locations:
            emit('eta_response', {
                'success': False,
                'message': 'Vehicle location not available'
            })
            return
        
        current = last_known_locations[vehicle_id]
        current_speed = current.get('speed', 40)
        
        # Calculate approximate ETA
        from geopy.distance import geodesic
        distance = geodesic(
            (current['latitude'], current['longitude']),
            (destination_lat, destination_lng)
        ).kilometers
        
        speed = current_speed if current_speed > 0 else 40
        eta_seconds = (distance / speed) * 3600
        
        eta_response = {
            'success': True,
            'vehicle_id': vehicle_id,
            'current_location': {
                'latitude': current['latitude'],
                'longitude': current['longitude']
            },
            'destination': {
                'latitude': destination_lat,
                'longitude': destination_lng
            },
            'distance_km': round(distance, 2),
            'estimated_arrival_seconds': int(eta_seconds),
            'estimated_arrival_minutes': round(eta_seconds / 60, 1),
            'estimated_arrival_time': (datetime.utcnow() + timedelta(seconds=eta_seconds)).isoformat(),
            'timestamp': datetime.utcnow().isoformat()
        }
        
        emit('eta_response', eta_response)
        
        # Also broadcast to control room if requested
        if data.get('broadcast_to_control', False):
            emit('vehicle_eta_broadcast', eta_response, room='control_room')
    
    # ============================================
    # CORRIDOR PROGRESS TRACKING
    # ============================================
    
    @socketio.on('subscribe_corridor')
    def handle_subscribe_corridor(data):
        """Subscribe to corridor progress updates"""
        session_id = request.sid
        corridor_id = data.get('corridor_id')
        
        if not corridor_id:
            emit('corridor_subscribed', {
                'success': False,
                'message': 'corridor_id required'
            })
            return
        
        join_room(f'corridor_{corridor_id}')
        
        emit('corridor_subscribed', {
            'success': True,
            'corridor_id': corridor_id,
            'message': f'Subscribed to corridor {corridor_id} updates',
            'timestamp': datetime.utcnow().isoformat()
        })
    
    @socketio.on('corridor_progress_update')
    def handle_corridor_progress(data):
        """Receive corridor progress update from vehicle or system"""
        corridor_id = data.get('corridor_id')
        vehicle_id = data.get('vehicle_id')
        progress_percentage = data.get('progress_percentage', 0)
        remaining_distance = data.get('remaining_distance_km', 0)
        remaining_time = data.get('remaining_time_seconds', 0)
        current_signal = data.get('current_signal_id')
        next_signal = data.get('next_signal_id')
        
        progress_data = {
            'corridor_id': corridor_id,
            'vehicle_id': vehicle_id,
            'progress_percentage': progress_percentage,
            'remaining_distance_km': remaining_distance,
            'remaining_time_seconds': remaining_time,
            'current_signal_id': current_signal,
            'next_signal_id': next_signal,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Broadcast to corridor subscribers
        emit('corridor_progress', progress_data, room=f'corridor_{corridor_id}')
        
        # Also broadcast to control room
        emit('corridor_progress_control', progress_data, room='control_room')
        
        logger.debug(f"Corridor {corridor_id} progress: {progress_percentage}%")
    
    # ============================================
    # GEO-FENCE ALERTS
    # ============================================
    
    @socketio.on('geofence_alert_ack')
    def handle_geofence_ack(data):
        """Acknowledge geofence alert"""
        alert_id = data.get('alert_id')
        vehicle_id = data.get('vehicle_id')
        
        if alert_id and vehicle_id:
            # Mark alert as acknowledged in database
            emit('geofence_alert_acknowledged', {
                'alert_id': alert_id,
                'vehicle_id': vehicle_id,
                'acknowledged_by': request.sid,
                'timestamp': datetime.utcnow().isoformat()
            }, room='control_room')
    
    # ============================================
    # HELPER FUNCTIONS FOR PROGRAMMATIC USE
    # ============================================
    
    def broadcast_vehicle_update(vehicle_id, location_data):
        """Programmatically broadcast vehicle update"""
        socketio.emit('vehicle_location_update', {
            'vehicle_id': vehicle_id,
            'location': location_data,
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'vehicle_{vehicle_id}')
    
    def broadcast_eta_update(vehicle_id, eta_data):
        """Programmatically broadcast ETA update"""
        socketio.emit('eta_update', {
            'vehicle_id': vehicle_id,
            'eta': eta_data,
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'vehicle_{vehicle_id}')
    
    def broadcast_corridor_update(corridor_id, progress_data):
        """Programmatically broadcast corridor update"""
        socketio.emit('corridor_progress', progress_data, room=f'corridor_{corridor_id}')
    
    # Store broadcast functions for external use
    socketio.broadcast_vehicle_update = broadcast_vehicle_update
    socketio.broadcast_eta_update = broadcast_eta_update
    socketio.broadcast_corridor_update = broadcast_corridor_update
    
    logger.info("✅ Live tracking WebSocket events registered")
    
    return socketio


# ============================================
# HELPER FUNCTIONS (for use by other modules)
# ============================================

def notify_vehicle_arrival(vehicle_id: int, destination: str):
    """Notify subscribers that vehicle has arrived"""
    if socketio:
        socketio.emit('vehicle_arrived', {
            'vehicle_id': vehicle_id,
            'destination': destination,
            'arrival_time': datetime.utcnow().isoformat()
        }, room=f'vehicle_{vehicle_id}')
        socketio.emit('vehicle_arrived_control', {
            'vehicle_id': vehicle_id,
            'destination': destination,
            'arrival_time': datetime.utcnow().isoformat()
        }, room='control_room')
        logger.info(f"Vehicle {vehicle_id} arrived at {destination}")


def notify_emergency_vehicle_detected(vehicle_id: int, location: dict):
    """Notify control room about emergency vehicle detection"""
    if socketio:
        socketio.emit('emergency_vehicle_detected', {
            'vehicle_id': vehicle_id,
            'location': location,
            'timestamp': datetime.utcnow().isoformat()
        }, room='control_room')


def notify_route_deviation(vehicle_id: int, corridor_id: int, deviation_km: float):
    """Notify about route deviation"""
    if socketio:
        socketio.emit('route_deviation_alert', {
            'vehicle_id': vehicle_id,
            'corridor_id': corridor_id,
            'deviation_km': deviation_km,
            'timestamp': datetime.utcnow().isoformat()
        }, room='control_room')


def get_last_known_location(vehicle_id: int) -> dict:
    """Get last known location for a vehicle"""
    return last_known_locations.get(vehicle_id)


def get_all_vehicle_locations() -> dict:
    """Get all last known locations"""
    return last_known_locations.copy()


# ============================================
# EXPORTS
# ============================================

__all__ = [
    'register_tracking_events',
    'notify_vehicle_arrival',
    'notify_emergency_vehicle_detected',
    'notify_route_deviation',
    'get_last_known_location',
    'get_all_vehicle_locations'
]

# Import for request context
from flask_socketio import request
from datetime import timedelta