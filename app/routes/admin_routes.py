"""
Smart Emergency Vehicle Priority System - Admin Routes
Handles admin operations: user management, system monitoring, analytics, and configuration
Only accessible by ADMIN and SUPER_ADMIN roles
"""

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, timedelta
from loguru import logger
from functools import wraps

from app.extensions import db, cache, limiter
from app.models.user import (
    User, UserRole, UserStatus, TokenBlocklist, UserSession,
    find_user_by_id, find_user_by_email, find_user_by_username,
    get_all_active_users, get_users_by_role, create_default_admin
)
from app.models.vehicle import (
    EmergencyVehicle, VehicleType, VehicleStatus,
    get_all_emergency_vehicles, get_available_vehicles
)
from app.models.traffic_signal import TrafficSignal, SignalStatus, get_all_signals
from app.models.incident import Incident, get_incident_statistics, get_active_incidents
from app.models.corridor import GreenCorridor, get_corridor_statistics, get_active_corridors
from app.models.audit_log import (
    AuditLog, AuditAction, AuditSeverity, get_audit_logs, 
    get_audit_statistics, run_blockchain_verification, create_audit_log
)
from app.routes.auth_routes import role_required

# Create Blueprint
admin_bp = Blueprint('admin', __name__)

# ============================================
# HELPER FUNCTIONS
# ============================================

def get_client_ip():
    """Get client IP address from request"""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0]
    return request.remote_addr

def log_admin_action(action, user_id, user_email, details=None, entity_type=None, entity_id=None):
    """Log admin action to audit trail"""
    create_audit_log(
        action=action,
        user_id=user_id,
        user_email=user_email,
        entity_type=entity_type,
        entity_id=entity_id,
        action_details=details,
        ip_address=get_client_ip(),
        user_agent=request.headers.get('User-Agent', 'Unknown'),
        severity=AuditSeverity.INFO
    )

# ============================================
# USER MANAGEMENT ROUTES
# ============================================

@admin_bp.route('/users', methods=['GET'])
@jwt_required()
@role_required('admin', 'super_admin')
@cache.cached(timeout=60)  # Cache for 1 minute
def get_all_users():
    """
    Get all users with pagination and filters
    GET /api/v1/admin/users?page=1&limit=50&role=admin&status=active
    """
    try:
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 50, type=int)
        role = request.args.get('role')
        status = request.args.get('status')
        search = request.args.get('search')
        
        query = User.query
        
        # Apply filters
        if role:
            try:
                role_enum = UserRole(role)
                query = query.filter_by(role=role_enum)
            except ValueError:
                return jsonify({'error': f'Invalid role: {role}'}), 400
        
        if status:
            try:
                status_enum = UserStatus(status)
                query = query.filter_by(status=status_enum)
            except ValueError:
                return jsonify({'error': f'Invalid status: {status}'}), 400
        
        if search:
            query = query.filter(
                db.or_(
                    User.email.ilike(f'%{search}%'),
                    User.username.ilike(f'%{search}%'),
                    User.full_name.ilike(f'%{search}%')
                )
            )
        
        # Pagination
        total = query.count()
        users = query.order_by(User.created_at.desc()).offset((page - 1) * limit).limit(limit).all()
        
        # Log admin action
        current_user_id = get_jwt_identity()
        current_user = find_user_by_id(current_user_id)
        log_admin_action(
            action=AuditAction.ADMIN_ACTION,
            user_id=current_user_id,
            user_email=current_user.email if current_user else None,
            details={'action': 'view_users', 'filters': {'role': role, 'status': status, 'search': search}},
            entity_type='user'
        )
        
        return jsonify({
            'success': True,
            'data': {
                'users': [user.to_dict() for user in users],
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': total,
                    'pages': (total + limit - 1) // limit
                }
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Get all users error: {str(e)}")
        return jsonify({'error': 'Failed to fetch users'}), 500


@admin_bp.route('/users/<int:user_id>', methods=['GET'])
@jwt_required()
@role_required('admin', 'super_admin')
def get_user_details(user_id):
    """
    Get detailed information about a specific user
    GET /api/v1/admin/users/<user_id>
    """
    try:
        user = find_user_by_id(user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Get user statistics
        stats = {
            'total_sessions': UserSession.query.filter_by(user_id=user_id).count(),
            'active_sessions': UserSession.query.filter_by(user_id=user_id, is_active=True).count(),
            'total_audit_logs': AuditLog.query.filter_by(user_id=user_id).count(),
            'total_corridors_requested': GreenCorridor.query.filter_by(requested_by_id=user_id).count(),
            'last_login': user.last_login.isoformat() if user.last_login else None
        }
        
        current_user_id = get_jwt_identity()
        current_user = find_user_by_id(current_user_id)
        log_admin_action(
            action=AuditAction.ADMIN_ACTION,
            user_id=current_user_id,
            user_email=current_user.email if current_user else None,
            details={'action': 'view_user_details', 'target_user_id': user_id},
            entity_type='user',
            entity_id=user_id
        )
        
        return jsonify({
            'success': True,
            'data': {
                'user': user.to_dict(include_sensitive=True),
                'statistics': stats
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Get user details error: {str(e)}")
        return jsonify({'error': 'Failed to fetch user details'}), 500


@admin_bp.route('/users', methods=['POST'])
@jwt_required()
@role_required('admin', 'super_admin')
def create_user():
    """
    Create a new user (admin only)
    POST /api/v1/admin/users
    Body: {
        "email": "newuser@example.com",
        "username": "newuser",
        "full_name": "New User",
        "password": "Temp@123",
        "role": "control_room",
        "phone_number": "+1234567890"
    }
    """
    try:
        data = request.get_json()
        
        required_fields = ['email', 'username', 'full_name', 'password', 'role']
        for field in required_fields:
            if not data.get(field):
                return jsonify({'error': f'Missing required field: {field}'}), 400
        
        # Check if user exists
        if find_user_by_email(data['email']):
            return jsonify({'error': 'Email already exists'}), 409
        
        if find_user_by_username(data['username']):
            return jsonify({'error': 'Username already exists'}), 409
        
        # Validate role
        try:
            role = UserRole(data['role'])
        except ValueError:
            return jsonify({'error': f'Invalid role: {data["role"]}'}), 400
        
        # Create user
        user = User(
            email=data['email'],
            username=data['username'],
            full_name=data['full_name'],
            password=data['password'],
            role=role,
            phone_number=data.get('phone_number'),
            department=data.get('department'),
            employee_id=data.get('employee_id')
        )
        
        db.session.add(user)
        db.session.commit()
        
        current_user_id = get_jwt_identity()
        current_user = find_user_by_id(current_user_id)
        log_admin_action(
            action=AuditAction.USER_REGISTER,
            user_id=current_user_id,
            user_email=current_user.email if current_user else None,
            details={'created_user': user.email, 'role': role.value},
            entity_type='user',
            entity_id=user.id
        )
        
        logger.info(f"Admin {current_user.email} created user {user.email}")
        
        return jsonify({
            'success': True,
            'message': 'User created successfully',
            'data': {'user': user.to_dict()}
        }), 201
        
    except Exception as e:
        logger.error(f"Create user error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to create user'}), 500


@admin_bp.route('/users/<int:user_id>', methods=['PUT'])
@jwt_required()
@role_required('admin', 'super_admin')
def update_user(user_id):
    """
    Update user details
    PUT /api/v1/admin/users/<user_id>
    Body: {
        "full_name": "Updated Name",
        "phone_number": "+9876543210",
        "role": "admin",
        "status": "active",
        "department": "IT Department"
    }
    """
    try:
        user = find_user_by_id(user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        data = request.get_json()
        
        # Track changes for audit log
        changes = {}
        
        # Update allowed fields
        allowed_fields = ['full_name', 'phone_number', 'department', 'employee_id', 
                         'notification_enabled', 'email_notifications', 'sms_notifications']
        
        for field in allowed_fields:
            if field in data and getattr(user, field) != data[field]:
                changes[field] = {'old': getattr(user, field), 'new': data[field]}
                setattr(user, field, data[field])
        
        # Update role
        if 'role' in data:
            try:
                new_role = UserRole(data['role'])
                if user.role != new_role:
                    changes['role'] = {'old': user.role.value, 'new': new_role.value}
                    user.role = new_role
            except ValueError:
                return jsonify({'error': f'Invalid role: {data["role"]}'}), 400
        
        # Update status
        if 'status' in data:
            try:
                new_status = UserStatus(data['status'])
                if user.status != new_status:
                    changes['status'] = {'old': user.status.value, 'new': new_status.value}
                    user.status = new_status
            except ValueError:
                return jsonify({'error': f'Invalid status: {data["status"]}'}), 400
        
        db.session.commit()
        
        current_user_id = get_jwt_identity()
        current_user = find_user_by_id(current_user_id)
        log_admin_action(
            action=AuditAction.USER_UPDATE,
            user_id=current_user_id,
            user_email=current_user.email if current_user else None,
            details={'updated_user': user.email, 'changes': changes},
            entity_type='user',
            entity_id=user_id
        )
        
        logger.info(f"Admin {current_user.email} updated user {user.email}")
        
        return jsonify({
            'success': True,
            'message': 'User updated successfully',
            'data': {'user': user.to_dict(), 'changes': changes}
        }), 200
        
    except Exception as e:
        logger.error(f"Update user error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to update user'}), 500


@admin_bp.route('/users/<int:user_id>', methods=['DELETE'])
@jwt_required()
@role_required('admin', 'super_admin')
def delete_user(user_id):
    """
    Soft delete a user (deactivate)
    DELETE /api/v1/admin/users/<user_id>
    """
    try:
        user = find_user_by_id(user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        # Can't delete yourself
        current_user_id = get_jwt_identity()
        if user_id == current_user_id:
            return jsonify({'error': 'Cannot delete your own account'}), 400
        
        # Soft delete
        user.status = UserStatus.DELETED
        user.is_active = False
        db.session.commit()
        
        current_user = find_user_by_id(current_user_id)
        log_admin_action(
            action=AuditAction.USER_DELETE,
            user_id=current_user_id,
            user_email=current_user.email if current_user else None,
            details={'deleted_user': user.email},
            entity_type='user',
            entity_id=user_id
        )
        
        logger.info(f"Admin {current_user.email} deleted user {user.email}")
        
        return jsonify({
            'success': True,
            'message': f'User {user.email} has been deleted'
        }), 200
        
    except Exception as e:
        logger.error(f"Delete user error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to delete user'}), 500


@admin_bp.route('/users/reset-password/<int:user_id>', methods=['POST'])
@jwt_required()
@role_required('admin', 'super_admin')
def reset_user_password(user_id):
    """
    Reset user password (admin only)
    POST /api/v1/admin/users/reset-password/<user_id>
    Body: {"new_password": "NewTemp@123"}
    """
    try:
        user = find_user_by_id(user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        data = request.get_json()
        new_password = data.get('new_password')
        
        if not new_password:
            return jsonify({'error': 'New password is required'}), 400
        
        # Validate password strength
        from app.routes.auth_routes import validate_password
        is_valid, message = validate_password(new_password)
        if not is_valid:
            return jsonify({'error': message}), 400
        
        user.set_password(new_password)
        db.session.commit()
        
        current_user = find_user_by_id(get_jwt_identity())
        log_admin_action(
            action=AuditAction.ADMIN_ACTION,
            user_id=get_jwt_identity(),
            user_email=current_user.email if current_user else None,
            details={'action': 'reset_password', 'target_user': user.email},
            entity_type='user',
            entity_id=user_id
        )
        
        logger.info(f"Admin {current_user.email} reset password for user {user.email}")
        
        return jsonify({
            'success': True,
            'message': f'Password reset for user {user.email}'
        }), 200
        
    except Exception as e:
        logger.error(f"Reset password error: {str(e)}")
        db.session.rollback()
        return jsonify({'error': 'Failed to reset password'}), 500


# ============================================
# SYSTEM MONITORING ROUTES
# ============================================

@admin_bp.route('/dashboard/stats', methods=['GET'])
@jwt_required()
@role_required('admin', 'super_admin', 'control_room')
def get_system_stats():
    """
    Get system-wide statistics for admin dashboard
    GET /api/v1/admin/dashboard/stats
    """
    try:
        # Get counts
        total_users = User.query.count()
        active_users = User.query.filter_by(status=UserStatus.ACTIVE).count()
        
        total_vehicles = EmergencyVehicle.query.count()
        available_vehicles = EmergencyVehicle.query.filter_by(status=VehicleStatus.AVAILABLE).count()
        
        total_signals = TrafficSignal.query.count()
        active_corridor_signals = TrafficSignal.query.filter_by(current_status=SignalStatus.GREEN_CORRIDOR).count()
        
        active_incidents = len(get_active_incidents())
        active_corridors = len(get_active_corridors())
        
        # Recent activity
        last_24h = datetime.utcnow() - timedelta(hours=24)
        recent_audits = AuditLog.query.filter(AuditLog.timestamp >= last_24h).count()
        recent_incidents = Incident.query.filter(Incident.reported_at >= last_24h).count()
        recent_corridors = GreenCorridor.query.filter(GreenCorridor.requested_at >= last_24h).count()
        
        # System health
        online_signals = TrafficSignal.query.filter_by(is_online=True).count()
        
        stats = {
            'users': {
                'total': total_users,
                'active': active_users,
                'inactive': total_users - active_users
            },
            'vehicles': {
                'total': total_vehicles,
                'available': available_vehicles,
                'on_duty': EmergencyVehicle.query.filter_by(status=VehicleStatus.ON_DUTY).count(),
                'maintenance': EmergencyVehicle.query.filter_by(status=VehicleStatus.MAINTENANCE).count()
            },
            'signals': {
                'total': total_signals,
                'online': online_signals,
                'offline': total_signals - online_signals,
                'green_corridor_active': active_corridor_signals
            },
            'incidents': {
                'active': active_incidents,
                'today': Incident.query.filter(
                    Incident.reported_at >= datetime.utcnow().replace(hour=0, minute=0, second=0)
                ).count()
            },
            'corridors': {
                'active': active_corridors,
                'today': GreenCorridor.query.filter(
                    GreenCorridor.requested_at >= datetime.utcnow().replace(hour=0, minute=0, second=0)
                ).count()
            },
            'activity': {
                'audit_logs_24h': recent_audits,
                'incidents_24h': recent_incidents,
                'corridors_24h': recent_corridors
            },
            'timestamp': datetime.utcnow().isoformat()
        }
        
        current_user = find_user_by_id(get_jwt_identity())
        log_admin_action(
            action=AuditAction.ADMIN_ACTION,
            user_id=get_jwt_identity(),
            user_email=current_user.email if current_user else None,
            details={'action': 'view_system_stats'},
            entity_type='system'
        )
        
        return jsonify({
            'success': True,
            'data': stats
        }), 200
        
    except Exception as e:
        logger.error(f"Get system stats error: {str(e)}")
        return jsonify({'error': 'Failed to fetch system statistics'}), 500


@admin_bp.route('/system/health', methods=['GET'])
@jwt_required()
@role_required('admin', 'super_admin')
def get_system_health():
    """
    Get detailed system health status
    GET /api/v1/admin/system/health
    """
    try:
        health = {
            'status': 'healthy',
            'components': {},
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Check database
        try:
            db.session.execute('SELECT 1')
            health['components']['database'] = {'status': 'up', 'message': 'Connected'}
        except Exception as e:
            health['components']['database'] = {'status': 'down', 'message': str(e)}
            health['status'] = 'degraded'
        
        # Check Redis (if configured)
        try:
            from app.extensions import get_redis
            redis_client = get_redis()
            if redis_client:
                redis_client.ping()
                health['components']['redis'] = {'status': 'up', 'message': 'Connected'}
            else:
                health['components']['redis'] = {'status': 'disabled', 'message': 'Not configured'}
        except Exception as e:
            health['components']['redis'] = {'status': 'down', 'message': str(e)}
            health['status'] = 'degraded'
        
        # Check MQTT (if configured)
        try:
            from app.extensions import get_mqtt
            mqtt_client = get_mqtt()
            if mqtt_client:
                health['components']['mqtt'] = {'status': 'connected', 'message': 'MQTT broker connected'}
            else:
                health['components']['mqtt'] = {'status': 'disabled', 'message': 'Not configured'}
        except Exception as e:
            health['components']['mqtt'] = {'status': 'down', 'message': str(e)}
        
        # Signal connectivity
        total_signals = TrafficSignal.query.count()
        online_signals = TrafficSignal.query.filter_by(is_online=True).count()
        
        health['components']['traffic_signals'] = {
            'status': 'healthy' if online_signals > total_signals * 0.8 else 'degraded',
            'online': online_signals,
            'total': total_signals,
            'percentage': round((online_signals / total_signals * 100) if total_signals > 0 else 0, 2)
        }
        
        if health['components']['traffic_signals']['percentage'] < 80:
            health['status'] = 'degraded'
        
        return jsonify({
            'success': True,
            'data': health
        }), 200
        
    except Exception as e:
        logger.error(f"System health error: {str(e)}")
        return jsonify({'error': 'Failed to get system health'}), 500


# ============================================
# ANALYTICS ROUTES
# ============================================

@admin_bp.route('/analytics/overview', methods=['GET'])
@jwt_required()
@role_required('admin', 'super_admin', 'control_room')
def get_analytics_overview():
    """
    Get comprehensive analytics overview
    GET /api/v1/admin/analytics/overview?days=30
    """
    try:
        days = request.args.get('days', 30, type=int)
        
        incident_stats = get_incident_statistics(days=days)
        corridor_stats = get_corridor_statistics(days=days)
        audit_stats = get_audit_statistics(days=days)
        
        # Additional analytics
        response_time_avg = db.session.query(db.func.avg(Incident.response_time)).filter(
            Incident.response_time.isnot(None),
            Incident.reported_at >= datetime.utcnow() - timedelta(days=days)
        ).scalar() or 0
        
        time_saved_avg = db.session.query(db.func.avg(GreenCorridor.time_saved_seconds)).filter(
            GreenCorridor.time_saved_seconds.isnot(None),
            GreenCorridor.created_at >= datetime.utcnow() - timedelta(days=days)
        ).scalar() or 0
        
        analytics = {
            'period_days': days,
            'incidents': incident_stats,
            'corridors': corridor_stats,
            'audit': audit_stats,
            'performance': {
                'average_response_time_seconds': round(response_time_avg, 2),
                'average_time_saved_seconds': round(time_saved_avg, 2),
                'total_time_saved_hours': round(corridor_stats.get('total_time_saved_seconds', 0) / 3600, 2),
                'total_distance_covered_km': round(corridor_stats.get('total_distance_km', 0), 2)
            },
            'timestamp': datetime.utcnow().isoformat()
        }
        
        return jsonify({
            'success': True,
            'data': analytics
        }), 200
        
    except Exception as e:
        logger.error(f"Analytics overview error: {str(e)}")
        return jsonify({'error': 'Failed to fetch analytics'}), 500


# ============================================
# AUDIT LOG ROUTES
# ============================================

@admin_bp.route('/audit-logs', methods=['GET'])
@jwt_required()
@role_required('admin', 'super_admin')
def get_audit_logs_route():
    """
    Get audit logs with filters
    GET /api/v1/admin/audit-logs?page=1&limit=50&action=user_login&user_id=1&start_date=2024-01-01
    """
    try:
        page = request.args.get('page', 1, type=int)
        limit = request.args.get('limit', 50, type=int)
        
        filters = {}
        
        if request.args.get('action'):
            actions = request.args.get('action').split(',')
            from app.models.audit_log import AuditAction
            filters['action'] = [AuditAction(a) for a in actions if hasattr(AuditAction, a.upper())]
        
        if request.args.get('user_id'):
            filters['user_id'] = request.args.get('user_id', type=int)
        
        if request.args.get('entity_type'):
            filters['entity_type'] = request.args.get('entity_type')
        
        if request.args.get('entity_id'):
            filters['entity_id'] = request.args.get('entity_id', type=int)
        
        if request.args.get('severity'):
            from app.models.audit_log import AuditSeverity
            filters['severity'] = AuditSeverity(request.args.get('severity'))
        
        if request.args.get('start_date'):
            filters['start_date'] = datetime.fromisoformat(request.args.get('start_date'))
        
        if request.args.get('end_date'):
            filters['end_date'] = datetime.fromisoformat(request.args.get('end_date'))
        
        logs = get_audit_logs(filters=filters if filters else None, limit=limit, offset=(page-1)*limit)
        total = AuditLog.query.count()
        
        return jsonify({
            'success': True,
            'data': {
                'logs': [log.to_dict(include_blockchain=True) for log in logs],
                'pagination': {
                    'page': page,
                    'limit': limit,
                    'total': total,
                    'pages': (total + limit - 1) // limit
                }
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Get audit logs error: {str(e)}")
        return jsonify({'error': 'Failed to fetch audit logs'}), 500


@admin_bp.route('/audit-logs/verify', methods=['POST'])
@jwt_required()
@role_required('super_admin')
def verify_audit_integrity():
    """
    Run blockchain verification on all audit logs
    POST /api/v1/admin/audit-logs/verify
    """
    try:
        verification = run_blockchain_verification()
        
        current_user = find_user_by_id(get_jwt_identity())
        log_admin_action(
            action=AuditAction.BLOCKCHAIN_VERIFY,
            user_id=get_jwt_identity(),
            user_email=current_user.email if current_user else None,
            details={
                'total_checked': verification.total_records_checked,
                'tampered_found': verification.tampered_records_found
            },
            entity_type='system'
        )
        
        return jsonify({
            'success': True,
            'message': f'Verification completed. Checked {verification.total_records_checked} records.',
            'data': verification.to_dict()
        }), 200
        
    except Exception as e:
        logger.error(f"Verify audit integrity error: {str(e)}")
        return jsonify({'error': 'Failed to verify audit integrity'}), 500


# ============================================
# SYSTEM CONFIGURATION ROUTES
# ============================================

@admin_bp.route('/system/config', methods=['GET'])
@jwt_required()
@role_required('super_admin')
def get_system_config():
    """
    Get current system configuration
    GET /api/v1/admin/system/config
    """
    try:
        # Return non-sensitive configuration
        config = {
            'environment': current_app.config.get('ENVIRONMENT', 'development'),
            'debug': current_app.config.get('DEBUG', False),
            'api_version': '1.0.0',
            'features': {
                'blockchain_enabled': current_app.config.get('BLOCKCHAIN_ENABLED', False),
                'mqtt_enabled': bool(current_app.config.get('MQTT_BROKER_URL')),
                'adaptive_signals': current_app.config.get('adaptive_mode_enabled', True)
            },
            'limits': {
                'max_corridor_distance_km': current_app.config.get('MAX_CORRIDOR_DISTANCE_KM', 10),
                'green_corridor_pre_time': current_app.config.get('GREEN_CORRIDOR_PRE_TIME', 15),
                'max_concurrent_corridors': 50
            }
        }
        
        return jsonify({
            'success': True,
            'data': config
        }), 200
        
    except Exception as e:
        logger.error(f"Get system config error: {str(e)}")
        return jsonify({'error': 'Failed to fetch system config'}), 500


# ============================================
# EXPORTS
# ============================================

__all__ = ['admin_bp']