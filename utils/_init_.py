"""
Smart Emergency Vehicle Priority System - Utils Package
This file initializes all utility modules and exports helper functions,
custom decorators, and validators for use across the application
"""

from loguru import logger

# ============================================
# IMPORT ALL UTILITY MODULES
# ============================================

from app.utils.helpers import (
    # Date/Time Helpers
    format_datetime,
    format_duration,
    get_current_ist,
    time_ago,
    
    # String Helpers
    generate_random_string,
    truncate_string,
    slugify,
    validate_email_format,
    validate_phone_format,
    
    # Distance/Geo Helpers
    calculate_distance,
    calculate_bearing,
    midpoint,
    is_point_in_polygon,
    
    # JSON/Data Helpers
    safe_json_parse,
    safe_json_dumps,
    deep_merge,
    
    # Response Helpers
    success_response,
    error_response,
    paginated_response,
    
    # Token/ID Helpers
    generate_uuid,
    generate_otp,
    generate_tracking_id,
    
    # File Helpers
    allowed_file,
    get_file_extension,
    unique_filename,
    
    # Network Helpers
    get_client_ip,
    is_safe_url,
    
    # Cache Helpers
    cache_key,
    invalidate_cache_pattern,
    
    # Logging Helpers
    log_error,
    log_api_call,
    
    # Dictionary Helpers
    filter_dict,
    exclude_keys,
    pick_keys,
    
    # List Helpers
    chunk_list,
    unique_list,
    
    # Number Helpers
    round_km,
    format_percentage,
    format_currency
)

from app.utils.decorators import (
    # Authentication Decorators
    role_required,
    permission_required,
    
    # Rate Limiting Decorators
    rate_limit,
    limiter,
    
    # Cache Decorators
    cached,
    cached_response,
    
    # Logging Decorators
    log_execution_time,
    log_function_call,
    
    # Validation Decorators
    validate_json_schema,
    validate_query_params,
    
    # Error Handling Decorators
    handle_errors,
    retry_on_failure,
    
    # Async Decorators
    async_task,
    background_task,
    
    # API Decorators
    api_endpoint,
    public_endpoint,
    
    # Database Decorators
    transactional,
    master_only,
    replica_only
)

from app.utils.validators import (
    # Schema Validators
    validate_json,
    validate_schema,
    
    # Field Validators
    validate_required_fields,
    validate_email,
    validate_phone,
    validate_password_strength,
    validate_pincode,
    validate_vehicle_number,
    validate_latitude,
    validate_longitude,
    validate_url,
    
    # Range Validators
    validate_range,
    validate_length,
    
    # Emergency Vehicle Validators
    validate_vehicle_type,
    validate_incident_type,
    validate_severity_level,
    validate_status_transition,
    
    # Custom Validators
    validate_coordinates,
    validate_timestamp,
    validate_date_range
)

# ============================================
# UTILITIES INITIALIZATION FUNCTION
# ============================================

def init_utils(app):
    """
    Initialize all utilities with the Flask app
    Call this function inside create_app()
    """
    logger.info("✅ Utilities package initialized")
    logger.info("   Available: helpers, decorators, validators")
    return True


# ============================================
# VERSION INFORMATION
# ============================================

__version__ = "1.0.0"
__author__ = "SEVPS Team"
__description__ = "Smart Emergency Vehicle Priority System - Utilities"

# ============================================
# EXPORTS - All utilities available from one place
# ============================================

__all__ = [
    # Helper Functions
    'format_datetime',
    'format_duration',
    'get_current_ist',
    'time_ago',
    'generate_random_string',
    'truncate_string',
    'slugify',
    'validate_email_format',
    'validate_phone_format',
    'calculate_distance',
    'calculate_bearing',
    'midpoint',
    'is_point_in_polygon',
    'safe_json_parse',
    'safe_json_dumps',
    'deep_merge',
    'success_response',
    'error_response',
    'paginated_response',
    'generate_uuid',
    'generate_otp',
    'generate_tracking_id',
    'allowed_file',
    'get_file_extension',
    'unique_filename',
    'get_client_ip',
    'is_safe_url',
    'cache_key',
    'invalidate_cache_pattern',
    'log_error',
    'log_api_call',
    'filter_dict',
    'exclude_keys',
    'pick_keys',
    'chunk_list',
    'unique_list',
    'round_km',
    'format_percentage',
    'format_currency',
    
    # Decorators
    'role_required',
    'permission_required',
    'rate_limit',
    'limiter',
    'cached',
    'cached_response',
    'log_execution_time',
    'log_function_call',
    'validate_json_schema',
    'validate_query_params',
    'handle_errors',
    'retry_on_failure',
    'async_task',
    'background_task',
    'api_endpoint',
    'public_endpoint',
    'transactional',
    'master_only',
    'replica_only',
    
    # Validators
    'validate_json',
    'validate_schema',
    'validate_required_fields',
    'validate_email',
    'validate_phone',
    'validate_password_strength',
    'validate_pincode',
    'validate_vehicle_number',
    'validate_latitude',
    'validate_longitude',
    'validate_url',
    'validate_range',
    'validate_length',
    'validate_vehicle_type',
    'validate_incident_type',
    'validate_severity_level',
    'validate_status_transition',
    'validate_coordinates',
    'validate_timestamp',
    'validate_date_range',
    
    # Init
    'init_utils',
    
    # Version
    '__version__',
    '__author__',
    '__description__'
]

# ============================================
# INITIALIZATION LOG
# ============================================

logger.info("📦 Utils package initialized successfully")
logger.info("   - helpers.py: loaded")
logger.info("   - decorators.py: loaded")
logger.info("   - validators.py: loaded")