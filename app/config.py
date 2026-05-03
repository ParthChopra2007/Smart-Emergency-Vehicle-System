"""
Smart Emergency Vehicle Priority System - Configuration Module
Handles environment-based configuration for development, testing, and production
"""

import os
from datetime import timedelta
from pathlib import Path

# Build paths inside the project
BASE_DIR = Path(__file__).resolve().parent.parent.parent


class Config:
    """
    Base configuration class with common settings
    All other config classes will inherit from this
    """
    
    # ============================================
    # BASIC FLASK CONFIGURATION
    # ============================================
    SECRET_KEY = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
    
    # ============================================
    # DATABASE CONFIGURATION
    # ============================================
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_size': 10,
        'pool_recycle': 3600,
        'pool_pre_ping': True,
    }
    
    # ============================================
    # JWT AUTHENTICATION CONFIGURATION
    # ============================================
    JWT_SECRET_KEY = os.environ.get('JWT_SECRET_KEY', 'jwt-secret-key-change-in-production')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=1)
    JWT_REFRESH_TOKEN_EXPIRES = timedelta(days=7)
    JWT_TOKEN_LOCATION = ['headers']
    JWT_HEADER_NAME = 'Authorization'
    JWT_HEADER_TYPE = 'Bearer'
    
    # ============================================
    # CORS CONFIGURATION
    # ============================================
    CORS_ORIGINS = [
        'http://localhost:3000',
        'http://localhost:5000',
        'http://127.0.0.1:5000',
        'http://127.0.0.1:3000'
    ]
    CORS_SUPPORTS_CREDENTIALS = True
    
    # ============================================
    # REDIS CONFIGURATION (for caching and Celery)
    # ============================================
    REDIS_URL = os.environ.get('REDIS_URL', 'redis://localhost:6379/0')
    CACHE_TYPE = 'redis'
    CACHE_REDIS_URL = REDIS_URL
    CACHE_DEFAULT_TIMEOUT = 300
    
    # ============================================
    # CELERY CONFIGURATION
    # ============================================
    CELERY_BROKER_URL = REDIS_URL
    CELERY_RESULT_BACKEND = REDIS_URL
    CELERY_ACCEPT_CONTENT = ['json']
    CELERY_TASK_SERIALIZER = 'json'
    CELERY_RESULT_SERIALIZER = 'json'
    CELERY_TIMEZONE = 'Asia/Kolkata'
    
    # ============================================
    # MQTT/IoT CONFIGURATION
    # ============================================
    MQTT_BROKER_URL = os.environ.get('MQTT_BROKER_URL', 'localhost')
    MQTT_BROKER_PORT = int(os.environ.get('MQTT_BROKER_PORT', 1883))
    MQTT_USERNAME = os.environ.get('MQTT_USERNAME', '')
    MQTT_PASSWORD = os.environ.get('MQTT_PASSWORD', '')
    MQTT_KEEPALIVE = 60
    MQTT_TLS_ENABLED = False
    
    # ============================================
    # WEBSOCKET/SOCKETIO CONFIGURATION
    # ============================================
    SOCKETIO_MESSAGE_QUEUE = REDIS_URL
    SOCKETIO_ASYNC_MODE = 'threading'
    SOCKETIO_CORS_ALLOWED_ORIGINS = CORS_ORIGINS
    
    # ============================================
    # EMERGENCY VEHICLE CONFIGURATION
    # ============================================
    EMERGENCY_VEHICLE_TYPES = {
        'ambulance': {
            'priority': 1,  # Highest priority
            'color': '#FF0000',
            'time_threshold_seconds': 300  # 5 minutes
        },
        'fire_brigade': {
            'priority': 2,
            'color': '#FF5500',
            'time_threshold_seconds': 420  # 7 minutes
        },
        'police': {
            'priority': 3,
            'color': '#0000FF',
            'time_threshold_seconds': 600  # 10 minutes
        }
    }
    
    # Green corridor parameters
    GREEN_CORRIDOR_PRE_TIME = 15  # Seconds before vehicle arrives, signal turns green
    GREEN_CORRIDOR_POST_TIME = 5  # Seconds after vehicle passes, signal stays green
    MAX_CORRIDOR_DISTANCE_KM = 10  # Maximum corridor length in KM
    
    # ============================================
    # AI & TRAFFIC INTELLIGENCE CONFIGURATION
    # ============================================
    AI_MODEL_PATH = os.path.join(BASE_DIR, 'models', 'yolov8n.pt')
    TRAFFIC_PREDICTION_WINDOW = 300  # Predict next 5 minutes
    TRAFFIC_UPDATE_INTERVAL = 10  # Update traffic data every 10 seconds
    VEHICLE_DETECTION_CONFIDENCE = 0.5  # YOLO confidence threshold
    
    # ============================================
    # BLOCKCHAIN CONFIGURATION
    # ============================================
    WEB3_PROVIDER_URL = os.environ.get('WEB3_PROVIDER_URL', 'http://localhost:8545')
    BLOCKCHAIN_ENABLED = os.environ.get('BLOCKCHAIN_ENABLED', 'False').lower() == 'true'
    CONTRACT_ADDRESS = os.environ.get('CONTRACT_ADDRESS', '')
    GAS_LIMIT = 2000000
    GAS_PRICE = 20  # Gwei
    
    # ============================================
    # EMAIL CONFIGURATION (for alerts)
    # ============================================
    MAIL_SERVER = os.environ.get('MAIL_SERVER', 'smtp.gmail.com')
    MAIL_PORT = int(os.environ.get('MAIL_PORT', 587))
    MAIL_USE_TLS = True
    MAIL_USE_SSL = False
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME', '')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD', '')
    MAIL_DEFAULT_SENDER = os.environ.get('MAIL_DEFAULT_SENDER', 'noreply@sevps.com')
    
    # ============================================
    # SMS CONFIGURATION (for critical alerts using Twilio)
    # ============================================
    TWILIO_ACCOUNT_SID = os.environ.get('TWILIO_ACCOUNT_SID', '')
    TWILIO_AUTH_TOKEN = os.environ.get('TWILIO_AUTH_TOKEN', '')
    TWILIO_PHONE_NUMBER = os.environ.get('TWILIO_PHONE_NUMBER', '')
    
    # ============================================
    # MAPS & GEOLOCATION
    # ============================================
    GOOGLE_MAPS_API_KEY = os.environ.get('GOOGLE_MAPS_API_KEY', '')
    OPENWEATHER_API_KEY = os.environ.get('OPENWEATHER_API_KEY', '')
    DEFAULT_CITY_COORDINATES = {
        'latitude': 28.6139,   # Delhi (example)
        'longitude': 77.2090
    }
    
    # ============================================
    # LOGGING CONFIGURATION
    # ============================================
    LOG_LEVEL = 'INFO'
    LOG_FILE_PATH = os.path.join(BASE_DIR, 'logs', 'sevps.log')
    LOG_MAX_BYTES = 10 * 1024 * 1024  # 10 MB
    LOG_BACKUP_COUNT = 10
    
    # ============================================
    # API RATE LIMITING
    # ============================================
    RATELIMIT_ENABLED = True
    RATELIMIT_DEFAULT = "100 per minute"
    RATELIMIT_STORAGE_URL = REDIS_URL
    
    # ============================================
    # UPLOAD CONFIGURATION
    # ============================================
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB max upload
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'backend', 'static', 'uploads')
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'mp4'}
    
    # ============================================
    # SESSION & SECURITY
    # ============================================
    SESSION_COOKIE_SECURE = False  # Set to True in production with HTTPS
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_DURATION = timedelta(days=30)
    
    # ============================================
    # ENVIRONMENT SPECIFIC
    # ============================================
    ENVIRONMENT = 'base'
    DEBUG = False
    TESTING = False


class DevelopmentConfig(Config):
    """Development environment configuration"""
    
    ENVIRONMENT = 'development'
    DEBUG = True
    TESTING = False
    
    # Use SQLite for development (easy setup)
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL', 
        f'sqlite:///{os.path.join(BASE_DIR, "database", "dev_sevps.db")}'
    )
    
    # Ensure database directory exists
    os.makedirs(os.path.join(BASE_DIR, 'database'), exist_ok=True)
    
    # Log level for development
    LOG_LEVEL = 'DEBUG'
    
    # Disable blockchain in development (optional)
    BLOCKCHAIN_ENABLED = False
    
    # CORS for development (allow all)
    CORS_ORIGINS = ['*']
    
    # Session security relaxed for development
    SESSION_COOKIE_SECURE = False
    
    # Print SQL queries in development
    SQLALCHEMY_ECHO = True


class TestingConfig(Config):
    """Testing environment configuration"""
    
    ENVIRONMENT = 'testing'
    DEBUG = False
    TESTING = True
    
    # Use in-memory SQLite for testing
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    
    # Disable rate limiting in tests
    RATELIMIT_ENABLED = False
    
    # JWT expiry short for testing
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(minutes=5)
    
    # Disable blockchain in tests
    BLOCKCHAIN_ENABLED = False
    
    # Test-specific MQTT settings
    MQTT_BROKER_URL = 'localhost'
    
    # No email sending in tests
    MAIL_SUPPRESS_SEND = True


class ProductionConfig(Config):
    """Production environment configuration"""
    
    ENVIRONMENT = 'production'
    DEBUG = False
    TESTING = False
    
    # Use PostgreSQL for production
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL')
    
    # Must be set in production
    if not SQLALCHEMY_DATABASE_URI:
        raise ValueError("DATABASE_URL environment variable is required in production")
    
    # SECURITY: Must be set in production
    if os.environ.get('SECRET_KEY') == 'dev-secret-key-change-in-production':
        raise ValueError("SECRET_KEY must be changed in production")
    
    if os.environ.get('JWT_SECRET_KEY') == 'jwt-secret-key-change-in-production':
        raise ValueError("JWT_SECRET_KEY must be changed in production")
    
    # Production security settings
    SESSION_COOKIE_SECURE = True  # HTTPS only
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Strict'
    
    # Enable blockchain in production (if configured)
    BLOCKCHAIN_ENABLED = os.environ.get('BLOCKCHAIN_ENABLED', 'False').lower() == 'true'
    
    # Production log level
    LOG_LEVEL = 'WARNING'
    
    # Disable SQL query logging
    SQLALCHEMY_ECHO = False
    
    # Use Redis for production (not default)
    CACHE_TYPE = 'redis'
    
    # Rate limiting enabled in production
    RATELIMIT_ENABLED = True
    
    # CORS restricted in production
    CORS_ORIGINS = os.environ.get('CORS_ORIGINS', '').split(',')
    
    # MQTT with TLS in production
    MQTT_TLS_ENABLED = True


class DockerConfig(ProductionConfig):
    """Configuration for Docker deployment"""
    
    ENVIRONMENT = 'docker'
    
    # Docker-specific database URL
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL', 'postgresql://postgres:password@postgres:5432/sevps_db')
    
    # Docker-specific Redis URL
    REDIS_URL = os.environ.get('REDIS_URL', 'redis://redis:6379/0')
    CELERY_BROKER_URL = REDIS_URL
    CELERY_RESULT_BACKEND = REDIS_URL
    
    # Docker MQTT settings
    MQTT_BROKER_URL = os.environ.get('MQTT_BROKER_URL', 'mqtt_broker')
    
    # Docker log settings
    LOG_LEVEL = 'INFO'


# Configuration dictionary
config = {
    'development': DevelopmentConfig,
    'testing': TestingConfig,
    'production': ProductionConfig,
    'docker': DockerConfig,
    'default': DevelopmentConfig
}


def get_config():
    """Return configuration class based on FLASK_ENV environment variable"""
    env = os.environ.get('FLASK_ENV', 'development')
    return config.get(env, DevelopmentConfig)


# Export all configs
__all__ = [
    'Config',
    'DevelopmentConfig', 
    'TestingConfig',
    'ProductionConfig',
    'DockerConfig',
    'get_config',
    'BASE_DIR'
]