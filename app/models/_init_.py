"""
Smart Emergency Vehicle Priority System - Models Package
This file initializes all database models and exports them for use in the application
"""

# ============================================
# IMPORT ALL MODELS
# ============================================
import datetime
# User & Authentication Models
from app.models.user import (
    User,
    UserRole,
    UserStatus,
    TokenBlocklist,
    UserSession,
    UserInvitation,
    find_user_by_email,
    find_user_by_username,
    find_user_by_id,
    get_all_active_users,
    get_users_by_role,
    create_default_admin
)

# Emergency Vehicle Models
from app.models.vehicle import (
    EmergencyVehicle,
    VehicleType,
    VehicleStatus,
    VehicleEmergencyLevel,
    VehicleEquipmentStatus,
    VehicleLocationHistory,
    find_vehicle_by_id,
    find_vehicle_by_registration,
    find_vehicle_by_uuid,
    get_all_emergency_vehicles,
    get_available_vehicles,
    get_nearest_vehicle,
    create_sample_vehicles
)

# Traffic Signal Models
from app.models.traffic_signal import (
    TrafficSignal,
    SignalStatus,
    SignalDirection,
    LaneType,
    TrafficDensity,
    SignalLog,
    find_signal_by_id,
    find_signal_by_intersection_id,
    find_signal_by_uuid,
    get_all_signals,
    get_signals_on_route,
    get_next_signal_on_path,
    create_sample_signals
)

# Incident Models
from app.models.incident import (
    Incident,
    IncidentType,
    IncidentSeverity,
    IncidentStatus,
    PatientCondition,
    IncidentAlert,
    find_incident_by_id,
    find_incident_by_uuid,
    get_active_incidents,
    get_incidents_by_status,
    get_nearby_incidents,
    get_incident_statistics,
    create_sample_incident
)

# Green Corridor Models
from app.models.corridor import (
    GreenCorridor,
    CorridorStatus,
    CorridorType,
    PathCalculationMethod,
    find_corridor_by_id,
    find_corridor_by_uuid,
    find_corridor_by_vehicle,
    find_corridor_by_incident,
    get_active_corridors,
    get_corridor_history,
    get_corridor_statistics,
    create_sample_corridor
)

# ============================================
# DATABASE INITIALIZATION FUNCTION
# ============================================

def init_db(app):
    """
    Initialize database with all models
    Call this function when creating the Flask app
    """
    from app.extensions import db
    
    # Create all tables
    db.create_all()
    
    # Create default admin user
    create_default_admin()
    
    # Create sample data for development
    if app.config.get('ENVIRONMENT') == 'development':
        create_sample_vehicles()
        create_sample_signals()
        create_sample_incident()
        create_sample_corridor()
    
    return db


def reset_db(app):
    """
    Reset database - Drop all tables and recreate
    USE ONLY FOR DEVELOPMENT/TESTING
    """
    from app.extensions import db
    
    # Drop all tables
    db.drop_all()
    
    # Recreate all tables
    db.create_all()
    
    # Create default admin
    create_default_admin()
    
    # Create sample data
    if app.config.get('ENVIRONMENT') == 'development':
        create_sample_vehicles()
        create_sample_signals()
        create_sample_incident()
        create_sample_corridor()
    
    return db


# ============================================
# HELPER FUNCTIONS FOR MODELS
# ============================================

def get_model_by_name(model_name):
    """
    Get model class by string name
    Useful for dynamic imports
    """
    models = {
        'User': User,
        'EmergencyVehicle': EmergencyVehicle,
        'TrafficSignal': TrafficSignal,
        'Incident': Incident,
        'GreenCorridor': GreenCorridor,
        'TokenBlocklist': TokenBlocklist,
        'UserSession': UserSession,
        'UserInvitation': UserInvitation,
        'VehicleLocationHistory': VehicleLocationHistory,
        'SignalLog': SignalLog,
        'IncidentAlert': IncidentAlert
    }
    return models.get(model_name)


def get_all_model_names():
    """Get list of all model names"""
    return [
        'User',
        'EmergencyVehicle',
        'TrafficSignal',
        'Incident',
        'GreenCorridor',
        'TokenBlocklist',
        'UserSession',
        'UserInvitation',
        'VehicleLocationHistory',
        'SignalLog',
        'IncidentAlert'
    ]


def get_model_count():
    """Get count of records in each model"""
    from app.extensions import db
    
    counts = {}
    model_names = get_all_model_names()
    
    for name in model_names:
        model = get_model_by_name(name)
        if model:
            counts[name] = db.session.query(model).count()
    
    return counts


# ============================================
# DATABASE STATISTICS FUNCTION
# ============================================

def get_database_stats():
    from app.extensions import db
    """
    Get comprehensive database statistics
    Useful for admin dashboard
    """
    stats = {
        'users': {
            'total': db.session.query(User).count(),
            'active': db.session.query(User).filter(User.status == UserStatus.ACTIVE).count(),
            'by_role': {}
        },
        'vehicles': {
            'total': db.session.query(EmergencyVehicle).count(),
            'available': db.session.query(EmergencyVehicle).filter(EmergencyVehicle.status == VehicleStatus.AVAILABLE).count(),
            'on_duty': db.session.query(EmergencyVehicle).filter(EmergencyVehicle.status == VehicleStatus.ON_DUTY).count(),
            'by_type': {}
        },
        'signals': {
            'total': db.session.query(TrafficSignal).count(),
            'active_corridors': db.session.query(TrafficSignal).filter(TrafficSignal.current_status == SignalStatus.GREEN_CORRIDOR).count(),
            'online': db.session.query(TrafficSignal).filter(TrafficSignal.is_online == True).count()
        },
        'incidents': {
            'total': db.session.query(Incident).count(),
            'active': len(get_active_incidents()),
            'resolved_today': 0
        },
        'corridors': {
            'total': db.session.query(GreenCorridor).count(),
            'active': len(get_active_corridors()),
            'completed': db.session.query(GreenCorridor).filter(GreenCorridor.status == CorridorStatus.COMPLETED).count()
        }
    }
    
    # Get user counts by role
    for role in UserRole:
        count = db.session.query(User).filter(User.role == role).count()
        if count > 0:
            stats['users']['by_role'][role.value] = count
    
    # Get vehicle counts by type
    for vtype in VehicleType:
        count = db.session.query(EmergencyVehicle).filter(EmergencyVehicle.vehicle_type == vtype).count()
        if count > 0:
            stats['vehicles']['by_type'][vtype.value] = count
    
    # Get incidents resolved today
    today_start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    stats['incidents']['resolved_today'] = db.session.query(Incident).filter(
        Incident.resolved_at >= today_start
    ).count()
    
    return stats


# ============================================
# DATABASE BACKUP/RESTORE FUNCTIONS
# ============================================

def export_to_json():
    """
    Export all database data to JSON
    Useful for backup or migration
    """
    import json
    
    data = {
        'users': [user.to_dict(include_sensitive=False) for user in User.query.all()],
        'vehicles': [vehicle.to_dict() for vehicle in EmergencyVehicle.query.all()],
        'signals': [signal.to_dict() for signal in TrafficSignal.query.all()],
        'incidents': [incident.to_dict() for incident in Incident.query.all()],
        'corridors': [corridor.to_dict() for corridor in GreenCorridor.query.all()]
    }
    
    return json.dumps(data, indent=2, default=str)


def import_from_json(json_data):
    """
    Import data from JSON backup
    USE WITH CAUTION - This will add/update records
    """
    import json
    from app.extensions import db
    
    data = json.loads(json_data)
    
    # Import users
    for user_data in data.get('users', []):
        existing = find_user_by_email(user_data['email'])
        if not existing:
            user = User(
                email=user_data['email'],
                username=user_data['username'],
                full_name=user_data['full_name'],
                password='Temp@123'  # Reset password needed
            )
            db.session.add(user)
    
    db.session.commit()
    return True


# ============================================
# EXPORTS - Sab kuch ek jagah se import karne ke liye
# ============================================

__all__ = [
    # User Models
    'User',
    'UserRole',
    'UserStatus',
    'TokenBlocklist',
    'UserSession',
    'UserInvitation',
    'find_user_by_email',
    'find_user_by_username',
    'find_user_by_id',
    'get_all_active_users',
    'get_users_by_role',
    'create_default_admin',
    
    # Vehicle Models
    'EmergencyVehicle',
    'VehicleType',
    'VehicleStatus',
    'VehicleEmergencyLevel',
    'VehicleEquipmentStatus',
    'VehicleLocationHistory',
    'find_vehicle_by_id',
    'find_vehicle_by_registration',
    'find_vehicle_by_uuid',
    'get_all_emergency_vehicles',
    'get_available_vehicles',
    'get_nearest_vehicle',
    'create_sample_vehicles',
    
    # Traffic Signal Models
    'TrafficSignal',
    'SignalStatus',
    'SignalDirection',
    'LaneType',
    'TrafficDensity',
    'SignalLog',
    'find_signal_by_id',
    'find_signal_by_intersection_id',
    'find_signal_by_uuid',
    'get_all_signals',
    'get_signals_on_route',
    'get_next_signal_on_path',
    'create_sample_signals',
    
    # Incident Models
    'Incident',
    'IncidentType',
    'IncidentSeverity',
    'IncidentStatus',
    'PatientCondition',
    'IncidentAlert',
    'find_incident_by_id',
    'find_incident_by_uuid',
    'get_active_incidents',
    'get_incidents_by_status',
    'get_nearby_incidents',
    'get_incident_statistics',
    'create_sample_incident',
    
    # Corridor Models
    'GreenCorridor',
    'CorridorStatus',
    'CorridorType',
    'PathCalculationMethod',
    'find_corridor_by_id',
    'find_corridor_by_uuid',
    'find_corridor_by_vehicle',
    'find_corridor_by_incident',
    'get_active_corridors',
    'get_corridor_history',
    'get_corridor_statistics',
    'create_sample_corridor',
    
    # Database Functions
    'init_db',
    'reset_db',
    'get_model_by_name',
    'get_all_model_names',
    'get_model_count',
    'get_database_stats',
    'export_to_json',
    'import_from_json'
]