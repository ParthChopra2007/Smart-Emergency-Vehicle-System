"""
Smart Emergency Vehicle Priority System - Flask Application Factory
This file initializes the Flask app, extensions, blueprints, and SocketIO
"""

import os
from flask import Flask, jsonify, request
from flask_cors import CORS
from flask_socketio import SocketIO
from loguru import logger
from datetime import datetime
import sys

# Configure logger to write to both console and file
logger.remove()  # Remove default handler
logger.add(
    sys.stdout,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <cyan>{name}</cyan>:<cyan>{function}</cyan> - <level>{message}</level>",
    level="INFO"
)
logger.add(
    "logs/sevps_{time:YYYY-MM-DD}.log",
    rotation="1 day",
    retention="30 days",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function} - {message}",
    level="DEBUG"
)

# Initialize SocketIO globally
socketio = SocketIO(cors_allowed_origins="*", async_mode='threading')

def create_app(config_object=None):
    """
    Application factory function
    Creates and configures the Flask application instance
    """
    app = Flask(
        __name__,
        template_folder='templates',
        static_folder='static'
    )
    
    # Load configuration
    if config_object:
        app.config.from_object(config_object)
    else:
        from app.config import Config
        app.config.from_object(Config)
    
    # Ensure logs directory exists
    os.makedirs('logs', exist_ok=True)
    
    # Initialize extensions
    initialize_extensions(app)
    
    # Register blueprints (routes)
    register_blueprints(app)
    
    # Register SocketIO events
    register_socket_events()
    
    # Register error handlers
    register_error_handlers(app)
    
    # Register before/after request handlers
    register_request_handlers(app)
    
    logger.info("🚑 Smart Emergency Vehicle Priority System initialized successfully")
    logger.info(f"📍 Environment: {app.config.get('ENVIRONMENT', 'development')}")
    logger.info(f"🗄️  Database: {app.config.get('SQLALCHEMY_DATABASE_URI', 'Not configured')}")
    
    return app

def initialize_extensions(app):
    """
    Initialize all Flask extensions
    """
    # CORS - Allow frontend to communicate with backend
    CORS(app, resources={
        r"/api/*": {"origins": "*"},
        r"/socket.io/*": {"origins": "*"}
    })
    
    # Database (will be initialized when we create models)
    from app.extensions import db, migrate, bcrypt, jwt, cors
    db.init_app(app)
    migrate.init_app(app, db)
    bcrypt.init_app(app)
    jwt.init_app(app)
    
    # Store extensions in app config for easy access
    app.extensions['db'] = db
    app.extensions['bcrypt'] = bcrypt
    app.extensions['jwt'] = jwt
    
    # Initialize SocketIO
    socketio.init_app(app, cors_allowed_origins="*")
    
    logger.info("✅ All extensions initialized successfully")

def register_blueprints(app):
    """
    Register all route blueprints (API endpoints)
    """
    from app.routes.auth_routes import auth_bp
    from app.routes.vehicle_routes import vehicle_bp
    from app.routes.traffic_routes import traffic_bp
    from app.routes.corridor_routes import corridor_bp
    from app.routes.dashboard_routes import dashboard_bp
    from app.routes.admin_routes import admin_bp
    
    # Register blueprints with URL prefixes
    app.register_blueprint(auth_bp, url_prefix='/api/v1/auth')
    app.register_blueprint(vehicle_bp, url_prefix='/api/v1/vehicles')
    app.register_blueprint(traffic_bp, url_prefix='/api/v1/traffic')
    app.register_blueprint(corridor_bp, url_prefix='/api/v1/corridor')
    app.register_blueprint(dashboard_bp, url_prefix='/api/v1/dashboard')
    app.register_blueprint(admin_bp, url_prefix='/api/v1/admin')
    
    # Root route for health check
    @app.route('/health', methods=['GET'])
    def health_check():
        return jsonify({
            'status': 'healthy',
            'timestamp': datetime.now().isoformat(),
            'version': '1.0.0',
            'service': 'Smart Emergency Vehicle Priority System'
        }), 200
    
    @app.route('/', methods=['GET'])
    def home():
        return jsonify({
            'message': 'Welcome to Smart Emergency Vehicle Priority System API',
            'docs': '/api/v1/docs',
            'health': '/health',
            'version': '1.0.0'
        }), 200
    
    logger.info(f"✅ Registered {len(app.blueprints)} blueprints")

def register_socket_events():
    """
    Register WebSocket event handlers
    """
    from app.socket_events.live_tracking import register_tracking_events
    from app.socket_events.signal_updates import register_signal_events
    
    register_tracking_events(socketio)
    register_signal_events(socketio)
    
    logger.info("✅ SocketIO events registered successfully")

def register_error_handlers(app):
    """
    Register global error handlers
    """
    @app.errorhandler(400)
    def bad_request(error):
        logger.warning(f"Bad request: {error}")
        return jsonify({
            'error': 'Bad Request',
            'message': str(error.description) if hasattr(error, 'description') else 'Invalid request',
            'status_code': 400
        }), 400
    
    @app.errorhandler(401)
    def unauthorized(error):
        logger.warning(f"Unauthorized access: {error}")
        return jsonify({
            'error': 'Unauthorized',
            'message': 'Authentication required',
            'status_code': 401
        }), 401
    
    @app.errorhandler(403)
    def forbidden(error):
        logger.warning(f"Forbidden access: {error}")
        return jsonify({
            'error': 'Forbidden',
            'message': 'You don\'t have permission to access this resource',
            'status_code': 403
        }), 403
    
    @app.errorhandler(404)
    def not_found(error):
        logger.warning(f"Route not found: {request.url}")
        return jsonify({
            'error': 'Not Found',
            'message': 'The requested resource was not found',
            'status_code': 404
        }), 404
    
    @app.errorhandler(500)
    def internal_server_error(error):
        logger.error(f"Internal server error: {error}")
        return jsonify({
            'error': 'Internal Server Error',
            'message': 'Something went wrong on our end',
            'status_code': 500
        }), 500
    
    logger.info("✅ Error handlers registered")

def register_request_handlers(app):
    """
    Register before_request and after_request handlers
    """
    @app.before_request
    def before_request():
        """Log all incoming requests"""
        logger.debug(f"📥 {request.method} {request.path} - IP: {request.remote_addr}")
        
        # Skip logging for health check
        if request.path != '/health':
            # Log request body for POST/PUT requests (except large files)
            if request.method in ['POST', 'PUT'] and request.is_json:
                logger.debug(f"📦 Request body: {request.get_json()}")
    
    @app.after_request
    def after_request(response):
        """Add security headers to all responses"""
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Server'] = 'SEVPS/1.0'
        
        logger.debug(f"📤 {request.method} {request.path} - Status: {response.status_code}")
        return response
    
    logger.info("✅ Request handlers registered")

# This will be imported by run.py
__all__ = ['create_app', 'socketio']