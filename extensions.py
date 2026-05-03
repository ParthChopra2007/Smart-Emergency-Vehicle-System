"""
Smart Emergency Vehicle Priority System - Flask Extensions
This file initializes all Flask extensions that are used across the application
"""

from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager
from flask_caching import Cache
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_mail import Mail
from flask_socketio import SocketIO
from celery import Celery
from redis import Redis
from loguru import logger
import redis

# ============================================
# DATABASE EXTENSIONS
# ============================================
# SQLAlchemy for ORM (Object Relational Mapping)
db = SQLAlchemy()

# Migrate for database schema migrations (like git for database)
migrate = Migrate()

# ============================================
# SECURITY EXTENSIONS
# ============================================
# Bcrypt for password hashing (security)
bcrypt = Bcrypt()

# JWT Manager for authentication tokens
jwt = JWTManager()

# ============================================
# CACHING & RATE LIMITING
# ============================================
# Cache for storing frequently accessed data
cache = Cache()

# Rate limiter to prevent API abuse
limiter = Limiter(
    key_func=get_remote_address,  # Track requests by IP address
    default_limits=["100 per minute"],  # Default limit per IP
    storage_uri="memory://"  # Use memory for rate limiting (will be overridden by Redis in production)
)

# ============================================
# EMAIL EXTENSION
# ============================================
# Mail for sending email alerts
mail = Mail()

# ============================================
# WEBSOCKET EXTENSION (Real-time Communication)
# ============================================
# SocketIO for real-time vehicle tracking and signal updates
socketio = SocketIO(cors_allowed_origins="*")

# ============================================
# TASK QUEUE (Celery for background tasks)
# ============================================
def make_celery(app=None):
    """
    Create Celery instance for background tasks
    Tasks like: traffic prediction, sending emails, blockchain transactions
    """
    celery = Celery(
        app.import_name if app else __name__,
        backend=app.config['CELERY_RESULT_BACKEND'] if app else 'redis://localhost:6379/0',
        broker=app.config['CELERY_BROKER_URL'] if app else 'redis://localhost:6379/0'
    )
    
    if app:
        # Update Celery config from Flask app
        celery.conf.update(app.config)
        
        # Task routes for different queues
        celery.conf.task_routes = {
            'app.services.ai_detection.*': {'queue': 'ai_queue'},
            'app.services.traffic_intel.*': {'queue': 'traffic_queue'},
            'app.services.blockchain_service.*': {'queue': 'blockchain_queue'},
            'app.services.notification_service.*': {'queue': 'notification_queue'}
        }
        
        # Task time limits
        celery.conf.task_time_limit = 300  # 5 minutes
        celery.conf.task_soft_time_limit = 240  # 4 minutes
        
        # Task result expiration
        celery.conf.result_expires = 3600  # 1 hour
    
    return celery

# Create Celery instance (will be initialized with app later)
celery = None

# ============================================
# REDIS CLIENT (For caching and real-time data)
# ============================================
redis_client = None

def init_redis(app):
    """Initialize Redis client for caching and real-time operations"""
    global redis_client
    try:
        redis_client = redis.from_url(
            app.config['REDIS_URL'],
            decode_responses=True,
            socket_connect_timeout=5,
            socket_timeout=5
        )
        # Test connection
        redis_client.ping()
        logger.info("✅ Redis connection established successfully")
        
        # Store vehicle locations in Redis for real-time access
        # Format: "vehicle:{vehicle_id}:location" -> "lat,lng,timestamp"
        
        # Store active corridors
        # Format: "corridor:{corridor_id}" -> JSON data
        
        return redis_client
    except Exception as e:
        logger.error(f"❌ Redis connection failed: {e}")
        logger.warning("Falling back to in-memory cache")
        return None

# ============================================
# MQTT CLIENT (For IoT device communication)
# ============================================
import paho.mqtt.client as mqtt

mqtt_client = None

def init_mqtt(app):
    """Initialize MQTT client for communication with traffic signals"""
    global mqtt_client
    
    if not app.config.get('MQTT_BROKER_URL'):
        logger.warning("MQTT not configured, skipping initialization")
        return None
    
    try:
        mqtt_client = mqtt.Client()
        
        # Set username/password if provided
        if app.config.get('MQTT_USERNAME'):
            mqtt_client.username_pw_set(
                app.config['MQTT_USERNAME'],
                app.config['MQTT_PASSWORD']
            )
        
        # Set TLS if enabled
        if app.config.get('MQTT_TLS_ENABLED'):
            mqtt_client.tls_set()
        
        # Callback functions
        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                logger.info("✅ MQTT connected successfully")
                # Subscribe to traffic signal topics
                client.subscribe("traffic/signals/#")
                client.subscribe("vehicles/emergency/#")
            else:
                logger.error(f"❌ MQTT connection failed with code: {rc}")
        
        def on_message(client, userdata, msg):
            logger.debug(f"📡 MQTT message received: {msg.topic} -> {msg.payload}")
            # Process MQTT messages (will be handled by services)
        
        mqtt_client.on_connect = on_connect
        mqtt_client.on_message = on_message
        
        # Connect to broker
        mqtt_client.connect_async(
            app.config['MQTT_BROKER_URL'],
            app.config['MQTT_BROKER_PORT'],
            app.config['MQTT_KEEPALIVE']
        )
        
        # Start MQTT loop in background
        mqtt_client.loop_start()
        
        return mqtt_client
        
    except Exception as e:
        logger.error(f"❌ MQTT initialization failed: {e}")
        return None

# ============================================
# JWT CALLBACKS (Custom JWT handlers)
# ============================================
def setup_jwt_callbacks():
    """Setup custom JWT callbacks for token handling"""
    
    @jwt.token_in_blocklist_loader
    def check_if_token_revoked(jwt_header, jwt_payload):
        """Check if token is revoked (for logout functionality)"""
        from app.models.user import TokenBlocklist
        jti = jwt_payload["jti"]
        token = db.session.query(TokenBlocklist).filter_by(jti=jti).first()
        return token is not None
    
    @jwt.expired_token_loader
    def expired_token_callback(jwt_header, jwt_payload):
        """Handle expired token"""
        return {
            "error": "Token Expired",
            "message": "Your session has expired. Please login again."
        }, 401
    
    @jwt.invalid_token_loader
    def invalid_token_callback(error):
        """Handle invalid token"""
        return {
            "error": "Invalid Token",
            "message": "Authentication token is invalid."
        }, 401
    
    @jwt.unauthorized_loader
    def unauthorized_callback(error):
        """Handle missing token"""
        return {
            "error": "Authorization Required",
            "message": "Please provide a valid authentication token."
        }, 401
    
    logger.info("✅ JWT callbacks configured")

# ============================================
# DATABASE EVENT LISTENERS
# ============================================
def setup_db_listeners():
    """Setup database event listeners for auditing"""
    
    from sqlalchemy import event
    
    # Example: Log all INSERT, UPDATE, DELETE operations
    @event.listens_for(db.Model, 'before_insert')
    def before_insert(mapper, connection, target):
        """Triggered before any database insert"""
        if hasattr(target, 'created_at'):
            from datetime import datetime
            target.created_at = datetime.utcnow()
        logger.debug(f"📝 Database INSERT: {target.__class__.__name__}")
    
    @event.listens_for(db.Model, 'before_update')
    def before_update(mapper, connection, target):
        """Triggered before any database update"""
        if hasattr(target, 'updated_at'):
            from datetime import datetime
            target.updated_at = datetime.utcnow()
        logger.debug(f"📝 Database UPDATE: {target.__class__.__name__}")
    
    @event.listens_for(db.Model, 'before_delete')
    def before_delete(mapper, connection, target):
        """Triggered before any database delete"""
        logger.debug(f"📝 Database DELETE: {target.__class__.__name__}")
    
    logger.info("✅ Database event listeners configured")

# ============================================
# EXTENSIONS INITIALIZATION FUNCTION
# ============================================
def init_extensions(app):
    """
    Initialize all extensions with the Flask app instance
    Call this function inside create_app()
    """
    global celery, redis_client
    
    # Initialize database extensions
    db.init_app(app)
    migrate.init_app(app, db)
    
    # Initialize security extensions
    bcrypt.init_app(app)
    jwt.init_app(app)
    
    # Initialize caching and rate limiting
    cache.init_app(app)
    limiter.init_app(app)
    
    # Initialize email
    mail.init_app(app)
    
    # Initialize SocketIO
    socketio.init_app(app, cors_allowed_origins=app.config.get('CORS_ORIGINS', '*'))
    
    # Initialize Celery
    celery = make_celery(app)
    
    # Initialize Redis
    redis_client = init_redis(app)
    
    # Initialize MQTT (optional)
    if app.config.get('MQTT_BROKER_URL'):
        init_mqtt(app)
    
    # Setup JWT callbacks
    setup_jwt_callbacks()
    
    # Setup database listeners (commented for performance)
    # setup_db_listeners()
    
    logger.info("✅ All Flask extensions initialized successfully")
    logger.info(f"📦 Extensions loaded: db, migrate, bcrypt, jwt, cache, limiter, mail, socketio, celery")
    
    return {
        'db': db,
        'migrate': migrate,
        'bcrypt': bcrypt,
        'jwt': jwt,
        'cache': cache,
        'limiter': limiter,
        'mail': mail,
        'socketio': socketio,
        'celery': celery,
        'redis': redis_client
    }

# ============================================
# HELPER FUNCTIONS FOR EXTENSIONS
# ============================================

def get_redis():
    """Get Redis client instance"""
    return redis_client

def get_celery():
    """Get Celery instance"""
    return celery

def get_mqtt():
    """Get MQTT client instance"""
    return mqtt_client

# Context manager for Redis operations
class RedisContext:
    """Context manager for Redis operations"""
    def __enter__(self):
        return redis_client
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        pass  # Redis connection pooling handles cleanup

# ============================================
# HELPER FUNCTIONS FOR EXTENSIONS
# ============================================

def get_cache_key(prefix, *args):
    """Generate a cache key from prefix and arguments"""
    return f"{prefix}:{':'.join(str(arg) for arg in args)}"

def clear_vehicle_cache(vehicle_id):
    """Clear cache for a specific vehicle"""
    cache.delete(f"vehicle:{vehicle_id}")
    cache.delete(f"vehicle_location:{vehicle_id}")
    logger.debug(f"Cleared cache for vehicle {vehicle_id}")

def clear_traffic_cache(intersection_id):
    """Clear cache for a specific traffic intersection"""
    cache.delete(f"traffic:{intersection_id}")
    cache.delete(f"traffic_density:{intersection_id}")
    logger.debug(f"Cleared cache for intersection {intersection_id}")

# ============================================
# EXPORTS
# ============================================

__all__ = [
    'db',
    'migrate',
    'bcrypt',
    'jwt',
    'cache',
    'limiter',
    'mail',
    'socketio',
    'init_extensions',
    'get_redis',
    'get_celery',
    'get_mqtt',
    'RedisContext',
    'get_cache_key',
    'clear_vehicle_cache',
    'clear_traffic_cache'
]