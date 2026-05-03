"""
Smart Emergency Vehicle Priority System - Dashboard Routes
Provides real-time dashboard data, statistics, alerts, and monitoring for control room
"""

from flask import Blueprint, request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from datetime import datetime, timedelta
from loguru import logger
from collections import defaultdict

from app.extensions import db, cache, socketio
from app.models.user import User, UserRole, find_user_by_id
from app.models.vehicle import (
    EmergencyVehicle, VehicleType, VehicleStatus,
    get_all_emergency_vehicles, get_available_vehicles
)
from app.models.traffic_signal import TrafficSignal, SignalStatus, get_all_signals
from app.models.incident import (
    Incident, IncidentType, IncidentSeverity, IncidentStatus,
    get_active_incidents, get_incident_statistics
)
from app.models.corridor import (
    GreenCorridor, CorridorStatus, get_active_corridors, 
    get_corridor_statistics, find_corridor_by_vehicle
)
from app.routes.auth_routes import role_required

# Create Blueprint
dashboard_bp = Blueprint('dashboard', __name__)

# ============================================
# HELPER FUNCTIONS
# ============================================

def get_recent_activities(limit=20):
    """Get recent system activities from corridors and incidents"""
    activities = []
    
    # Recent corridors
    recent_corridors = GreenCorridor.query.order_by(
        GreenCorridor.created_at.desc()
    ).limit(limit // 2).all()
    
    for corridor in recent_corridors:
        vehicle = EmergencyVehicle.query.get(corridor.vehicle_id)
        activities.append({
            'id': corridor.id,
            'type': 'corridor',
            'action': f"Green corridor {corridor.status.value}",
            'vehicle': vehicle.registration_number if vehicle else 'Unknown',
            'status': corridor.status.value if corridor.status else None,
            'timestamp': corridor.created_at.isoformat(),
            'details': {
                'distance_km': corridor.path_distance_km,
                'time_saved_seconds': corridor.time_saved_seconds
            }
        })
    
    # Recent incidents
    recent_incidents = Incident.query.order_by(
        Incident.reported_at.desc()
    ).limit(limit // 2).all()
    
    for incident in recent_incidents:
        activities.append({
            'id': incident.id,
            'type': 'incident',
            'action': f"Incident {incident.status.value}",
            'title': incident.title[:50],
            'severity': incident.severity.value if incident.severity else None,
            'timestamp': incident.reported_at.isoformat(),
            'details': {
                'incident_type': incident.incident_type.value if incident.incident_type else None,
                'patient_count': incident.patient_count
            }
        })
    
    # Sort by timestamp and return top limit
    activities.sort(key=lambda x: x['timestamp'], reverse=True)
    return activities[:limit]


def get_hourly_incidents(hours=24):
    """Get hourly incident count for chart data"""
    cutoff = datetime.utcnow() - timedelta(hours=hours)
    incidents = Incident.query.filter(Incident.reported_at >= cutoff).all()
    
    hourly_data = defaultdict(int)
    for incident in incidents:
        hour_key = incident.reported_at.strftime('%Y-%m-%d %H:00')
        hourly_data[hour_key] += 1
    
    # Prepare for chart
    hours_list = []
    counts_list = []
    for i in range(hours):
        hour_time = datetime.utcnow() - timedelta(hours=hours - i - 1)
        hour_key = hour_time.strftime('%Y-%m-%d %H:00')
        hours_list.append(hour_time.strftime('%H:00'))
        counts_list.append(hourly_data.get(hour_key, 0))
    
    return {
        'labels': hours_list,
        'datasets': [{
            'label': 'Incidents',
            'data': counts_list,
            'borderColor': '#ef4444',
            'backgroundColor': 'rgba(239, 68, 68, 0.1)'
        }]
    }


def get_response_time_trend(days=7):
    """Get average response time trend for chart"""
    response_times = []
    dates = []
    
    for i in range(days):
        date = datetime.utcnow().date() - timedelta(days=days - i - 1)
        start = datetime.combine(date, datetime.min.time())
        end = datetime.combine(date, datetime.max.time())
        
        avg_response = db.session.query(db.func.avg(Incident.response_time)).filter(
            Incident.resolved_at >= start,
            Incident.resolved_at <= end,
            Incident.response_time.isnot(None)
        ).scalar() or 0
        
        dates.append(date.strftime('%b %d'))
        response_times.append(round(avg_response, 1) if avg_response else 0)
    
    return {
        'labels': dates,
        'datasets': [{
            'label': 'Avg Response Time (seconds)',
            'data': response_times,
            'borderColor': '#3b82f6',
            'backgroundColor': 'rgba(59, 130, 246, 0.1)',
            'fill': True
        }]
    }


def get_vehicle_status_distribution():
    """Get vehicle status distribution for pie chart"""
    vehicles = get_all_emergency_vehicles()
    
    status_counts = defaultdict(int)
    for vehicle in vehicles:
        status_name = vehicle.status.value if vehicle.status else 'unknown'
        status_counts[status_name] += 1
    
    # Color mapping
    colors = {
        'available': '#22c55e',
        'on_duty': '#ef4444',
        'en_route': '#f59e0b',
        'at_scene': '#8b5cf6',
        'returning': '#06b6d4',
        'off_duty': '#6b7280',
        'maintenance': '#ef4444',
        'out_of_service': '#9ca3af'
    }
    
    return {
        'labels': list(status_counts.keys()),
        'datasets': [{
            'data': list(status_counts.values()),
            'backgroundColor': [colors.get(k, '#3b82f6') for k in status_counts.keys()],
            'borderWidth': 0
        }]
    }


def get_incident_type_distribution():
    """Get incident type distribution for pie chart"""
    incidents = Incident.query.filter(
        Incident.reported_at >= datetime.utcnow() - timedelta(days=30)
    ).all()
    
    type_counts = defaultdict(int)
    for incident in incidents:
        type_name = incident.incident_type.value if incident.incident_type else 'unknown'
        type_counts[type_name] += 1
    
    # Color mapping
    colors = {
        'medical_emergency': '#ef4444',
        'accident': '#f59e0b',
        'fire': '#dc2626',
        'crime': '#8b5cf6',
        'natural_disaster': '#06b6d4',
        'hazmat': '#84cc16',
        'rescue_operation': '#14b8a6',
        'bomb_threat': '#d946ef'
    }
    
    return {
        'labels': [t.replace('_', ' ').title() for t in type_counts.keys()],
        'datasets': [{
            'data': list(type_counts.values()),
            'backgroundColor': [colors.get(k, '#6b7280') for k in type_counts.keys()],
            'borderWidth': 0
        }]
    }

# ============================================
# MAIN DASHBOARD ROUTES
# ============================================

@dashboard_bp.route('/stats', methods=['GET'])
@jwt_required()
@cache.cached(timeout=30)  # Cache for 30 seconds
def get_dashboard_stats():
    """
    Get main dashboard statistics (KPI cards)
    GET /api/v1/dashboard/stats
    """
    try:
        # Active counts
        active_incidents = len(get_active_incidents())
        active_corridors = len(get_active_corridors())
        
        # Vehicle counts
        total_vehicles = EmergencyVehicle.query.count()
        available_vehicles = EmergencyVehicle.query.filter_by(status=VehicleStatus.AVAILABLE).count()
        on_duty_vehicles = EmergencyVehicle.query.filter_by(status=VehicleStatus.ON_DUTY).count()
        
        # Incident stats for today
        today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        incidents_today = Incident.query.filter(Incident.reported_at >= today_start).count()
        resolved_today = Incident.query.filter(Incident.resolved_at >= today_start).count()
        
        # Corridor stats for today
        corridors_today = GreenCorridor.query.filter(
            GreenCorridor.requested_at >= today_start
        ).count()
        completed_today = GreenCorridor.query.filter(
            GreenCorridor.completed_at >= today_start
        ).count()
        
        # Average response time (last 24 hours)
        last_24h = datetime.utcnow() - timedelta(hours=24)
        avg_response = db.session.query(db.func.avg(Incident.response_time)).filter(
            Incident.response_time.isnot(None),
            Incident.arrived_at >= last_24h
        ).scalar() or 0
        
        # Time saved today
        time_saved_today = db.session.query(db.func.sum(GreenCorridor.time_saved_seconds)).filter(
            GreenCorridor.completed_at >= today_start,
            GreenCorridor.time_saved_seconds.isnot(None)
        ).scalar() or 0
        
        stats = {
            'active_incidents': active_incidents,
            'active_corridors': active_corridors,
            'total_vehicles': total_vehicles,
            'available_vehicles': available_vehicles,
            'on_duty_vehicles': on_duty_vehicles,
            'incidents_today': incidents_today,
            'resolved_today': resolved_today,
            'corridors_today': corridors_today,
            'completed_today': completed_today,
            'avg_response_time_seconds': round(avg_response, 1) if avg_response else 0,
            'avg_response_time_minutes': round(avg_response / 60, 1) if avg_response else 0,
            'time_saved_today_seconds': int(time_saved_today),
            'time_saved_today_minutes': round(time_saved_today / 60, 1),
            'success_rate': round((completed_today / corridors_today * 100) if corridors_today > 0 else 0, 1),
            'timestamp': datetime.utcnow().isoformat()
        }
        
        return jsonify({
            'success': True,
            'data': stats
        }), 200
        
    except Exception as e:
        logger.error(f"Get dashboard stats error: {str(e)}")
        return jsonify({'error': 'Failed to fetch dashboard stats'}), 500


@dashboard_bp.route('/realtime', methods=['GET'])
@jwt_required()
def get_realtime_data():
    """
    Get real-time data for live dashboard (refreshed frequently)
    GET /api/v1/dashboard/realtime
    """
    try:
        # Active incidents with basic info
        active_incidents_list = []
        for incident in get_active_incidents():
            active_incidents_list.append({
                'id': incident.id,
                'title': incident.title[:50],
                'type': incident.incident_type.value if incident.incident_type else None,
                'severity': incident.severity.value if incident.severity else None,
                'status': incident.status.value if incident.status else None,
                'location': {
                    'latitude': incident.latitude,
                    'longitude': incident.longitude,
                    'address': incident.address
                },
                'patient_count': incident.patient_count,
                'reported_at': incident.reported_at.isoformat()
            })
        
        # Active corridors
        active_corridors_list = []
        for corridor in get_active_corridors():
            vehicle = EmergencyVehicle.query.get(corridor.vehicle_id)
            active_corridors_list.append({
                'id': corridor.id,
                'vehicle_id': corridor.vehicle_id,
                'vehicle_registration': vehicle.registration_number if vehicle else 'Unknown',
                'status': corridor.status.value if corridor.status else None,
                'progress_percentage': corridor.progress_percentage,
                'remaining_time_seconds': corridor.remaining_time_seconds,
                'remaining_distance_km': corridor.remaining_distance_km,
                'destination': corridor.destination_address
            })
        
        # Vehicle locations (live tracking)
        vehicle_locations = []
        vehicles = EmergencyVehicle.query.filter(
            EmergencyVehicle.current_latitude.isnot(None),
            EmergencyVehicle.is_active == True
        ).limit(100).all()
        
        for vehicle in vehicles:
            vehicle_locations.append({
                'id': vehicle.id,
                'registration_number': vehicle.registration_number,
                'vehicle_type': vehicle.vehicle_type.value if vehicle.vehicle_type else None,
                'status': vehicle.status.value if vehicle.status else None,
                'location': {
                    'latitude': vehicle.current_latitude,
                    'longitude': vehicle.current_longitude,
                    'speed': vehicle.current_speed,
                    'heading': vehicle.current_heading
                },
                'is_siren_active': vehicle.is_siren_active,
                'last_update': vehicle.last_location_update.isoformat() if vehicle.last_location_update else None
            })
        
        # Signal status (for map visualization)
        signal_status = []
        signals = TrafficSignal.query.filter_by(is_active=True).limit(50).all()
        
        for signal in signals:
            signal_status.append({
                'id': signal.id,
                'intersection_name': signal.intersection_name,
                'location': {
                    'latitude': signal.latitude,
                    'longitude': signal.longitude
                },
                'status': signal.current_status.value if signal.current_status else None,
                'current_green_direction': signal.current_green_direction.value if signal.current_green_direction else None,
                'is_corridor_active': signal.is_corridor_active()
            })
        
        return jsonify({
            'success': True,
            'data': {
                'active_incidents': active_incidents_list,
                'active_corridors': active_corridors_list,
                'vehicle_locations': vehicle_locations,
                'signal_status': signal_status,
                'counts': {
                    'active_incidents': len(active_incidents_list),
                    'active_corridors': len(active_corridors_list),
                    'vehicles_tracked': len(vehicle_locations),
                    'signals_monitored': len(signal_status)
                },
                'timestamp': datetime.utcnow().isoformat()
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Get realtime data error: {str(e)}")
        return jsonify({'error': 'Failed to fetch realtime data'}), 500


@dashboard_bp.route('/alerts', methods=['GET'])
@jwt_required()
def get_alerts():
    """
    Get active alerts and notifications
    GET /api/v1/dashboard/alerts
    """
    try:
        alerts = []
        
        # Check for high severity active incidents
        high_severity_incidents = Incident.query.filter(
            Incident.severity.in_([IncidentSeverity.CRITICAL, IncidentSeverity.HIGH]),
            Incident.status != IncidentStatus.RESOLVED,
            Incident.status != IncidentStatus.CANCELLED
        ).all()
        
        for incident in high_severity_incidents:
            alerts.append({
                'id': f"incident_{incident.id}",
                'type': 'critical_incident',
                'severity': incident.severity.value if incident.severity else 'high',
                'title': incident.title,
                'message': f"High severity {incident.incident_type.value if incident.incident_type else 'incident'} reported",
                'timestamp': incident.reported_at.isoformat(),
                'is_read': False,
                'action_url': f"/incidents/{incident.id}"
            })
        
        # Check for low fuel/status vehicles
        low_fuel_vehicles = EmergencyVehicle.query.filter(
            EmergencyVehicle.fuel_level < 20,
            EmergencyVehicle.status == VehicleStatus.ON_DUTY
        ).all()
        
        for vehicle in low_fuel_vehicles:
            alerts.append({
                'id': f"vehicle_{vehicle.id}",
                'type': 'warning',
                'severity': 'warning',
                'title': 'Low Fuel Alert',
                'message': f"Vehicle {vehicle.registration_number} has low fuel ({vehicle.fuel_level}%)",
                'timestamp': datetime.utcnow().isoformat(),
                'is_read': False,
                'action_url': f"/vehicles/{vehicle.id}"
            })
        
        # Check for offline signals
        offline_signals = TrafficSignal.query.filter_by(is_online=False, is_active=True).limit(10).all()
        
        for signal in offline_signals:
            alerts.append({
                'id': f"signal_{signal.id}",
                'type': 'warning',
                'severity': 'warning',
                'title': 'Signal Offline',
                'message': f"Traffic signal at {signal.intersection_name} is offline",
                'timestamp': datetime.utcnow().isoformat(),
                'is_read': False,
                'action_url': f"/signals/{signal.id}"
            })
        
        # Sort by severity (critical first, then by time)
        severity_order = {'critical': 0, 'high': 1, 'warning': 2, 'info': 3}
        alerts.sort(key=lambda x: (severity_order.get(x.get('severity', 'info'), 4), x['timestamp']), reverse=False)
        
        return jsonify({
            'success': True,
            'data': {
                'alerts': alerts[:20],  # Limit to 20
                'total': len(alerts),
                'critical_count': len([a for a in alerts if a.get('severity') == 'critical']),
                'warning_count': len([a for a in alerts if a.get('severity') == 'warning'])
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Get alerts error: {str(e)}")
        return jsonify({'error': 'Failed to fetch alerts'}), 500


# ============================================
# CHART DATA ROUTES
# ============================================

@dashboard_bp.route('/charts/incidents-hourly', methods=['GET'])
@jwt_required()
def get_hourly_incidents_chart():
    """
    Get hourly incident data for chart
    GET /api/v1/dashboard/charts/incidents-hourly?hours=24
    """
    try:
        hours = request.args.get('hours', 24, type=int)
        hours = min(hours, 168)  # Max 7 days
        
        data = get_hourly_incidents(hours)
        
        return jsonify({
            'success': True,
            'data': data
        }), 200
        
    except Exception as e:
        logger.error(f"Get hourly incidents error: {str(e)}")
        return jsonify({'error': 'Failed to fetch chart data'}), 500


@dashboard_bp.route('/charts/response-time-trend', methods=['GET'])
@jwt_required()
def get_response_time_trend_chart():
    """
    Get response time trend for chart
    GET /api/v1/dashboard/charts/response-time-trend?days=7
    """
    try:
        days = request.args.get('days', 7, type=int)
        days = min(days, 30)  # Max 30 days
        
        data = get_response_time_trend(days)
        
        return jsonify({
            'success': True,
            'data': data
        }), 200
        
    except Exception as e:
        logger.error(f"Get response time trend error: {str(e)}")
        return jsonify({'error': 'Failed to fetch chart data'}), 500


@dashboard_bp.route('/charts/vehicle-status', methods=['GET'])
@jwt_required()
def get_vehicle_status_chart():
    """
    Get vehicle status distribution for pie chart
    GET /api/v1/dashboard/charts/vehicle-status
    """
    try:
        data = get_vehicle_status_distribution()
        
        return jsonify({
            'success': True,
            'data': data
        }), 200
        
    except Exception as e:
        logger.error(f"Get vehicle status chart error: {str(e)}")
        return jsonify({'error': 'Failed to fetch chart data'}), 500


@dashboard_bp.route('/charts/incident-types', methods=['GET'])
@jwt_required()
def get_incident_types_chart():
    """
    Get incident type distribution for pie chart
    GET /api/v1/dashboard/charts/incident-types
    """
    try:
        data = get_incident_type_distribution()
        
        return jsonify({
            'success': True,
            'data': data
        }), 200
        
    except Exception as e:
        logger.error(f"Get incident types chart error: {str(e)}")
        return jsonify({'error': 'Failed to fetch chart data'}), 500


@dashboard_bp.route('/charts/corridor-performance', methods=['GET'])
@jwt_required()
def get_corridor_performance():
    """
    Get corridor performance metrics
    GET /api/v1/dashboard/charts/corridor-performance?days=30
    """
    try:
        days = request.args.get('days', 30, type=int)
        
        corridor_stats = get_corridor_statistics(days=days)
        
        # Prepare chart data
        performance = {
            'total_corridors': corridor_stats.get('total_corridors', 0),
            'completed_corridors': corridor_stats.get('completed_corridors', 0),
            'cancelled_corridors': corridor_stats.get('cancelled_corridors', 0),
            'success_rate': corridor_stats.get('success_rate', 0),
            'total_time_saved_hours': round(corridor_stats.get('total_time_saved_seconds', 0) / 3600, 1),
            'total_distance_km': round(corridor_stats.get('total_distance_km', 0), 1),
            'avg_time_saved_seconds': corridor_stats.get('average_time_saved_seconds', 0),
            'avg_distance_km': corridor_stats.get('average_distance_km', 0)
        }
        
        return jsonify({
            'success': True,
            'data': performance
        }), 200
        
    except Exception as e:
        logger.error(f"Get corridor performance error: {str(e)}")
        return jsonify({'error': 'Failed to fetch performance data'}), 500


# ============================================
# ACTIVITY FEED ROUTES
# ============================================

@dashboard_bp.route('/recent-activity', methods=['GET'])
@jwt_required()
def get_recent_activity():
    """
    Get recent system activity feed
    GET /api/v1/dashboard/recent-activity?limit=20
    """
    try:
        limit = request.args.get('limit', 20, type=int)
        limit = min(limit, 100)  # Max 100
        
        activities = get_recent_activities(limit)
        
        return jsonify({
            'success': True,
            'data': activities,
            'count': len(activities)
        }), 200
        
    except Exception as e:
        logger.error(f"Get recent activity error: {str(e)}")
        return jsonify({'error': 'Failed to fetch activity'}), 500


# ============================================
# MAP DATA ROUTES
# ============================================

@dashboard_bp.route('/map-data', methods=['GET'])
@jwt_required()
def get_map_data():
    """
    Get all data needed for map visualization
    GET /api/v1/dashboard/map-data
    """
    try:
        # Active incidents with location
        incidents = []
        for incident in get_active_incidents():
            incidents.append({
                'id': incident.id,
                'type': 'incident',
                'title': incident.title,
                'incident_type': incident.incident_type.value if incident.incident_type else None,
                'severity': incident.severity.value if incident.severity else None,
                'latitude': incident.latitude,
                'longitude': incident.longitude,
                'status': incident.status.value if incident.status else None,
                'icon': get_incident_icon(incident.incident_type),
                'color': get_severity_color(incident.severity)
            })
        
        # Active vehicles with location
        vehicles = []
        for vehicle in EmergencyVehicle.query.filter(
            EmergencyVehicle.current_latitude.isnot(None),
            EmergencyVehicle.is_active == True
        ).all():
            vehicles.append({
                'id': vehicle.id,
                'type': 'vehicle',
                'registration': vehicle.registration_number,
                'vehicle_type': vehicle.vehicle_type.value if vehicle.vehicle_type else None,
                'latitude': vehicle.current_latitude,
                'longitude': vehicle.current_longitude,
                'status': vehicle.status.value if vehicle.status else None,
                'speed': vehicle.current_speed,
                'is_siren_active': vehicle.is_siren_active,
                'icon': get_vehicle_icon(vehicle.vehicle_type),
                'color': get_vehicle_status_color(vehicle.status)
            })
        
        # Traffic signals with location
        signals = []
        for signal in TrafficSignal.query.filter_by(is_active=True).all():
            signals.append({
                'id': signal.id,
                'type': 'signal',
                'name': signal.intersection_name,
                'latitude': signal.latitude,
                'longitude': signal.longitude,
                'status': signal.current_status.value if signal.current_status else None,
                'is_corridor_active': signal.is_corridor_active(),
                'icon': 'traffic-light',
                'color': get_signal_color(signal)
            })
        
        # Active corridors (paths)
        corridors = []
        for corridor in get_active_corridors():
            corridors.append({
                'id': corridor.id,
                'type': 'corridor',
                'vehicle_id': corridor.vehicle_id,
                'path': corridor.path_points,
                'progress': corridor.progress_percentage,
                'status': corridor.status.value if corridor.status else None
            })
        
        return jsonify({
            'success': True,
            'data': {
                'incidents': incidents,
                'vehicles': vehicles,
                'signals': signals,
                'corridors': corridors,
                'center': {
                    'latitude': 28.6139,
                    'longitude': 77.2090
                },
                'zoom': 12
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Get map data error: {str(e)}")
        return jsonify({'error': 'Failed to fetch map data'}), 500


# ============================================
# HELPER FUNCTIONS FOR MAP ICONS
# ============================================

def get_incident_icon(incident_type):
    """Get icon name for incident type"""
    icon_map = {
        IncidentType.MEDICAL_EMERGENCY: 'heartbeat',
        IncidentType.ACCIDENT: 'car-crash',
        IncidentType.FIRE: 'fire',
        IncidentType.CRIME: 'police-badge',
        IncidentType.NATURAL_DISASTER: 'earthquake',
        IncidentType.HAZMAT: 'biohazard',
        IncidentType.RESCUE_OPERATION: 'rescue',
        IncidentType.BOMB_THREAT: 'bomb'
    }
    return icon_map.get(incident_type, 'alert-circle')


def get_severity_color(severity):
    """Get color for severity level"""
    color_map = {
        IncidentSeverity.CRITICAL: '#ef4444',
        IncidentSeverity.HIGH: '#f97316',
        IncidentSeverity.MEDIUM: '#f59e0b',
        IncidentSeverity.LOW: '#22c55e'
    }
    return color_map.get(severity, '#6b7280')


def get_vehicle_icon(vehicle_type):
    """Get icon name for vehicle type"""
    icon_map = {
        VehicleType.AMBULANCE: 'ambulance',
        VehicleType.FIRE_BRIGADE: 'fire-truck',
        VehicleType.POLICE: 'police-car',
        VehicleType.DISASTER_MANAGEMENT: 'truck',
        VehicleType.RESCUE: 'rescue'
    }
    return icon_map.get(vehicle_type, 'car')


def get_vehicle_status_color(status):
    """Get color for vehicle status"""
    color_map = {
        VehicleStatus.AVAILABLE: '#22c55e',
        VehicleStatus.ON_DUTY: '#ef4444',
        VehicleStatus.EN_ROUTE: '#f59e0b',
        VehicleStatus.AT_SCENE: '#8b5cf6',
        VehicleStatus.RETURNING: '#06b6d4',
        VehicleStatus.OFF_DUTY: '#6b7280',
        VehicleStatus.MAINTENANCE: '#ef4444'
    }
    return color_map.get(status, '#3b82f6')


def get_signal_color(signal):
    """Get color for signal status"""
    if signal.is_corridor_active():
        return '#22c55e'
    elif signal.current_status == SignalStatus.RED_ALERT:
        return '#ef4444'
    elif signal.current_status == SignalStatus.MANUAL:
        return '#f59e0b'
    elif not signal.is_online:
        return '#6b7280'
    return '#3b82f6'


# ============================================
# WEBSOCKET EVENT HANDLERS (Real-time updates)
# ============================================

@dashboard_bp.route('/subscribe', methods=['POST'])
@jwt_required()
def subscribe_to_updates():
    """
    Subscribe to real-time dashboard updates via WebSocket
    POST /api/v1/dashboard/subscribe
    Body: {"topics": ["incidents", "vehicles", "corridors"]}
    """
    try:
        current_user_id = get_jwt_identity()
        data = request.get_json()
        topics = data.get('topics', ['incidents', 'vehicles', 'corridors', 'signals'])
        
        # In production, this would set up WebSocket subscriptions
        # For now, return success
        
        return jsonify({
            'success': True,
            'message': 'Subscribed to real-time updates',
            'topics': topics,
            'websocket_url': '/socket.io/?EIO=4&transport=websocket'
        }), 200
        
    except Exception as e:
        logger.error(f"Subscribe error: {str(e)}")
        return jsonify({'error': 'Failed to subscribe'}), 500


# ============================================
# EXPORTS
# ============================================

__all__ = ['dashboard_bp']
