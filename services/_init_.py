"""
Smart Emergency Vehicle Priority System - Services Package
This file initializes all business logic services and exports them for use
"""

from loguru import logger

# ============================================
# IMPORT ALL SERVICES
# ============================================

# AI & Detection Services
from app.services.ai_detection import (
    VehicleDetectionService,
    EmergencyVehicleDetector,
    TrafficFlowAnalyzer,
    LicensePlateRecognizer,
    get_ai_service
)

# Traffic Intelligence Services
from app.services.traffic_intel import (
    TrafficPredictor,
    TrafficOptimizer,
    CongestionAnalyzer,
    RouteOptimizer,
    get_traffic_intel_service
)

# Green Corridor Services
from app.services.corridor_generator import (
    CorridorGenerator,
    PathCalculator,
    SignalCoordinator,
    ETACalculator,
    get_corridor_service
)

# Blockchain Services
from app.services.blockchain_service import (
    BlockchainService,
    AuditRecorder,
    SmartContractManager,
    VerificationService,
    get_blockchain_service
)

# IoT Services
from app.services.iot_service import (
    IoTService,
    MQTTManager,
    SignalController,
    VehicleTracker,
    SensorDataProcessor,
    get_iot_service
)

# Notification Services
from app.services.notification_service import (
    NotificationService,
    EmailNotifier,
    SMSNotifier,
    PushNotifier,
    AlertManager,
    get_notification_service
)

# GPS Tracking Services
from app.services.gps_tracker import (
    GPSTracker,
    LocationService,
    GeofenceManager,
    RouteTrackingService,
    get_gps_service
)

# ============================================
# SERVICE INITIALIZATION FUNCTION
# ============================================

_services = {}


def init_services(app):
    """
    Initialize all services with the Flask app
    Call this function inside create_app() after extensions are initialized
    """
    global _services
    
    try:
        # Initialize AI Service
        _services['ai'] = get_ai_service(app)
        logger.info("✅ AI Service initialized")
    except Exception as e:
        logger.error(f"Failed to initialize AI Service: {e}")
        _services['ai'] = None
    
    try:
        # Initialize Traffic Intelligence Service
        _services['traffic_intel'] = get_traffic_intel_service(app)
        logger.info("✅ Traffic Intelligence Service initialized")
    except Exception as e:
        logger.error(f"Failed to initialize Traffic Intelligence Service: {e}")
        _services['traffic_intel'] = None
    
    try:
        # Initialize Corridor Service
        _services['corridor'] = get_corridor_service(app)
        logger.info("✅ Corridor Service initialized")
    except Exception as e:
        logger.error(f"Failed to initialize Corridor Service: {e}")
        _services['corridor'] = None
    
    try:
        # Initialize Blockchain Service
        _services['blockchain'] = get_blockchain_service(app)
        logger.info("✅ Blockchain Service initialized")
    except Exception as e:
        logger.error(f"Failed to initialize Blockchain Service: {e}")
        _services['blockchain'] = None
    
    try:
        # Initialize IoT Service
        _services['iot'] = get_iot_service(app)
        logger.info("✅ IoT Service initialized")
    except Exception as e:
        logger.error(f"Failed to initialize IoT Service: {e}")
        _services['iot'] = None
    
    try:
        # Initialize Notification Service
        _services['notification'] = get_notification_service(app)
        logger.info("✅ Notification Service initialized")
    except Exception as e:
        logger.error(f"Failed to initialize Notification Service: {e}")
        _services['notification'] = None
    
    try:
        # Initialize GPS Service
        _services['gps'] = get_gps_service(app)
        logger.info("✅ GPS Service initialized")
    except Exception as e:
        logger.error(f"Failed to initialize GPS Service: {e}")
        _services['gps'] = None
    
    logger.info(f"🎯 Services initialized: {len([s for s in _services.values() if s])} active")
    
    return _services


def get_service(service_name):
    """
    Get a specific service by name
    Usage: get_service('ai') or get_service('corridor')
    """
    return _services.get(service_name)


def get_all_services():
    """Get all initialized services"""
    return {k: v for k, v in _services.items() if v is not None}


def shutdown_services():
    """
    Gracefully shutdown all services
    Call this when application is shutting down
    """
    logger.info("Shutting down services...")
    
    for service_name, service in _services.items():
        if service and hasattr(service, 'shutdown'):
            try:
                service.shutdown()
                logger.info(f"✅ {service_name} service shut down")
            except Exception as e:
                logger.error(f"Error shutting down {service_name}: {e}")
    
    logger.info("All services shut down")


# ============================================
# SERVICE STATUS FUNCTIONS
# ============================================

def get_service_status():
    """Get status of all services"""
    status = {
        'ai': {
            'initialized': _services.get('ai') is not None,
            'status': 'healthy' if _services.get('ai') else 'unavailable'
        },
        'traffic_intel': {
            'initialized': _services.get('traffic_intel') is not None,
            'status': 'healthy' if _services.get('traffic_intel') else 'unavailable'
        },
        'corridor': {
            'initialized': _services.get('corridor') is not None,
            'status': 'healthy' if _services.get('corridor') else 'unavailable'
        },
        'blockchain': {
            'initialized': _services.get('blockchain') is not None,
            'status': 'healthy' if _services.get('blockchain') else 'unavailable'
        },
        'iot': {
            'initialized': _services.get('iot') is not None,
            'status': 'healthy' if _services.get('iot') else 'unavailable'
        },
        'notification': {
            'initialized': _services.get('notification') is not None,
            'status': 'healthy' if _services.get('notification') else 'unavailable'
        },
        'gps': {
            'initialized': _services.get('gps') is not None,
            'status': 'healthy' if _services.get('gps') else 'unavailable'
        }
    }
    
    # Get detailed status from each service if available
    for service_name, service in _services.items():
        if service and hasattr(service, 'get_status'):
            try:
                status[service_name]['details'] = service.get_status()
            except:
                pass
    
    return status


def check_service_health(service_name):
    """
    Check health of a specific service
    Returns True if service is healthy, False otherwise
    """
    service = _services.get(service_name)
    if not service:
        return False
    
    if hasattr(service, 'health_check'):
        try:
            return service.health_check()
        except:
            return False
    
    return True


# ============================================
# SERVICE DEPENDENCY MANAGEMENT
# ============================================

_service_dependencies = {
    'corridor': ['traffic_intel', 'gps'],
    'notification': ['ai'],
    'blockchain': ['notification'],
    'iot': ['notification']
}


def get_service_dependencies(service_name):
    """Get list of dependencies for a service"""
    return _service_dependencies.get(service_name, [])


def is_service_ready(service_name):
    """
    Check if a service and its dependencies are ready
    """
    dependencies = get_service_dependencies(service_name)
    
    for dep in dependencies:
        if not check_service_health(dep):
            return False
    
    return check_service_health(service_name)


# ============================================
# HELPER FUNCTIONS FOR SERVICES
# ============================================

def run_background_tasks():
    """
    Run background tasks for all services
    This can be called from a Celery beat schedule
    """
    results = {}
    
    # Run AI predictions
    if _services.get('ai'):
        try:
            results['ai'] = _services['ai'].run_prediction()
        except Exception as e:
            logger.error(f"AI prediction failed: {e}")
            results['ai'] = None
    
    # Update traffic predictions
    if _services.get('traffic_intel'):
        try:
            results['traffic_intel'] = _services['traffic_intel'].update_predictions()
        except Exception as e:
            logger.error(f"Traffic intel update failed: {e}")
            results['traffic_intel'] = None
    
    # Sync blockchain
    if _services.get('blockchain'):
        try:
            results['blockchain'] = _services['blockchain'].sync()
        except Exception as e:
            logger.error(f"Blockchain sync failed: {e}")
            results['blockchain'] = None
    
    # Process IoT heartbeats
    if _services.get('iot'):
        try:
            results['iot'] = _services['iot'].process_heartbeats()
        except Exception as e:
            logger.error(f"IoT heartbeat processing failed: {e}")
            results['iot'] = None
    
    return results


# ============================================
# SERVICE CONFIGURATION
# ============================================

def configure_services(app):
    """
    Configure all services with app configuration
    """
    config = app.config
    
    # Configure AI service
    if _services.get('ai'):
        _services['ai'].configure({
            'model_path': config.get('AI_MODEL_PATH'),
            'confidence_threshold': config.get('VEHICLE_DETECTION_CONFIDENCE', 0.5),
            'device': 'cuda' if config.get('DEBUG') else 'cpu'
        })
    
    # Configure Corridor service
    if _services.get('corridor'):
        _services['corridor'].configure({
            'pre_time_seconds': config.get('GREEN_CORRIDOR_PRE_TIME', 15),
            'post_time_seconds': config.get('GREEN_CORRIDOR_POST_TIME', 5),
            'max_distance_km': config.get('MAX_CORRIDOR_DISTANCE_KM', 10)
        })
    
    # Configure Notification service
    if _services.get('notification'):
        _services['notification'].configure({
            'mail_server': config.get('MAIL_SERVER'),
            'mail_port': config.get('MAIL_PORT'),
            'mail_username': config.get('MAIL_USERNAME'),
            'twilio_sid': config.get('TWILIO_ACCOUNT_SID')
        })
    
    logger.info("Services configured with app settings")
    return True


# ============================================
# EXPORTS - All services available from one place
# ============================================

__all__ = [
    # AI Services
    'VehicleDetectionService',
    'EmergencyVehicleDetector',
    'TrafficFlowAnalyzer',
    'LicensePlateRecognizer',
    'get_ai_service',
    
    # Traffic Intelligence
    'TrafficPredictor',
    'TrafficOptimizer',
    'CongestionAnalyzer',
    'RouteOptimizer',
    'get_traffic_intel_service',
    
    # Corridor Services
    'CorridorGenerator',
    'PathCalculator',
    'SignalCoordinator',
    'ETACalculator',
    'get_corridor_service',
    
    # Blockchain Services
    'BlockchainService',
    'AuditRecorder',
    'SmartContractManager',
    'VerificationService',
    'get_blockchain_service',
    
    # IoT Services
    'IoTService',
    'MQTTManager',
    'SignalController',
    'VehicleTracker',
    'SensorDataProcessor',
    'get_iot_service',
    
    # Notification Services
    'NotificationService',
    'EmailNotifier',
    'SMSNotifier',
    'PushNotifier',
    'AlertManager',
    'get_notification_service',
    
    # GPS Services
    'GPSTracker',
    'LocationService',
    'GeofenceManager',
    'RouteTrackingService',
    'get_gps_service',
    
    # Service Management
    'init_services',
    'get_service',
    'get_all_services',
    'shutdown_services',
    'get_service_status',
    'check_service_health',
    'get_service_dependencies',
    'is_service_ready',
    'run_background_tasks',
    'configure_services'
]

# ============================================
# INITIALIZATION LOG
# ============================================

logger.info("📦 Services package initialized")
logger.info("   Available services: AI, TrafficIntel, Corridor, Blockchain, IoT, Notification, GPS")