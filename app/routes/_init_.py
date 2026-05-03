"""
Smart Emergency Vehicle Priority System - Routes Package
This file initializes all route blueprints and exports them for use in the main app
"""

from flask import Blueprint, jsonify, request
from loguru import logger
from datetime import datetime

# ============================================
# IMPORT ALL BLUEPRINTS
# ============================================
# These will be created in separate files
from app.routes.auth_routes import auth_bp
from app.routes.vehicle_routes import vehicle_bp
from app.routes.traffic_routes import traffic_bp
from app.routes.corridor_routes import corridor_bp
from app.routes.dashboard_routes import dashboard_bp
from app.routes.admin_routes import admin_bp

# ============================================
# CREATE ADDITIONAL UTILITY BLUEPRINTS
# ============================================

# Health check blueprint (for monitoring)
health_bp = Blueprint('health', __name__)

@health_bp.route('/health', methods=['GET'])
def health_check():
    """Basic health check endpoint for load balancers and monitoring"""
    return jsonify({
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'service': 'SEVPS-API',
        'version': '1.0.0'
    }), 200

@health_bp.route('/health/detailed', methods=['GET'])
def detailed_health_check():
    """
    Detailed health check with database, redis, and service status
    Useful for debugging and monitoring
    """
    health_status = {
        'status': 'healthy',
        'timestamp': datetime.utcnow().isoformat(),
        'version': '1.0.0',
        'components': {}
    }
    
    # Check database connection
    try:
        from app.extensions import db
        db.session.execute('SELECT 1')
        health_status['components']['database'] = {'status': 'up', 'message': 'Connected'}
    except Exception as e:
        health_status['components']['database'] = {'status': 'down', 'message': str(e)}
        health_status['status'] = 'degraded'
    
    # Check Redis connection (if configured)
    try:
        from app.extensions import get_redis
        redis_client = get_redis()
        if redis_client:
            redis_client.ping()
            health_status['components']['redis'] = {'status': 'up', 'message': 'Connected'}
        else:
            health_status['components']['redis'] = {'status': 'down', 'message': 'Not configured'}
    except Exception as e:
        health_status['components']['redis'] = {'status': 'down', 'message': str(e)}
        health_status['status'] = 'degraded'
    
    # Check MQTT connection (if configured)
    try:
        from app.extensions import get_mqtt
        mqtt_client = get_mqtt()
        if mqtt_client:
            health_status['components']['mqtt'] = {'status': 'up', 'message': 'Connected'}
        else:
            health_status['components']['mqtt'] = {'status': 'unknown', 'message': 'Not configured'}
    except Exception as e:
        health_status['components']['mqtt'] = {'status': 'down', 'message': str(e)}
    
    # Return appropriate HTTP status code
    status_code = 200 if health_status['status'] == 'healthy' else 503
    return jsonify(health_status), status_code


# API Documentation blueprint
docs_bp = Blueprint('docs', __name__, url_prefix='/api/v1/docs')

@docs_bp.route('/', methods=['GET'])
def api_documentation():
    """Simple API documentation endpoint"""
    return jsonify({
        'name': 'Smart Emergency Vehicle Priority System API',
        'version': '1.0.0',
        'base_url': '/api/v1',
        'endpoints': {
            'Authentication': {
                'POST /auth/register': 'Register new user',
                'POST /auth/login': 'Login user',
                'POST /auth/logout': 'Logout user',
                'POST /auth/refresh': 'Refresh JWT token',
                'GET /auth/me': 'Get current user info'
            },
            'Vehicles': {
                'GET /vehicles/list': 'Get all emergency vehicles',
                'GET /vehicles/live': 'Get live vehicle locations',
                'POST /vehicles/register': 'Register new emergency vehicle',
                'PUT /vehicles/<id>/location': 'Update vehicle location',
                'GET /vehicles/<id>/status': 'Get vehicle status'
            },
            'Traffic Signals': {
                'GET /traffic/signals': 'Get all traffic signals',
                'GET /traffic/signals/<id>': 'Get specific signal',
                'PUT /traffic/signals/<id>/control': 'Control signal manually',
                'GET /traffic/density': 'Get traffic density data'
            },
            'Green Corridor': {
                'POST /corridor/request': 'Request green corridor',
                'GET /corridor/active': 'Get active corridors',
                'DELETE /corridor/<id>/cancel': 'Cancel active corridor',
                'GET /corridor/history': 'Get corridor history'
            },
            'Dashboard': {
                'GET /dashboard/stats': 'Get dashboard statistics',
                'GET /dashboard/realtime': 'Get real-time data',
                'GET /dashboard/alerts': 'Get active alerts'
            },
            'Admin': {
                'GET /admin/users': 'List all users',
                'PUT /admin/users/<id>/role': 'Update user role',
                'DELETE /admin/users/<id>': 'Delete user',
                'GET /admin/system/logs': 'View system logs'
            }
        },
        'authentication': 'Bearer token required for all endpoints except /auth/*',
        'websocket_events': {
            'connect': 'Connect to WebSocket',
            'vehicle_location': 'Receive real-time vehicle locations',
            'signal_update': 'Receive traffic signal updates',
            'corridor_created': 'Receive corridor creation alerts'
        }
    }), 200


# ============================================
# LIST OF ALL BLUEPRINTS TO REGISTER
# ============================================
# This list will be used in create_app() to register all routes
blueprints = [
    (health_bp, None),                    # Health check endpoints
    (docs_bp, None),                      # API documentation
    (auth_bp, '/api/v1/auth'),           # Authentication routes
    (vehicle_bp, '/api/v1/vehicles'),    # Vehicle management
    (traffic_bp, '/api/v1/traffic'),     # Traffic signal control
    (corridor_bp, '/api/v1/corridor'),   # Green corridor management
    (dashboard_bp, '/api/v1/dashboard'), # Dashboard data
    (admin_bp, '/api/v1/admin')          # Admin operations
]

# ============================================
# REGISTRATION HELPER FUNCTION
# ============================================
def register_blueprints(app):
    """
    Register all blueprints with the Flask app
    This function is called from app/__init__.py
    """
    for blueprint, url_prefix in blueprints:
        if url_prefix:
            app.register_blueprint(blueprint, url_prefix=url_prefix)
        else:
            app.register_blueprint(blueprint)
        logger.info(f"✅ Registered blueprint: {blueprint.name} at {url_prefix or '/'}")
    
    logger.info(f"🎯 Total {len(blueprints)} blueprints registered successfully")
    
    # Print all registered routes for debugging
    if app.debug:
        print("\n" + "="*60)
        print("📋 REGISTERED API ENDPOINTS")
        print("="*60)
        for rule in app.url_map.iter_rules():
            methods = ','.join(sorted(rule.methods - {'HEAD', 'OPTIONS'}))
            print(f"{methods:10} {rule}")
        print("="*60 + "\n")

# ============================================
# ERROR HANDLERS FOR BLUEPRINTS
# ============================================
def register_blueprint_error_handlers(bp):
    """
    Register error handlers for a specific blueprint
    Can be used for blueprint-specific error handling
    """
    
    @bp.errorhandler(400)
    def bad_request(error):
        return jsonify({
            'error': 'Bad Request',
            'message': 'Invalid request parameters',
            'status_code': 400
        }), 400
    
    @bp.errorhandler(401)
    def unauthorized(error):
        return jsonify({
            'error': 'Unauthorized',
            'message': 'Authentication required',
            'status_code': 401
        }), 401
    
    @bp.errorhandler(403)
    def forbidden(error):
        return jsonify({
            'error': 'Forbidden',
            'message': 'You do not have permission',
            'status_code': 403
        }), 403
    
    @bp.errorhandler(404)
    def not_found(error):
        return jsonify({
            'error': 'Not Found',
            'message': 'Resource not found',
            'status_code': 404
        }), 404
    
    @bp.errorhandler(429)
    def rate_limit_exceeded(error):
        return jsonify({
            'error': 'Rate Limit Exceeded',
            'message': 'Too many requests. Please try again later.',
            'status_code': 429
        }), 429
    
    @bp.errorhandler(500)
    def internal_error(error):
        logger.error(f"Blueprint {bp.name} error: {error}")
        return jsonify({
            'error': 'Internal Server Error',
            'message': 'Something went wrong',
            'status_code': 500
        }), 500
    
    return bp

# ============================================
# REQUEST HOOKS FOR BLUEPRINTS
# ============================================
def register_blueprint_hooks(bp):
    """
    Register before_request and after_request hooks for a blueprint
    """
    
    @bp.before_request
    def before_request():
        """Log all requests to this blueprint"""
        logger.debug(f"📥 [{bp.name}] {request.method} {request.path}")
        
        # Skip authentication for public endpoints
        public_endpoints = ['/auth/login', '/auth/register', '/health']
        if request.path in public_endpoints:
            return None
        
        # Authentication will be handled by JWT decorators in individual routes
        return None
    
    @bp.after_request
    def after_request(response):
        """Add blueprint-specific headers"""
        response.headers['X-API-Version'] = '1.0.0'
        response.headers['X-Blueprint'] = bp.name
        return response
    
    return bp

# ============================================
# VERSIONING SUPPORT
# ============================================
class APIVersion:
    """Simple API version management"""
    
    CURRENT_VERSION = 'v1'
    SUPPORTED_VERSIONS = ['v1']
    DEPRECATED_VERSIONS = []
    
    @classmethod
    def get_version_from_headers(cls):
        """Extract API version from request headers"""
        return request.headers.get('API-Version', cls.CURRENT_VERSION)
    
    @classmethod
    def is_version_supported(cls, version):
        """Check if API version is supported"""
        return version in cls.SUPPORTED_VERSIONS
    
    @classmethod
    def is_version_deprecated(cls, version):
        """Check if API version is deprecated"""
        return version in cls.DEPRECATED_VERSIONS

# ============================================
# RATE LIMIT CONFIGURATION PER BLUEPRINT
# ============================================
# Different rate limits for different types of endpoints
RATE_LIMITS = {
    'auth': '10 per minute',      # Login/Register limits
    'vehicle': '60 per minute',    # Vehicle updates frequent
    'corridor': '30 per minute',   # Corridor requests
    'dashboard': '120 per minute', # Dashboard frequent polling
    'admin': '20 per minute'       # Admin operations
}

# ============================================
# EXPORTS
# ============================================
__all__ = [
    'auth_bp',
    'vehicle_bp', 
    'traffic_bp',
    'corridor_bp',
    'dashboard_bp',
    'admin_bp',
    'health_bp',
    'docs_bp',
    'blueprints',
    'register_blueprints',
    'register_blueprint_error_handlers',
    'register_blueprint_hooks',
    'APIVersion',
    'RATE_LIMITS'
]

# ============================================
# INITIALIZATION LOG
# ============================================
logger.info("📦 Routes package initialized")
logger.info(f"   - {len(blueprints)} blueprints ready for registration")
logger.info(f"   - API Version: {APIVersion.CURRENT_VERSION}")
logger.info(f"   - Supported versions: {APIVersion.SUPPORTED_VERSIONS}")