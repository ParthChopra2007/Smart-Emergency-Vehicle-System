"""
Smart Emergency Vehicle Priority System - Corridor Routes
Handles green corridor requests, approvals, tracking, and management
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, timedelta
from loguru import logger
from geopy.distance import geodesic

from app.extensions import db, cache, limiter, socketio
from app.models.user import User, UserRole, find_user_by_id
from app.models.vehicle import (
    EmergencyVehicle, VehicleStatus, VehicleEmergencyLevel,
    find_vehicle_by_id, get_available_vehicles, get_nearest_vehicle
)
from app.models.incident import Incident, find_incident_by_id
from app.models.traffic_signal import TrafficSignal, get_signals_on_route, find_signal_by_id
from app.models.corridor import (
    GreenCorridor, CorridorStatus, CorridorType, PathCalculationMethod,
    find_corridor_by_id, find_corridor_by_vehicle, find_corridor_by_incident,
    get_active_corridors, get_corridor_history, get_corridor_statistics,
    create_sample_corridor
)
from app.models.audit_log import create_audit_log, AuditAction, AuditSeverity
from app.routes.auth_routes import role_required

# Create Blueprint
corridor_bp = Blueprint('corridor', __name__)

# ============================================
# HELPER FUNCTIONS
# ============================================

def get_client_ip():
    """Get client IP address from request"""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0]
    return request.remote_addr

def emit_corridor_update(corridor, event_type='corridor_update'):
    """Emit real-time corridor update via WebSocket"""
    socketio.emit(event_type, {
        'corridor_id': corridor.id,
        'corridor_uuid': corridor.corridor_uuid,
        'status': corridor.status.value if corridor.status else None,
        'vehicle_id': corridor.vehicle_id,
        'progress_percentage': corridor.progress_percentage,
        'remaining_distance_km': corridor.remaining_distance_km,
        'remaining_time_seconds': corridor.remaining_time_seconds,
        'next_signal_id': corridor.next_signal_id,
        'timestamp': datetime.utcnow().isoformat()
    }, broadcast=True)
    
    logger.debug(f"Real-time update emitted for corridor {corridor.id}")

def calculate_route_points(start_lat, start_lng, dest_lat, dest_lng):
    """Calculate route points between start and destination"""
    # Simplified - in production use Google Maps API or OSRM
    points = [
        {'lat': start_lat, 'lng': start_lng, 'order': 0},
        {'lat': dest_lat, 'lng': dest_lng, 'order': 1}
    ]
    return points

def get_signals_on_path(signal_ids):
    """Get signal details for given signal IDs"""
    signals = []
    for signal_id in signal_ids:
        signal = find_signal_by_id(signal_id)
        if signal:
            signals.append({
                'id': signal.id,
                'intersection_name': signal.intersection_name,
                'latitude': signal.latitude,
                'longitude': signal.longitude,
                'distance_from_start': 0  # Would calculate in production
            })
    return signals

# ============================================
# CORRIDOR REQUEST ROUTES
# ============================================

@corridor_bp.route('/request', methods=['POST'])
@jwt_required()
@limiter.limit("10 per minute")
def request_corridor():
    """
    Request a new green corridor
    POST /api/v1/corridor/request
    Body: {
        "vehicle_id": 1,
        "incident_id": 123,
        "destination_latitude": 28.5675,
        "destination_longitude": 77.2100,
        "destination_address": "AIIMS Hospital",
        "destination_type": "hospital",
        "priority_level": 1
    }
    """
    try:
        current_user_id = get_jwt_identity()
        user = find_user_by_id(current_user_id)
        
        data = request.get_json()
        
        # Validate required fields
        if not data.get('vehicle_id'):
            return jsonify({'error': 'vehicle_id is required'}), 400
        
        if not data.get('destination_latitude') or not data.get('destination_longitude'):
            return jsonify({'error': 'Destination coordinates are required'}), 400
        
        # Get vehicle details
        vehicle = find_vehicle_by_id(data['vehicle_id'])
        if not vehicle:
            return jsonify({'error': 'Vehicle not found'}), 404
        
        # Check if vehicle already has active corridor
        existing_corridor = find_corridor_by_vehicle(vehicle.id)
        if existing_corridor:
            return jsonify({
                'error': 'Vehicle already has an active corridor',
                'corridor_id': existing_corridor.id,
                'status': existing_corridor.status.value
            }), 409
        
        # Check if user has permission
        if not (user.is_admin() or user.role == UserRole.CONTROL_ROOM or 
                vehicle.assigned_driver_id == current_user_id):
            return jsonify({'error': 'Permission denied'}), 403
        
        # Get vehicle current location
        start_lat = vehicle.current_latitude or data.get('start_latitude')
        start_lng = vehicle.current_longitude or data.get('start_longitude')
        
        if not start_lat or not start_lng:
            return jsonify({'error': 'Vehicle location not available. Please update vehicle location first.'}), 400
        
        dest_lat = data['destination_latitude']
        dest_lng = data['destination_longitude']
        
        # Calculate distance
        distance = geodesic((start_lat, start_lng), (dest_lat, dest_lng)).kilometers
        
        # Create corridor
        corridor = GreenCorridor(
            vehicle_id=vehicle.id,
            start_lat=start_lat,
            start_lng=start_lng,
            dest_lat=dest_lat,
            dest_lng=dest_lng,
            requested_by_id=current_user_id,
            destination_address=data.get('destination_address'),
            destination_type=data.get('destination_type', 'incident'),
            incident_id=data.get('incident_id'),
            priority_level=data.get('priority_level', vehicle.emergency_level.value if vehicle.emergency_level else 3),
            corridor_type=CorridorType.EMERGENCY,
            calculation_method=PathCalculationMethod.AI_OPTIMIZED
        )
        
        # Calculate route
        corridor.path_points = calculate_route_points(start_lat, start_lng, dest_lat, dest_lng)
        corridor.path_distance_km = round(distance, 2)
        corridor.estimated_duration_seconds = int((distance / 40) * 3600)  # 40 km/h avg speed
        
        db.session.add(corridor)
        db.session.commit()
        
        # Auto-approve for high priority (level 1) or if user is admin/control room
        auto_approve = (corridor.priority_level == 1) or user.is_admin() or user.role == UserRole.CONTROL_ROOM
        
        if auto_approve:
            corridor.approve(current_user_id)
            corridor.activate()
            db.session.commit()
            status_message = "Corridor approved and activated automatically"
        else:
            status_message = "Corridor request submitted for approval"
        
        # Log to audit
        create_audit_log(
            action=AuditAction.CORRIDOR_REQUEST,
            user_id=current_user_id,
            user_email=user.email,
            entity_type='corridor',
            entity_id=corridor.id,
            action_details={
                'vehicle_id': vehicle.id,
                'vehicle_registration': vehicle.registration_number,
                'distance_km': distance,
                'auto_approved': auto_approve
            },
            ip_address=get_client_ip()
        )
        
        # Emit real-time update
        emit_corridor_update(corridor, 'corridor_requested')
        
        logger.info(f"Corridor requested for vehicle {vehicle.registration_number} by {user.email}")
        
        return jsonify({
            'success': True,
            'message': status_message,
            'data': {
                'corridor': corridor.to_dict(),
                'auto_approved': auto_approve
            }
        }), 201
        
    except Exception as e:
        logger.error(f"Request corridor error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to request corridor'}), 500


@corridor_bp.route('/<int:corridor_id>/approve', methods=['PUT'])
@jwt_required()
@role_required('admin', 'control_room')
def approve_corridor(corridor_id):
    """
    Approve a pending corridor request
    PUT /api/v1/corridor/<corridor_id>/approve
    """
    try:
        current_user_id = get_jwt_identity()
        user = find_user_by_id(current_user_id)
        
        corridor = find_corridor_by_id(corridor_id)
        
        if not corridor:
            return jsonify({'error': 'Corridor not found'}), 404
        
        if corridor.status != CorridorStatus.REQUESTED:
            return jsonify({
                'error': f'Cannot approve corridor in {corridor.status.value} status'
            }), 400
        
        # Approve corridor
        corridor.approve(current_user_id)
        
        # Log to audit
        create_audit_log(
            action=AuditAction.CORRIDOR_APPROVE,
            user_id=current_user_id,
            user_email=user.email,
            entity_type='corridor',
            entity_id=corridor.id,
            action_details={'vehicle_id': corridor.vehicle_id},
            ip_address=get_client_ip()
        )
        
        # Emit real-time update
        emit_corridor_update(corridor, 'corridor_approved')
        
        logger.info(f"Corridor {corridor_id} approved by {user.email}")
        
        return jsonify({
            'success': True,
            'message': 'Corridor approved successfully',
            'data': {'corridor': corridor.to_dict()}
        }), 200
        
    except Exception as e:
        logger.error(f"Approve corridor error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to approve corridor'}), 500


@corridor_bp.route('/<int:corridor_id>/activate', methods=['PUT'])
@jwt_required()
def activate_corridor(corridor_id):
    """
    Activate a green corridor (start turning signals green)
    PUT /api/v1/corridor/<corridor_id>/activate
    """
    try:
        current_user_id = get_jwt_identity()
        user = find_user_by_id(current_user_id)
        
        corridor = find_corridor_by_id(corridor_id)
        
        if not corridor:
            return jsonify({'error': 'Corridor not found'}), 404
        
        # Check permission
        vehicle = find_vehicle_by_id(corridor.vehicle_id)
        if not (user.is_admin() or user.role == UserRole.CONTROL_ROOM or 
                (vehicle and vehicle.assigned_driver_id == current_user_id)):
            return jsonify({'error': 'Permission denied'}), 403
        
        if corridor.status not in [CorridorStatus.APPROVED, CorridorStatus.REQUESTED]:
            return jsonify({
                'error': f'Cannot activate corridor in {corridor.status.value} status'
            }), 400
        
        # Activate corridor
        corridor.activate()
        
        # Log to audit
        create_audit_log(
            action=AuditAction.CORRIDOR_ACTIVATE,
            user_id=current_user_id,
            user_email=user.email,
            entity_type='corridor',
            entity_id=corridor.id,
            action_details={'vehicle_id': corridor.vehicle_id},
            ip_address=get_client_ip()
        )
        
        # Emit real-time update
        emit_corridor_update(corridor, 'corridor_activated')
        
        logger.info(f"Corridor {corridor_id} activated by {user.email}")
        
        return jsonify({
            'success': True,
            'message': 'Corridor activated successfully',
            'data': {'corridor': corridor.to_dict()}
        }), 200
        
    except Exception as e:
        logger.error(f"Activate corridor error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to activate corridor'}), 500


@corridor_bp.route('/<int:corridor_id>/start', methods=['PUT'])
@jwt_required()
def start_corridor_journey(corridor_id):
    """
    Mark that vehicle has started the corridor journey
    PUT /api/v1/corridor/<corridor_id>/start
    """
    try:
        current_user_id = get_jwt_identity()
        user = find_user_by_id(current_user_id)
        
        corridor = find_corridor_by_id(corridor_id)
        
        if not corridor:
            return jsonify({'error': 'Corridor not found'}), 404
        
        # Check permission
        vehicle = find_vehicle_by_id(corridor.vehicle_id)
        if not (user.is_admin() or user.role == UserRole.CONTROL_ROOM or 
                (vehicle and vehicle.assigned_driver_id == current_user_id)):
            return jsonify({'error': 'Permission denied'}), 403
        
        if corridor.status not in [CorridorStatus.ACTIVE, CorridorStatus.APPROVED]:
            return jsonify({
                'error': f'Cannot start journey from {corridor.status.value} status'
            }), 400
        
        # Start journey
        corridor.start_journey()
        
        # Update vehicle status
        if vehicle:
            vehicle.status = VehicleStatus.EN_ROUTE
            db.session.commit()
        
        # Emit real-time update
        emit_corridor_update(corridor, 'corridor_started')
        
        logger.info(f"Journey started on corridor {corridor_id}")
        
        return jsonify({
            'success': True,
            'message': 'Journey started',
            'data': {'corridor': corridor.to_dict()}
        }), 200
        
    except Exception as e:
        logger.error(f"Start corridor journey error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to start journey'}), 500


@corridor_bp.route('/<int:corridor_id>/update-progress', methods=['POST'])
@jwt_required()
@limiter.limit("30 per minute")
def update_progress(corridor_id):
    """
    Update vehicle progress along the corridor (real-time tracking)
    POST /api/v1/corridor/<corridor_id>/update-progress
    Body: {
        "latitude": 28.6200,
        "longitude": 77.2200
    }
    """
    try:
        current_user_id = get_jwt_identity()
        user = find_user_by_id(current_user_id)
        
        corridor = find_corridor_by_id(corridor_id)
        
        if not corridor:
            return jsonify({'error': 'Corridor not found'}), 404
        
        # Check permission
        vehicle = find_vehicle_by_id(corridor.vehicle_id)
        if not (user.is_admin() or user.role == UserRole.CONTROL_ROOM or 
                (vehicle and vehicle.assigned_driver_id == current_user_id)):
            return jsonify({'error': 'Permission denied'}), 403
        
        data = request.get_json()
        latitude = data.get('latitude')
        longitude = data.get('longitude')
        
        if not latitude or not longitude:
            return jsonify({'error': 'Latitude and longitude required'}), 400
        
        # Update progress
        progress = corridor.update_progress(latitude, longitude)
        
        # Update vehicle location
        if vehicle:
            vehicle.update_location(latitude, longitude, data.get('speed'), data.get('heading'))
        
        # Emit real-time update
        emit_corridor_update(corridor, 'corridor_progress')
        
        return jsonify({
            'success': True,
            'data': progress
        }), 200
        
    except Exception as e:
        logger.error(f"Update progress error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to update progress'}), 500


@corridor_bp.route('/<int:corridor_id>/signal-passed', methods=['POST'])
@jwt_required()
def signal_passed(corridor_id):
    """
    Mark that vehicle has passed a traffic signal
    POST /api/v1/corridor/<corridor_id>/signal-passed
    Body: {"signal_id": 5}
    """
    try:
        current_user_id = get_jwt_identity()
        
        corridor = find_corridor_by_id(corridor_id)
        
        if not corridor:
            return jsonify({'error': 'Corridor not found'}), 404
        
        data = request.get_json()
        signal_id = data.get('signal_id')
        
        if not signal_id:
            return jsonify({'error': 'signal_id required'}), 400
        
        corridor.mark_signal_passed(signal_id)
        
        # Emit real-time update
        emit_corridor_update(corridor, 'signal_passed')
        
        return jsonify({
            'success': True,
            'message': f'Signal {signal_id} marked as passed',
            'data': {
                'signals_passed': corridor.signals_passed,
                'signals_total': corridor.signals_total,
                'progress_percentage': corridor.progress_percentage
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Signal passed error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to mark signal'}), 500


@corridor_bp.route('/<int:corridor_id>/complete', methods=['PUT'])
@jwt_required()
def complete_corridor(corridor_id):
    """
    Mark corridor as completed (vehicle reached destination)
    PUT /api/v1/corridor/<corridor_id>/complete
    """
    try:
        current_user_id = get_jwt_identity()
        user = find_user_by_id(current_user_id)
        
        corridor = find_corridor_by_id(corridor_id)
        
        if not corridor:
            return jsonify({'error': 'Corridor not found'}), 404
        
        # Check permission
        vehicle = find_vehicle_by_id(corridor.vehicle_id)
        if not (user.is_admin() or user.role == UserRole.CONTROL_ROOM or 
                (vehicle and vehicle.assigned_driver_id == current_user_id)):
            return jsonify({'error': 'Permission denied'}), 403
        
        # Complete corridor
        corridor.complete()
        
        # Update incident if associated
        if corridor.incident_id:
            incident = find_incident_by_id(corridor.incident_id)
            if incident:
                incident.mark_resolved()
        
        # Log to audit
        create_audit_log(
            action=AuditAction.CORRIDOR_COMPLETE,
            user_id=current_user_id,
            user_email=user.email,
            entity_type='corridor',
            entity_id=corridor.id,
            action_details={
                'time_saved_seconds': corridor.time_saved_seconds,
                'actual_duration_seconds': corridor.actual_duration_seconds
            },
            ip_address=get_client_ip()
        )
        
        # Emit real-time update
        emit_corridor_update(corridor, 'corridor_completed')
        
        logger.info(f"Corridor {corridor_id} completed. Time saved: {corridor.time_saved_seconds}s")
        
        return jsonify({
            'success': True,
            'message': 'Corridor completed successfully',
            'data': {
                'corridor': corridor.to_dict(),
                'time_saved_seconds': corridor.time_saved_seconds,
                'actual_duration_seconds': corridor.actual_duration_seconds
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Complete corridor error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to complete corridor'}), 500


@corridor_bp.route('/<int:corridor_id>/cancel', methods=['PUT'])
@jwt_required()
def cancel_corridor(corridor_id):
    """
    Cancel an active corridor
    PUT /api/v1/corridor/<corridor_id>/cancel
    Body: {"reason": "False alarm"}
    """
    try:
        current_user_id = get_jwt_identity()
        user = find_user_by_id(current_user_id)
        
        corridor = find_corridor_by_id(corridor_id)
        
        if not corridor:
            return jsonify({'error': 'Corridor not found'}), 404
        
        # Check permission
        vehicle = find_vehicle_by_id(corridor.vehicle_id)
        if not (user.is_admin() or user.role == UserRole.CONTROL_ROOM or 
                (vehicle and vehicle.assigned_driver_id == current_user_id)):
            return jsonify({'error': 'Permission denied'}), 403
        
        data = request.get_json()
        reason = data.get('reason', 'Cancelled by user')
        
        corridor.cancel(reason, current_user_id)
        
        # Log to audit
        create_audit_log(
            action=AuditAction.CORRIDOR_CANCEL,
            user_id=current_user_id,
            user_email=user.email,
            entity_type='corridor',
            entity_id=corridor.id,
            action_details={'reason': reason},
            ip_address=get_client_ip()
        )
        
        # Emit real-time update
        emit_corridor_update(corridor, 'corridor_cancelled')
        
        logger.info(f"Corridor {corridor_id} cancelled by {user.email}: {reason}")
        
        return jsonify({
            'success': True,
            'message': f'Corridor cancelled: {reason}',
            'data': {'corridor': corridor.to_dict()}
        }), 200
        
    except Exception as e:
        logger.error(f"Cancel corridor error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to cancel corridor'}), 500


# ============================================
# CORRIDOR QUERY ROUTES
# ============================================

@corridor_bp.route('/active', methods=['GET'])
@jwt_required()
def get_active_corridors_route():
    """
    Get all currently active corridors
    GET /api/v1/corridor/active
    """
    try:
        corridors = get_active_corridors()
        
        return jsonify({
            'success': True,
            'count': len(corridors),
            'data': [c.to_dict() for c in corridors]
        }), 200
        
    except Exception as e:
        logger.error(f"Get active corridors error: {str(e)}")
        return jsonify({'error': 'Failed to fetch active corridors'}), 500


@corridor_bp.route('/vehicle/<int:vehicle_id>', methods=['GET'])
@jwt_required()
def get_vehicle_corridor(vehicle_id):
    """
    Get active corridor for a specific vehicle
    GET /api/v1/corridor/vehicle/<vehicle_id>
    """
    try:
        corridor = find_corridor_by_vehicle(vehicle_id)
        
        if not corridor:
            return jsonify({
                'success': True,
                'data': None,
                'message': 'No active corridor for this vehicle'
            }), 200
        
        return jsonify({
            'success': True,
            'data': corridor.to_dict()
        }), 200
        
    except Exception as e:
        logger.error(f"Get vehicle corridor error: {str(e)}")
        return jsonify({'error': 'Failed to fetch corridor'}), 500


@corridor_bp.route('/<int:corridor_id>', methods=['GET'])
@jwt_required()
def get_corridor_details(corridor_id):
    """
    Get detailed corridor information
    GET /api/v1/corridor/<corridor_id>
    """
    try:
        corridor = find_corridor_by_id(corridor_id)
        
        if not corridor:
            return jsonify({'error': 'Corridor not found'}), 404
        
        return jsonify({
            'success': True,
            'data': corridor.to_dict(include_sensitive=True)
        }), 200
        
    except Exception as e:
        logger.error(f"Get corridor details error: {str(e)}")
        return jsonify({'error': 'Failed to fetch corridor'}), 500


@corridor_bp.route('/history', methods=['GET'])
@jwt_required()
def get_corridor_history_route():
    """
    Get corridor history with filters
    GET /api/v1/corridor/history?vehicle_id=1&days=7
    """
    try:
        vehicle_id = request.args.get('vehicle_id', type=int)
        days = request.args.get('days', 7, type=int)
        
        corridors = get_corridor_history(vehicle_id=vehicle_id, days=days)
        
        return jsonify({
            'success': True,
            'count': len(corridors),
            'data': [c.to_dict() for c in corridors]
        }), 200
        
    except Exception as e:
        logger.error(f"Get corridor history error: {str(e)}")
        return jsonify({'error': 'Failed to fetch corridor history'}), 500


@corridor_bp.route('/statistics', methods=['GET'])
@jwt_required()
def get_corridor_statistics_route():
    """
    Get corridor statistics
    GET /api/v1/corridor/statistics?days=30
    """
    try:
        days = request.args.get('days', 30, type=int)
        
        stats = get_corridor_statistics(days=days)
        
        return jsonify({
            'success': True,
            'data': stats
        }), 200
        
    except Exception as e:
        logger.error(f"Get corridor statistics error: {str(e)}")
        return jsonify({'error': 'Failed to fetch statistics'}), 500


@corridor_bp.route('/check-availability', methods=['POST'])
@jwt_required()
def check_corridor_availability():
    """
    Check if a corridor is available for given route
    POST /api/v1/corridor/check-availability
    Body: {
        "start_latitude": 28.6139,
        "start_longitude": 77.2090,
        "destination_latitude": 28.5675,
        "destination_longitude": 77.2100
    }
    """
    try:
        data = request.get_json()
        
        start_lat = data.get('start_latitude')
        start_lng = data.get('start_longitude')
        dest_lat = data.get('destination_latitude')
        dest_lng = data.get('destination_longitude')
        
        if not all([start_lat, start_lng, dest_lat, dest_lng]):
            return jsonify({'error': 'Start and destination coordinates required'}), 400
        
        # Calculate distance
        distance = geodesic((start_lat, start_lng), (dest_lat, dest_lng)).kilometers
        
        # Get signals on route (simplified)
        route_coords = [(start_lat, start_lng), (dest_lat, dest_lng)]
        signals = get_signals_on_route(route_coords)
        
        # Estimate duration
        estimated_duration = int((distance / 40) * 3600)  # 40 km/h avg
        
        return jsonify({
            'success': True,
            'data': {
                'distance_km': round(distance, 2),
                'estimated_duration_seconds': estimated_duration,
                'estimated_duration_minutes': round(estimated_duration / 60, 1),
                'signals_on_route': len(signals),
                'is_available': True,
                'message': 'Corridor route is available'
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Check corridor availability error: {str(e)}")
        return jsonify({'error': 'Failed to check availability'}), 500


# ============================================
# SAMPLE CORRIDOR ROUTE (Testing)
# ============================================

@corridor_bp.route('/sample/create', methods=['POST'])
@jwt_required()
@role_required('admin')
def create_sample():
    """
    Create a sample corridor for testing
    POST /api/v1/corridor/sample/create
    """
    try:
        corridor = create_sample_corridor()
        
        if not corridor:
            return jsonify({'error': 'Failed to create sample corridor. Ensure vehicles exist.'}), 400
        
        return jsonify({
            'success': True,
            'message': 'Sample corridor created',
            'data': corridor.to_dict()
        }), 201
        
    except Exception as e:
        logger.error(f"Create sample corridor error: {str(e)}")
        return jsonify({'error': 'Failed to create sample corridor'}), 500


# ============================================
# EXPORTS
# ============================================

__all__ = ['corridor_bp']
