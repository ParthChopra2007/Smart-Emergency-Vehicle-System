"""
Smart Emergency Vehicle Priority System - Traffic Signal Routes
Handles traffic signal control, monitoring, density tracking, and manual override
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, timedelta
from loguru import logger
from geopy.distance import geodesic

from app.extensions import db, cache, limiter, socketio
from app.models.user import User, UserRole, find_user_by_id
from app.models.traffic_signal import (
    TrafficSignal, SignalStatus, SignalDirection, TrafficDensity,
    SignalLog, find_signal_by_id, find_signal_by_intersection_id,
    get_all_signals, get_signals_on_route
)
from app.models.corridor import find_corridor_by_vehicle
from app.models.vehicle import EmergencyVehicle, find_vehicle_by_id
from app.routes.auth_routes import role_required
from app.models.audit_log import create_audit_log, AuditAction

# Create Blueprint
traffic_bp = Blueprint('traffic', __name__)

# ============================================
# HELPER FUNCTIONS
# ============================================

def get_client_ip():
    """Get client IP address from request"""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0]
    return request.remote_addr


def emit_signal_update(signal, event_type='signal_update'):
    """Emit real-time signal update via WebSocket"""
    socketio.emit(event_type, {
        'signal_id': signal.id,
        'intersection_id': signal.intersection_id,
        'intersection_name': signal.intersection_name,
        'status': signal.current_status.value if signal.current_status else None,
        'current_green_direction': signal.current_green_direction.value if signal.current_green_direction else None,
        'is_corridor_active': signal.is_corridor_active(),
        'traffic_density': signal.current_density.value if signal.current_density else None,
        'timestamp': datetime.utcnow().isoformat()
    }, broadcast=True)
    
    logger.debug(f"Real-time update emitted for signal {signal.id}")


def log_signal_action(signal_id, action, user_id, user_email, success=True, **kwargs):
    """Log signal action to audit trail and signal_logs"""
    # Log to signal_logs table
    SignalLog.log_action(
        signal_id=signal_id,
        action=action,
        triggered_by=user_email or 'system',
        success=success,
        command_params=kwargs.get('command_params'),
        previous_status=kwargs.get('previous_status'),
        new_status=kwargs.get('new_status'),
        response_time_ms=kwargs.get('response_time_ms')
    )
    
    # Log to audit_log for compliance
    create_audit_log(
        action=AuditAction.SIGNAL_CONTROL,
        user_id=user_id,
        user_email=user_email,
        entity_type='traffic_signal',
        entity_id=signal_id,
        action_details={
            'action': action,
            'params': kwargs.get('command_params', {})
        },
        ip_address=get_client_ip()
    )


# ============================================
# SIGNAL QUERY ROUTES
# ============================================

@traffic_bp.route('/signals', methods=['GET'])
@jwt_required()
@cache.cached(timeout=30)
def get_signals():
    """
    Get all traffic signals with filters
    GET /api/v1/traffic/signals?zone_id=ZONE_CENTRAL&status=normal
    """
    try:
        zone_id = request.args.get('zone_id')
        status = request.args.get('status')
        
        status_enum = None
        if status:
            try:
                status_enum = SignalStatus(status)
            except ValueError:
                return jsonify({'error': f'Invalid status: {status}'}), 400
        
        signals = get_all_signals(zone_id=zone_id, status=status_enum)
        
        # Get summary statistics
        total_signals = len(signals)
        online_count = sum(1 for s in signals if s.is_online)
        corridor_active_count = sum(1 for s in signals if s.is_corridor_active())
        
        return jsonify({
            'success': True,
            'data': {
                'signals': [s.to_dict() for s in signals],
                'summary': {
                    'total': total_signals,
                    'online': online_count,
                    'offline': total_signals - online_count,
                    'green_corridor_active': corridor_active_count
                }
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Get signals error: {str(e)}")
        return jsonify({'error': 'Failed to fetch signals'}), 500


@traffic_bp.route('/signals/<int:signal_id>', methods=['GET'])
@jwt_required()
def get_signal(signal_id):
    """
    Get specific traffic signal details
    GET /api/v1/traffic/signals/<signal_id>
    """
    try:
        signal = find_signal_by_id(signal_id)
        
        if not signal:
            return jsonify({'error': 'Signal not found'}), 404
        
        # Get recent logs for this signal
        recent_logs = SignalLog.query.filter_by(
            signal_id=signal_id
        ).order_by(SignalLog.created_at.desc()).limit(20).all()
        
        return jsonify({
            'success': True,
            'data': {
                'signal': signal.to_dict(include_sensitive=True),
                'recent_logs': [log.to_dict() for log in recent_logs]
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Get signal error: {str(e)}")
        return jsonify({'error': 'Failed to fetch signal'}), 500


@traffic_bp.route('/signals/intersection/<intersection_id>', methods=['GET'])
@jwt_required()
def get_signal_by_intersection(intersection_id):
    """
    Get signal by intersection ID
    GET /api/v1/traffic/signals/intersection/<intersection_id>
    """
    try:
        signal = find_signal_by_intersection_id(intersection_id)
        
        if not signal:
            return jsonify({'error': 'Signal not found'}), 404
        
        return jsonify({
            'success': True,
            'data': signal.to_dict()
        }), 200
        
    except Exception as e:
        logger.error(f"Get signal by intersection error: {str(e)}")
        return jsonify({'error': 'Failed to fetch signal'}), 500


@traffic_bp.route('/signals/nearby', methods=['GET'])
@jwt_required()
def get_nearby_signals():
    """
    Get traffic signals near a location
    GET /api/v1/traffic/signals/nearby?lat=28.6139&lng=77.2090&radius=2
    """
    try:
        latitude = request.args.get('lat', type=float)
        longitude = request.args.get('lng', type=float)
        radius_km = request.args.get('radius', 2, type=float)
        
        if not latitude or not longitude:
            return jsonify({'error': 'Latitude and longitude are required'}), 400
        
        all_signals = get_all_signals()
        nearby_signals = []
        
        for signal in all_signals:
            distance = geodesic(
                (latitude, longitude),
                (signal.latitude, signal.longitude)
            ).kilometers
            
            if distance <= radius_km:
                nearby_signals.append({
                    'id': signal.id,
                    'intersection_name': signal.intersection_name,
                    'distance_km': round(distance, 2),
                    'status': signal.current_status.value if signal.current_status else None,
                    'location': {
                        'latitude': signal.latitude,
                        'longitude': signal.longitude
                    }
                })
        
        nearby_signals.sort(key=lambda x: x['distance_km'])
        
        return jsonify({
            'success': True,
            'count': len(nearby_signals),
            'data': nearby_signals
        }), 200
        
    except Exception as e:
        logger.error(f"Get nearby signals error: {str(e)}")
        return jsonify({'error': 'Failed to fetch nearby signals'}), 500


# ============================================
# SIGNAL CONTROL ROUTES
# ============================================

@traffic_bp.route('/signals/<int:signal_id>/control', methods=['POST'])
@jwt_required()
@role_required('admin', 'control_room', 'traffic_officer')
def manual_control_signal(signal_id):
    """
    Manually control a traffic signal
    POST /api/v1/traffic/signals/<signal_id>/control
    Body: {
        "direction": "north",
        "duration_seconds": 30
    }
    """
    try:
        current_user_id = get_jwt_identity()
        user = find_user_by_id(current_user_id)
        
        signal = find_signal_by_id(signal_id)
        
        if not signal:
            return jsonify({'error': 'Signal not found'}), 404
        
        data = request.get_json()
        direction = data.get('direction')
        duration = data.get('duration_seconds', 30)
        
        if not direction:
            return jsonify({'error': 'Direction is required'}), 400
        
        # Get previous status for logging
        previous_status = signal.current_status.value if signal.current_status else None
        
        # Apply manual control
        signal.manual_control(direction, duration)
        
        # Log action
        log_signal_action(
            signal_id=signal_id,
            action='MANUAL_CONTROL',
            user_id=current_user_id,
            user_email=user.email,
            success=True,
            command_params={'direction': direction, 'duration': duration},
            previous_status=previous_status,
            new_status=SignalStatus.MANUAL.value
        )
        
        # Emit real-time update
        emit_signal_update(signal, 'signal_manual_control')
        
        logger.info(f"Manual control applied to {signal.intersection_name}: {direction} for {duration}s")
        
        return jsonify({
            'success': True,
            'message': f"Signal controlled: {direction} direction green for {duration} seconds",
            'data': {
                'signal': signal.to_dict(),
                'control': {
                    'direction': direction,
                    'duration_seconds': duration,
                    'expires_at': (datetime.utcnow() + timedelta(seconds=duration)).isoformat()
                }
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Manual control error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to control signal'}), 500


@traffic_bp.route('/signals/<int:signal_id>/reset', methods=['POST'])
@jwt_required()
@role_required('admin', 'control_room', 'traffic_officer')
def reset_signal(signal_id):
    """
    Reset signal to normal automatic operation
    POST /api/v1/traffic/signals/<signal_id>/reset
    """
    try:
        current_user_id = get_jwt_identity()
        user = find_user_by_id(current_user_id)
        
        signal = find_signal_by_id(signal_id)
        
        if not signal:
            return jsonify({'error': 'Signal not found'}), 404
        
        previous_status = signal.current_status.value if signal.current_status else None
        
        signal.reset_to_default()
        
        log_signal_action(
            signal_id=signal_id,
            action='RESET',
            user_id=current_user_id,
            user_email=user.email,
            success=True,
            command_params={},
            previous_status=previous_status,
            new_status=SignalStatus.NORMAL.value
        )
        
        emit_signal_update(signal, 'signal_reset')
        
        logger.info(f"Signal {signal.intersection_name} reset to normal operation")
        
        return jsonify({
            'success': True,
            'message': "Signal reset to normal automatic operation",
            'data': signal.to_dict()
        }), 200
        
    except Exception as e:
        logger.error(f"Reset signal error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to reset signal'}), 500


@traffic_bp.route('/signals/<int:signal_id>/timing', methods=['PUT'])
@jwt_required()
@role_required('admin', 'control_room')
def update_signal_timing(signal_id):
    """
    Update signal timing configuration
    PUT /api/v1/traffic/signals/<signal_id>/timing
    Body: {
        "green_time_north": 35,
        "green_time_south": 35,
        "green_time_east": 25,
        "green_time_west": 25,
        "yellow_time": 5
    }
    """
    try:
        current_user_id = get_jwt_identity()
        user = find_user_by_id(current_user_id)
        
        signal = find_signal_by_id(signal_id)
        
        if not signal:
            return jsonify({'error': 'Signal not found'}), 404
        
        data = request.get_json()
        changes = {}
        
        # Update timing values
        timing_fields = ['green_time_north', 'green_time_south', 'green_time_east', 
                        'green_time_west', 'yellow_time', 'all_red_time', 'default_cycle_time']
        
        for field in timing_fields:
            if field in data:
                old_value = getattr(signal, field)
                new_value = data[field]
                if old_value != new_value:
                    changes[field] = {'old': old_value, 'new': new_value}
                    setattr(signal, field, new_value)
        
        if changes:
            db.session.commit()
            
            log_signal_action(
                signal_id=signal_id,
                action='UPDATE_TIMING',
                user_id=current_user_id,
                user_email=user.email,
                success=True,
                command_params=changes
            )
            
            logger.info(f"Timing updated for {signal.intersection_name}: {changes}")
        
        return jsonify({
            'success': True,
            'message': "Signal timing updated successfully",
            'data': {
                'signal': signal.to_dict(),
                'changes': changes
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Update timing error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to update timing'}), 500


# ============================================
# TRAFFIC DENSITY ROUTES
# ============================================

@traffic_bp.route('/density', methods=['GET'])
@jwt_required()
def get_traffic_density():
    """
    Get traffic density across all signals or specific zone
    GET /api/v1/traffic/density?zone_id=ZONE_CENTRAL
    """
    try:
        zone_id = request.args.get('zone_id')
        
        signals = get_all_signals(zone_id=zone_id)
        
        # Calculate overall density statistics
        density_counts = {
            TrafficDensity.LOW.value: 0,
            TrafficDensity.MEDIUM.value: 0,
            TrafficDensity.HIGH.value: 0,
            TrafficDensity.GRIDLOCK.value: 0
        }
        
        for signal in signals:
            if signal.current_density:
                density_counts[signal.current_density.value] += 1
        
        total = len(signals)
        
        return jsonify({
            'success': True,
            'data': {
                'signals': [{
                    'id': s.id,
                    'intersection_name': s.intersection_name,
                    'density_level': s.current_density.value if s.current_density else None,
                    'density_north': s.density_north,
                    'density_south': s.density_south,
                    'density_east': s.density_east,
                    'density_west': s.density_west,
                    'last_update': s.last_density_update.isoformat() if s.last_density_update else None
                } for s in signals],
                'summary': {
                    'total_signals': total,
                    'low_density': density_counts[TrafficDensity.LOW.value],
                    'medium_density': density_counts[TrafficDensity.MEDIUM.value],
                    'high_density': density_counts[TrafficDensity.HIGH.value],
                    'gridlock': density_counts[TrafficDensity.GRIDLOCK.value]
                }
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Get traffic density error: {str(e)}")
        return jsonify({'error': 'Failed to fetch traffic density'}), 500


@traffic_bp.route('/signals/<int:signal_id>/density', methods=['POST'])
@jwt_required()
@role_required('admin', 'control_room')
def update_traffic_density(signal_id):
    """
    Update traffic density for a signal (from sensors/cameras)
    POST /api/v1/traffic/signals/<signal_id>/density
    Body: {
        "north_count": 45,
        "south_count": 32,
        "east_count": 28,
        "west_count": 40
    }
    """
    try:
        current_user_id = get_jwt_identity()
        user = find_user_by_id(current_user_id)
        
        signal = find_signal_by_id(signal_id)
        
        if not signal:
            return jsonify({'error': 'Signal not found'}), 404
        
        data = request.get_json()
        
        north = data.get('north_count', 0)
        south = data.get('south_count', 0)
        east = data.get('east_count', 0)
        west = data.get('west_count', 0)
        
        # Update density
        new_density = signal.update_traffic_density(north, south, east, west)
        
        # Log if density changed significantly
        log_signal_action(
            signal_id=signal_id,
            action='DENSITY_UPDATE',
            user_id=current_user_id,
            user_email=user.email,
            success=True,
            command_params={
                'north': north, 'south': south, 'east': east, 'west': west,
                'new_density': new_density.value if new_density else None
            }
        )
        
        # Emit update if density is high or gridlock
        if new_density in [TrafficDensity.HIGH, TrafficDensity.GRIDLOCK]:
            emit_signal_update(signal, 'high_traffic_alert')
        
        return jsonify({
            'success': True,
            'message': "Traffic density updated",
            'data': {
                'signal_id': signal.id,
                'intersection_name': signal.intersection_name,
                'density_level': new_density.value if new_density else None,
                'readings': {
                    'north': north,
                    'south': south,
                    'east': east,
                    'west': west
                }
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Update density error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to update density'}), 500


# ============================================
# EMERGENCY VEHICLE DETECTION ROUTES
# ============================================

@traffic_bp.route('/signals/<int:signal_id>/detect-emergency', methods=['POST'])
@jwt_required()
@role_required('admin', 'control_room')
def detect_emergency_vehicle(signal_id):
    """
    Report emergency vehicle detection at signal (from camera/radar)
    POST /api/v1/traffic/signals/<signal_id>/detect-emergency
    Body: {
        "vehicle_type": "ambulance",
        "direction": "north",
        "vehicle_id": 1
    }
    """
    try:
        current_user_id = get_jwt_identity()
        user = find_user_by_id(current_user_id)
        
        signal = find_signal_by_id(signal_id)
        
        if not signal:
            return jsonify({'error': 'Signal not found'}), 404
        
        data = request.get_json()
        vehicle_type = data.get('vehicle_type')
        direction = data.get('direction')
        vehicle_id = data.get('vehicle_id')
        
        if not vehicle_type or not direction:
            return jsonify({'error': 'Vehicle type and direction are required'}), 400
        
        # Detect emergency vehicle
        green_direction = signal.detect_emergency_vehicle(vehicle_type, direction)
        
        # If there's an active corridor for this vehicle, activate green corridor
        if vehicle_id:
            corridor = find_corridor_by_vehicle(vehicle_id)
            if corridor and corridor.is_active_corridor():
                signal.set_green_corridor(corridor.id, vehicle_id, 60)
        
        log_signal_action(
            signal_id=signal_id,
            action='EMERGENCY_DETECTED',
            user_id=current_user_id,
            user_email=user.email,
            success=True,
            command_params={
                'vehicle_type': vehicle_type,
                'direction': direction,
                'vehicle_id': vehicle_id,
                'green_direction': green_direction.value if green_direction else None
            }
        )
        
        emit_signal_update(signal, 'emergency_vehicle_detected')
        
        logger.info(f"Emergency {vehicle_type} detected at {signal.intersection_name} from {direction}")
        
        return jsonify({
            'success': True,
            'message': f"Emergency vehicle detected. Signal turning green for {direction} direction.",
            'data': {
                'signal_id': signal.id,
                'green_direction': green_direction.value if green_direction else None,
                'is_corridor_active': signal.is_corridor_active()
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Detect emergency error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to process detection'}), 500


# ============================================
# GREEN CORRIDOR INTEGRATION ROUTES
# ============================================

@traffic_bp.route('/signals/<int:signal_id>/corridor/activate', methods=['POST'])
@jwt_required()
@role_required('admin', 'control_room')
def activate_signal_corridor(signal_id):
    """
    Activate green corridor mode on a specific signal
    POST /api/v1/traffic/signals/<signal_id>/corridor/activate
    Body: {
        "corridor_id": 5,
        "vehicle_id": 3,
        "duration_seconds": 60
    }
    """
    try:
        current_user_id = get_jwt_identity()
        user = find_user_by_id(current_user_id)
        
        signal = find_signal_by_id(signal_id)
        
        if not signal:
            return jsonify({'error': 'Signal not found'}), 404
        
        data = request.get_json()
        corridor_id = data.get('corridor_id')
        vehicle_id = data.get('vehicle_id')
        duration = data.get('duration_seconds', 30)
        
        if not corridor_id or not vehicle_id:
            return jsonify({'error': 'Corridor ID and vehicle ID are required'}), 400
        
        previous_status = signal.current_status.value if signal.current_status else None
        
        # Activate green corridor
        signal.set_green_corridor(corridor_id, vehicle_id, duration)
        
        log_signal_action(
            signal_id=signal_id,
            action='GREEN_CORRIDOR_ACTIVATE',
            user_id=current_user_id,
            user_email=user.email,
            success=True,
            command_params={
                'corridor_id': corridor_id,
                'vehicle_id': vehicle_id,
                'duration': duration
            },
            previous_status=previous_status,
            new_status=SignalStatus.GREEN_CORRIDOR.value
        )
        
        emit_signal_update(signal, 'green_corridor_activated')
        
        logger.info(f"Green corridor {corridor_id} activated on {signal.intersection_name}")
        
        return jsonify({
            'success': True,
            'message': f"Green corridor activated on {signal.intersection_name}",
            'data': {
                'signal': signal.to_dict(),
                'corridor_active_until': signal.corridor_active_until.isoformat() if signal.corridor_active_until else None
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Activate corridor error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to activate corridor'}), 500


@traffic_bp.route('/signals/<int:signal_id>/corridor/deactivate', methods=['POST'])
@jwt_required()
def deactivate_signal_corridor(signal_id):
    """
    Deactivate green corridor mode on a specific signal
    POST /api/v1/traffic/signals/<signal_id>/corridor/deactivate
    """
    try:
        current_user_id = get_jwt_identity()
        user = find_user_by_id(current_user_id)
        
        signal = find_signal_by_id(signal_id)
        
        if not signal:
            return jsonify({'error': 'Signal not found'}), 404
        
        previous_status = signal.current_status.value if signal.current_status else None
        
        signal.deactivate_green_corridor()
        
        log_signal_action(
            signal_id=signal_id,
            action='GREEN_CORRIDOR_DEACTIVATE',
            user_id=current_user_id,
            user_email=user.email,
            success=True,
            previous_status=previous_status,
            new_status=SignalStatus.NORMAL.value
        )
        
        emit_signal_update(signal, 'green_corridor_deactivated')
        
        return jsonify({
            'success': True,
            'message': f"Green corridor deactivated on {signal.intersection_name}",
            'data': signal.to_dict()
        }), 200
        
    except Exception as e:
        logger.error(f"Deactivate corridor error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to deactivate corridor'}), 500


# ============================================
# SIGNAL MONITORING & MAINTENANCE ROUTES
# ============================================

@traffic_bp.route('/signals/<int:signal_id>/heartbeat', methods=['POST'])
def signal_heartbeat(signal_id):
    """
    Receive heartbeat from physical signal controller
    POST /api/v1/traffic/signals/<signal_id>/heartbeat
    (No authentication required - from IoT devices)
    """
    try:
        signal = find_signal_by_id(signal_id)
        
        if not signal:
            return jsonify({'error': 'Signal not found'}), 404
        
        signal.update_heartbeat()
        
        return jsonify({
            'success': True,
            'message': 'Heartbeat received',
            'timestamp': datetime.utcnow().isoformat()
        }), 200
        
    except Exception as e:
        logger.error(f"Heartbeat error: {str(e)}")
        return jsonify({'error': 'Failed to process heartbeat'}), 500


@traffic_bp.route('/signals/<int:signal_id>/error', methods=['POST'])
def report_signal_error(signal_id):
    """
    Report error from physical signal controller
    POST /api/v1/traffic/signals/<signal_id>/error
    Body: {"error_code": 500, "error_message": "Communication timeout"}
    (No authentication required - from IoT devices)
    """
    try:
        signal = find_signal_by_id(signal_id)
        
        if not signal:
            return jsonify({'error': 'Signal not found'}), 404
        
        data = request.get_json()
        error_code = data.get('error_code', 0)
        error_message = data.get('error_message', 'Unknown error')
        
        signal.report_error(error_code, error_message)
        
        # Emit alert for control room
        socketio.emit('signal_error_alert', {
            'signal_id': signal_id,
            'intersection_name': signal.intersection_name,
            'error_code': error_code,
            'error_message': error_message,
            'timestamp': datetime.utcnow().isoformat()
        }, broadcast=True)
        
        logger.warning(f"Signal {signal.intersection_name} reported error: {error_code} - {error_message}")
        
        return jsonify({
            'success': True,
            'message': 'Error reported'
        }), 200
        
    except Exception as e:
        logger.error(f"Report error error: {str(e)}")
        return jsonify({'error': 'Failed to report error'}), 500


@traffic_bp.route('/signals/<int:signal_id>/maintenance', methods=['POST'])
@jwt_required()
@role_required('admin')
def schedule_signal_maintenance(signal_id):
    """
    Schedule maintenance for a signal
    POST /api/v1/traffic/signals/<signal_id>/maintenance
    Body: {"days_from_now": 30, "notes": "Routine checkup"}
    """
    try:
        current_user_id = get_jwt_identity()
        user = find_user_by_id(current_user_id)
        
        signal = find_signal_by_id(signal_id)
        
        if not signal:
            return jsonify({'error': 'Signal not found'}), 404
        
        data = request.get_json()
        days_from_now = data.get('days_from_now', 30)
        notes = data.get('notes')
        
        signal.schedule_maintenance(days_from_now)
        if notes:
            signal.maintenance_notes = notes
        
        signal.current_status = SignalStatus.MAINTENANCE
        db.session.commit()
        
        log_signal_action(
            signal_id=signal_id,
            action='MAINTENANCE_SCHEDULED',
            user_id=current_user_id,
            user_email=user.email,
            success=True,
            command_params={'days_from_now': days_from_now, 'notes': notes}
        )
        
        return jsonify({
            'success': True,
            'message': f"Maintenance scheduled for {signal.intersection_name}",
            'data': {
                'signal_id': signal.id,
                'next_maintenance_due': signal.next_maintenance_due.isoformat() if signal.next_maintenance_due else None
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Schedule maintenance error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to schedule maintenance'}), 500


# ============================================
# SIGNAL STATISTICS ROUTES
# ============================================

@traffic_bp.route('/statistics', methods=['GET'])
@jwt_required()
@role_required('admin', 'control_room')
def get_traffic_statistics():
    """
    Get comprehensive traffic signal statistics
    GET /api/v1/traffic/statistics?days=30
    """
    try:
        days = request.args.get('days', 30, type=int)
        cutoff_date = datetime.utcnow() - timedelta(days=days)
        
        signals = get_all_signals()
        
        # Calculate statistics
        stats = {
            'total_signals': len(signals),
            'online_signals': sum(1 for s in signals if s.is_online),
            'offline_signals': sum(1 for s in signals if not s.is_online),
            'signals_with_corridor': sum(1 for s in signals if s.supports_green_corridor),
            'total_corridors_served': sum(s.total_corridors_served for s in signals),
            'total_emergency_vehicles_served': sum(s.total_emergency_vehicles_served for s in signals),
            'total_time_saved_minutes': round(sum(s.time_saved_for_emergencies for s in signals), 2),
            'avg_response_time_ms': 0,
            'signal_uptime_percentage': 0
        }
        
        # Get logs for response time calculation
        logs = SignalLog.query.filter(SignalLog.created_at >= cutoff_date).all()
        
        if logs:
            response_times = [l.response_time_ms for l in logs if l.response_time_ms]
            if response_times:
                stats['avg_response_time_ms'] = round(sum(response_times) / len(response_times), 2)
        
        # Calculate uptime
        if stats['total_signals'] > 0:
            stats['signal_uptime_percentage'] = round(
                (stats['online_signals'] / stats['total_signals']) * 100, 2
            )
        
        return jsonify({
            'success': True,
            'data': stats,
            'period_days': days
        }), 200
        
    except Exception as e:
        logger.error(f"Get traffic statistics error: {str(e)}")
        return jsonify({'error': 'Failed to fetch statistics'}), 500


# ============================================
# SIGNAL LOGS ROUTES
# ============================================

@traffic_bp.route('/signals/<int:signal_id>/logs', methods=['GET'])
@jwt_required()
@role_required('admin', 'control_room')
def get_signal_logs(signal_id):
    """
    Get logs for a specific signal
    GET /api/v1/traffic/signals/<signal_id>/logs?limit=100
    """
    try:
        signal = find_signal_by_id(signal_id)
        
        if not signal:
            return jsonify({'error': 'Signal not found'}), 404
        
        limit = request.args.get('limit', 100, type=int)
        limit = min(limit, 500)
        
        logs = SignalLog.query.filter_by(
            signal_id=signal_id
        ).order_by(SignalLog.created_at.desc()).limit(limit).all()
        
        return jsonify({
            'success': True,
            'data': {
                'signal': {
                    'id': signal.id,
                    'intersection_name': signal.intersection_name
                },
                'logs': [log.to_dict() for log in logs],
                'count': len(logs)
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Get signal logs error: {str(e)}")
        return jsonify({'error': 'Failed to fetch logs'}), 500


# ============================================
# EXPORTS
# ============================================

__all__ = ['traffic_bp']