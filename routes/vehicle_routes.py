"""
Smart Emergency Vehicle Priority System - Vehicle Routes
Handles vehicle tracking, dispatching, location updates, and vehicle management
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime
from loguru import logger
from functools import wraps

from app.extensions import db, cache, limiter, socketio
from app.models.user import User, UserRole, find_user_by_id
from app.models.vehicle import (
    EmergencyVehicle, 
    VehicleType, 
    VehicleStatus, 
    VehicleEmergencyLevel,
    VehicleLocationHistory,
    find_vehicle_by_id,
    find_vehicle_by_registration,
    find_vehicle_by_uuid,
    get_all_emergency_vehicles,
    get_available_vehicles,
    get_nearest_vehicle
)
from app.routes.auth_routes import role_required

# Create Blueprint
vehicle_bp = Blueprint('vehicles', __name__)

# ============================================
# HELPER FUNCTIONS
# ============================================

def emit_vehicle_update(vehicle):
    """Emit real-time vehicle update via WebSocket"""
    socketio.emit('vehicle_location_update', {
        'vehicle_id': vehicle.id,
        'registration_number': vehicle.registration_number,
        'vehicle_type': vehicle.vehicle_type.value if vehicle.vehicle_type else None,
        'location': vehicle.get_current_location(),
        'status': vehicle.status.value if vehicle.status else None,
        'emergency_level': vehicle.emergency_level.value if vehicle.emergency_level else None,
        'is_siren_active': vehicle.is_siren_active,
        'timestamp': datetime.utcnow().isoformat()
    }, broadcast=True)
    
    logger.debug(f"Real-time update emitted for vehicle {vehicle.registration_number}")

# ============================================
# PUBLIC VEHICLE ROUTES (Driver/Controller access)
# ============================================

@vehicle_bp.route('/list', methods=['GET'])
@jwt_required()
@cache.cached(timeout=30)  # Cache for 30 seconds
def get_vehicles():
    """
    Get all emergency vehicles with filters
    GET /api/v1/vehicles/list
    Query params: ?vehicle_type=ambulance&status=available
    """
    try:
        vehicle_type = request.args.get('vehicle_type')
        status = request.args.get('status')
        
        # Convert string to enum if provided
        vehicle_type_enum = None
        if vehicle_type:
            try:
                vehicle_type_enum = VehicleType(vehicle_type)
            except ValueError:
                return jsonify({'error': f'Invalid vehicle type: {vehicle_type}'}), 400
        
        status_enum = None
        if status:
            try:
                status_enum = VehicleStatus(status)
            except ValueError:
                return jsonify({'error': f'Invalid status: {status}'}), 400
        
        vehicles = get_all_emergency_vehicles(vehicle_type_enum, status_enum)
        
        return jsonify({
            'success': True,
            'count': len(vehicles),
            'vehicles': [v.to_dict() for v in vehicles]
        }), 200
        
    except Exception as e:
        logger.error(f"Get vehicles error: {str(e)}")
        return jsonify({'error': 'Failed to fetch vehicles'}), 500


@vehicle_bp.route('/live', methods=['GET'])
@jwt_required()
def get_live_vehicles():
    """
    Get live vehicle locations (real-time tracking)
    GET /api/v1/vehicles/live
    """
    try:
        vehicles = get_all_emergency_vehicles()
        
        live_data = []
        for vehicle in vehicles:
            if vehicle.current_latitude and vehicle.current_longitude:
                live_data.append({
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
                    'emergency_level': vehicle.emergency_level.value if vehicle.emergency_level else None,
                    'is_siren_active': vehicle.is_siren_active,
                    'last_update': vehicle.last_location_update.isoformat() if vehicle.last_location_update else None,
                    'destination': {
                        'name': vehicle.current_destination,
                        'latitude': vehicle.current_destination_latitude,
                        'longitude': vehicle.current_destination_longitude
                    } if vehicle.current_destination else None
                })
        
        return jsonify({
            'success': True,
            'count': len(live_data),
            'vehicles': live_data,
            'timestamp': datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Get live vehicles error: {str(e)}")
        return jsonify({'error': 'Failed to fetch live vehicles'}), 500


@vehicle_bp.route('/<int:vehicle_id>', methods=['GET'])
@jwt_required()
def get_vehicle(vehicle_id):
    """
    Get specific vehicle details
    GET /api/v1/vehicles/<vehicle_id>
    """
    try:
        vehicle = find_vehicle_by_id(vehicle_id)
        
        if not vehicle:
            return jsonify({'error': 'Vehicle not found'}), 404
        
        return jsonify({
            'success': True,
            'vehicle': vehicle.to_dict(include_sensitive=request.args.get('sensitive', 'false').lower() == 'true')
        }), 200
        
    except Exception as e:
        logger.error(f"Get vehicle error: {str(e)}")
        return jsonify({'error': 'Failed to fetch vehicle'}), 500


@vehicle_bp.route('/by-registration/<registration>', methods=['GET'])
@jwt_required()
def get_vehicle_by_registration(registration):
    """
    Get vehicle by registration number
    GET /api/v1/vehicles/by-registration/DL-01-AB-1234
    """
    try:
        vehicle = find_vehicle_by_registration(registration.upper())
        
        if not vehicle:
            return jsonify({'error': 'Vehicle not found'}), 404
        
        return jsonify({
            'success': True,
            'vehicle': vehicle.to_dict()
        }), 200
        
    except Exception as e:
        logger.error(f"Get vehicle by registration error: {str(e)}")
        return jsonify({'error': 'Failed to fetch vehicle'}), 500


@vehicle_bp.route('/available', methods=['GET'])
@jwt_required()
def get_available():
    """
    Get all available emergency vehicles
    GET /api/v1/vehicles/available?vehicle_type=ambulance
    """
    try:
        vehicle_type = request.args.get('vehicle_type')
        
        vehicle_type_enum = None
        if vehicle_type:
            try:
                vehicle_type_enum = VehicleType(vehicle_type)
            except ValueError:
                return jsonify({'error': f'Invalid vehicle type: {vehicle_type}'}), 400
        
        vehicles = get_available_vehicles(vehicle_type_enum)
        
        return jsonify({
            'success': True,
            'count': len(vehicles),
            'vehicles': [v.to_dict() for v in vehicles]
        }), 200
        
    except Exception as e:
        logger.error(f"Get available vehicles error: {str(e)}")
        return jsonify({'error': 'Failed to fetch available vehicles'}), 500


@vehicle_bp.route('/nearest', methods=['GET'])
@jwt_required()
def get_nearest():
    """
    Get nearest vehicle to a location
    GET /api/v1/vehicles/nearest?lat=28.6139&lng=77.2090&type=ambulance&max_distance=10
    """
    try:
        latitude = request.args.get('lat', type=float)
        longitude = request.args.get('lng', type=float)
        vehicle_type = request.args.get('type')
        max_distance = request.args.get('max_distance', 10, type=float)
        
        if not latitude or not longitude:
            return jsonify({'error': 'Latitude and longitude are required'}), 400
        
        vehicle_type_enum = None
        if vehicle_type:
            try:
                vehicle_type_enum = VehicleType(vehicle_type)
            except ValueError:
                return jsonify({'error': f'Invalid vehicle type: {vehicle_type}'}), 400
        
        vehicle, distance = get_nearest_vehicle(latitude, longitude, vehicle_type_enum, max_distance)
        
        if not vehicle:
            return jsonify({
                'success': False,
                'message': f'No {vehicle_type or "emergency"} vehicle found within {max_distance} km'
            }), 404
        
        return jsonify({
            'success': True,
            'vehicle': vehicle.to_dict(),
            'distance_km': round(distance, 2) if distance else None
        }), 200
        
    except Exception as e:
        logger.error(f"Get nearest vehicle error: {str(e)}")
        return jsonify({'error': 'Failed to find nearest vehicle'}), 500


# ============================================
# VEHICLE LOCATION UPDATES (Real-time)
# ============================================

@vehicle_bp.route('/<int:vehicle_id>/location', methods=['PUT'])
@jwt_required()
@limiter.limit("60 per minute")  # Frequent updates allowed
def update_vehicle_location(vehicle_id):
    """
    Update vehicle location (called by GPS device or driver app)
    PUT /api/v1/vehicles/<vehicle_id>/location
    Body: {
        "latitude": 28.6139,
        "longitude": 77.2090,
        "speed": 45.5,
        "heading": 180
    }
    """
    try:
        current_user_id = get_jwt_identity()
        user = find_user_by_id(current_user_id)
        
        vehicle = find_vehicle_by_id(vehicle_id)
        
        if not vehicle:
            return jsonify({'error': 'Vehicle not found'}), 404
        
        # Check permission: driver of this vehicle OR admin OR control room
        if not (user.is_admin() or user.role == UserRole.CONTROL_ROOM or 
                vehicle.assigned_driver_id == current_user_id):
            return jsonify({'error': 'Permission denied'}), 403
        
        data = request.get_json()
        
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        speed = data.get('speed')
        heading = data.get('heading')
        
        if not latitude or not longitude:
            return jsonify({'error': 'Latitude and longitude are required'}), 400
        
        # Update location
        vehicle.update_location(latitude, longitude, speed, heading)
        
        # Store in history
        VehicleLocationHistory.record_location(vehicle_id, latitude, longitude, speed, heading)
        
        # Cache the location in Redis for quick access
        from app.extensions import get_redis
        redis_client = get_redis()
        if redis_client:
            redis_client.setex(
                f'vehicle_location:{vehicle_id}',
                60,  # Expire after 60 seconds
                f'{latitude},{longitude},{speed},{heading}'
            )
        
        # Emit real-time update
        emit_vehicle_update(vehicle)
        
        return jsonify({
            'success': True,
            'message': 'Location updated successfully',
            'location': vehicle.get_current_location()
        }), 200
        
    except Exception as e:
        logger.error(f"Update vehicle location error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to update location'}), 500


@vehicle_bp.route('/<int:vehicle_id>/location/history', methods=['GET'])
@jwt_required()
def get_vehicle_location_history(vehicle_id):
    """
    Get vehicle location history
    GET /api/v1/vehicles/<vehicle_id>/location/history?hours=24&limit=100
    """
    try:
        vehicle = find_vehicle_by_id(vehicle_id)
        
        if not vehicle:
            return jsonify({'error': 'Vehicle not found'}), 404
        
        hours = request.args.get('hours', 24, type=int)
        limit = request.args.get('limit', 100, type=int)
        
        # Calculate cutoff time
        cutoff_time = datetime.utcnow() - datetime.timedelta(hours=hours)
        
        history = VehicleLocationHistory.query.filter(
            VehicleLocationHistory.vehicle_id == vehicle_id,
            VehicleLocationHistory.recorded_at >= cutoff_time
        ).order_by(VehicleLocationHistory.recorded_at.desc()).limit(limit).all()
        
        return jsonify({
            'success': True,
            'vehicle_id': vehicle_id,
            'count': len(history),
            'history': [h.to_dict() for h in history]
        }), 200
        
    except Exception as e:
        logger.error(f"Get location history error: {str(e)}")
        return jsonify({'error': 'Failed to fetch location history'}), 500


# ============================================
# VEHICLE STATUS MANAGEMENT
# ============================================

@vehicle_bp.route('/<int:vehicle_id>/status', methods=['PUT'])
@jwt_required()
def update_vehicle_status(vehicle_id):
    """
    Update vehicle status
    PUT /api/v1/vehicles/<vehicle_id>/status
    Body: {
        "status": "on_duty",
        "emergency_level": 1,
        "incident_id": 123
    }
    """
    try:
        current_user_id = get_jwt_identity()
        user = find_user_by_id(current_user_id)
        
        vehicle = find_vehicle_by_id(vehicle_id)
        
        if not vehicle:
            return jsonify({'error': 'Vehicle not found'}), 404
        
        # Check permission
        if not (user.is_admin() or user.role == UserRole.CONTROL_ROOM or 
                vehicle.assigned_driver_id == current_user_id):
            return jsonify({'error': 'Permission denied'}), 403
        
        data = request.get_json()
        status_str = data.get('status')
        emergency_level = data.get('emergency_level')
        incident_id = data.get('incident_id')
        
        if not status_str:
            return jsonify({'error': 'Status is required'}), 400
        
        try:
            new_status = VehicleStatus(status_str)
        except ValueError:
            return jsonify({'error': f'Invalid status: {status_str}'}), 400
        
        # Update based on new status
        if new_status == VehicleStatus.AVAILABLE:
            vehicle.set_available()
        elif new_status == VehicleStatus.ON_DUTY:
            vehicle.set_on_duty(incident_id, emergency_level)
        elif new_status == VehicleStatus.EN_ROUTE:
            destination = data.get('destination')
            dest_lat = data.get('destination_latitude')
            dest_lng = data.get('destination_longitude')
            if destination and dest_lat and dest_lng:
                vehicle.set_en_route(destination, dest_lat, dest_lng)
            else:
                vehicle.status = new_status
        elif new_status == VehicleStatus.AT_SCENE:
            vehicle.set_at_scene()
        elif new_status == VehicleStatus.RETURNING:
            vehicle.set_returning()
        elif new_status == VehicleStatus.OFF_DUTY:
            vehicle.set_off_duty()
        else:
            vehicle.status = new_status
        
        db.session.commit()
        
        # Emit real-time update
        emit_vehicle_update(vehicle)
        
        return jsonify({
            'success': True,
            'message': f'Vehicle status updated to {status_str}',
            'vehicle': vehicle.to_dict()
        }), 200
        
    except Exception as e:
        logger.error(f"Update vehicle status error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to update status'}), 500


@vehicle_bp.route('/<int:vehicle_id}/siren', methods=['PUT'])
@jwt_required()
def toggle_siren(vehicle_id):
    """
    Toggle vehicle siren
    PUT /api/v1/vehicles/<vehicle_id>/siren
    Body: {"active": true}
    """
    try:
        current_user_id = get_jwt_identity()
        user = find_user_by_id(current_user_id)
        
        vehicle = find_vehicle_by_id(vehicle_id)
        
        if not vehicle:
            return jsonify({'error': 'Vehicle not found'}), 404
        
        if not (user.is_admin() or user.role == UserRole.CONTROL_ROOM or 
                vehicle.assigned_driver_id == current_user_id):
            return jsonify({'error': 'Permission denied'}), 403
        
        data = request.get_json()
        active = data.get('active', False)
        
        vehicle.is_siren_active = active
        vehicle.is_lights_active = active  # Usually both together
        db.session.commit()
        
        # Emit real-time update
        emit_vehicle_update(vehicle)
        
        return jsonify({
            'success': True,
            'message': f'Siren {"activated" if active else "deactivated"}',
            'is_siren_active': vehicle.is_siren_active
        }), 200
        
    except Exception as e:
        logger.error(f"Toggle siren error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to toggle siren'}), 500


# ============================================
# VEHICLE MANAGEMENT (Admin only)
# ============================================

@vehicle_bp.route('/register', methods=['POST'])
@jwt_required()
@role_required('admin', 'super_admin')
def register_vehicle():
    """
    Register new emergency vehicle (Admin only)
    POST /api/v1/vehicles/register
    Body: {
        "registration_number": "DL-01-AB-1234",
        "vehicle_type": "ambulance",
        "make": "Mercedes",
        "model": "Sprinter",
        "year": 2024,
        "department": "City Ambulance Service",
        "driver_name": "Rajesh Kumar",
        "capacity_patients": 2
    }
    """
    try:
        data = request.get_json()
        
        required_fields = ['registration_number', 'vehicle_type', 'make', 'model', 'year', 'department']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Check if registration number already exists
        existing = find_vehicle_by_registration(data['registration_number'])
        if existing:
            return jsonify({'error': 'Vehicle with this registration number already exists'}), 409
        
        # Validate vehicle type
        try:
            vehicle_type = VehicleType(data['vehicle_type'])
        except ValueError:
            return jsonify({'error': f'Invalid vehicle type: {data["vehicle_type"]}'}), 400
        
        # Create vehicle
        vehicle = EmergencyVehicle(
            registration_number=data['registration_number'].upper(),
            vehicle_type=vehicle_type,
            make=data['make'],
            model=data['model'],
            year=data['year'],
            department=data['department'],
            driver_name=data.get('driver_name'),
            driver_contact=data.get('driver_contact'),
            capacity_patients=data.get('capacity_patients', 1),
            station_location=data.get('station_location'),
            station_latitude=data.get('station_latitude'),
            station_longitude=data.get('station_longitude'),
            has_life_support=data.get('has_life_support', False),
            has_oxygen=data.get('has_oxygen', True),
            has_defibrillator=data.get('has_defibrillator', False)
        )
        
        db.session.add(vehicle)
        db.session.commit()
        
        logger.info(f"New vehicle registered: {vehicle.registration_number} ({vehicle.vehicle_type.value})")
        
        return jsonify({
            'success': True,
            'message': 'Vehicle registered successfully',
            'vehicle': vehicle.to_dict()
        }), 201
        
    except Exception as e:
        logger.error(f"Register vehicle error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to register vehicle'}), 500


@vehicle_bp.route('/<int:vehicle_id>', methods=['PUT'])
@jwt_required()
@role_required('admin', 'super_admin')
def update_vehicle(vehicle_id):
    """
    Update vehicle details (Admin only)
    PUT /api/v1/vehicles/<vehicle_id>
    """
    try:
        vehicle = find_vehicle_by_id(vehicle_id)
        
        if not vehicle:
            return jsonify({'error': 'Vehicle not found'}), 404
        
        data = request.get_json()
        
        # Update allowed fields
        allowed_fields = [
            'make', 'model', 'year', 'color', 'department', 
            'driver_name', 'driver_contact', 'capacity_patients',
            'has_life_support', 'has_oxygen', 'has_defibrillator',
            'station_location', 'station_latitude', 'station_longitude'
        ]
        
        for field in allowed_fields:
            if field in data:
                setattr(vehicle, field, data[field])
        
        # Update vehicle type if provided
        if 'vehicle_type' in data:
            try:
                vehicle.vehicle_type = VehicleType(data['vehicle_type'])
            except ValueError:
                return jsonify({'error': f'Invalid vehicle type: {data["vehicle_type"]}'}), 400
        
        db.session.commit()
        
        logger.info(f"Vehicle updated: {vehicle.registration_number}")
        
        return jsonify({
            'success': True,
            'message': 'Vehicle updated successfully',
            'vehicle': vehicle.to_dict()
        }), 200
        
    except Exception as e:
        logger.error(f"Update vehicle error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to update vehicle'}), 500


@vehicle_bp.route('/<int:vehicle_id>', methods=['DELETE'])
@jwt_required()
@role_required('admin', 'super_admin')
def delete_vehicle(vehicle_id):
    """
    Delete/Deactivate vehicle (Admin only)
    DELETE /api/v1/vehicles/<vehicle_id>
    """
    try:
        vehicle = find_vehicle_by_id(vehicle_id)
        
        if not vehicle:
            return jsonify({'error': 'Vehicle not found'}), 404
        
        # Soft delete - mark as inactive
        vehicle.is_active = False
        vehicle.status = VehicleStatus.OUT_OF_SERVICE
        db.session.commit()
        
        logger.info(f"Vehicle deactivated: {vehicle.registration_number}")
        
        return jsonify({
            'success': True,
            'message': f'Vehicle {vehicle.registration_number} has been deactivated'
        }), 200
        
    except Exception as e:
        logger.error(f"Delete vehicle error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to delete vehicle'}), 500


@vehicle_bp.route('/<int:vehicle_id>/assign-driver/<int:driver_id>', methods=['PUT'])
@jwt_required()
@role_required('admin', 'super_admin')
def assign_driver(vehicle_id, driver_id):
    """
    Assign a driver to vehicle (Admin only)
    PUT /api/v1/vehicles/<vehicle_id>/assign-driver/<driver_id>
    """
    try:
        vehicle = find_vehicle_by_id(vehicle_id)
        driver = find_user_by_id(driver_id)
        
        if not vehicle:
            return jsonify({'error': 'Vehicle not found'}), 404
        
        if not driver:
            return jsonify({'error': 'Driver not found'}), 404
        
        # Check if driver is emergency driver
        if driver.role != UserRole.EMERGENCY_DRIVER:
            return jsonify({'error': 'User is not an emergency driver'}), 400
        
        vehicle.assigned_driver_id = driver_id
        vehicle.driver_name = driver.full_name
        vehicle.driver_contact = driver.phone_number
        
        driver.assigned_vehicle_id = vehicle_id
        
        db.session.commit()
        
        logger.info(f"Driver {driver.email} assigned to vehicle {vehicle.registration_number}")
        
        return jsonify({
            'success': True,
            'message': f'Driver {driver.full_name} assigned to {vehicle.registration_number}',
            'vehicle': vehicle.to_dict()
        }), 200
        
    except Exception as e:
        logger.error(f"Assign driver error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to assign driver'}), 500


# ============================================
# VEHICLE STATISTICS
# ============================================

@vehicle_bp.route('/statistics', methods=['GET'])
@jwt_required()
@role_required('admin', 'control_room')
def get_vehicle_statistics():
    """
    Get vehicle statistics and analytics
    GET /api/v1/vehicles/statistics
    """
    try:
        vehicles = get_all_emergency_vehicles()
        
        stats = {
            'total_vehicles': len(vehicles),
            'by_type': {},
            'by_status': {},
            'active_corridors': 0,
            'avg_response_time': 0,
            'total_emergencies_today': 0,
            'available_count': 0,
            'on_duty_count': 0
        }
        
        total_response_time = 0
        vehicles_with_response = 0
        
        for vehicle in vehicles:
            # Count by type
            type_name = vehicle.vehicle_type.value if vehicle.vehicle_type else 'unknown'
            stats['by_type'][type_name] = stats['by_type'].get(type_name, 0) + 1
            
            # Count by status
            status_name = vehicle.status.value if vehicle.status else 'unknown'
            stats['by_status'][status_name] = stats['by_status'].get(status_name, 0) + 1
            
            # Count available vehicles
            if vehicle.status == VehicleStatus.AVAILABLE:
                stats['available_count'] += 1
            
            # Count on duty
            if vehicle.status == VehicleStatus.ON_DUTY:
                stats['on_duty_count'] += 1
            
            # Active corridors
            if vehicle.active_corridor_id:
                stats['active_corridors'] += 1
            
            # Response time
            if vehicle.average_response_time > 0:
                total_response_time += vehicle.average_response_time
                vehicles_with_response += 1
        
        # Calculate averages
        if vehicles_with_response > 0:
            stats['avg_response_time'] = round(total_response_time / vehicles_with_response, 2)
        
        return jsonify({
            'success': True,
            'statistics': stats,
            'timestamp': datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Get vehicle statistics error: {str(e)}")
        return jsonify({'error': 'Failed to fetch statistics'}), 500


# ============================================
# WEBSOCKET EVENT HANDLERS (defined in socket_events)
# ============================================

# These will be implemented in socket_events/live_tracking.py
# For real-time vehicle tracking via WebSocket

__all__ = ['vehicle_bp']