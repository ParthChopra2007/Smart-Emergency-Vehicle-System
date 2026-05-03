"""
Smart Emergency Vehicle Priority System - Validators
Provides input validation functions for requests, JSON schemas,
data sanitization, and business rule validation
"""

import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Union, Tuple
from functools import wraps
from loguru import logger

from flask import request, jsonify

# ============================================
# SCHEMA VALIDATORS
# ============================================

class ValidationError(Exception):
    """Custom validation error"""
    pass


def validate_json(data: Dict, schema: Dict) -> Tuple[bool, List[str]]:
    """
    Validate JSON data against schema
    Returns (is_valid, errors_list)
    """
    errors = []
    
    # Check required fields
    for required_field in schema.get('required', []):
        if required_field not in data:
            errors.append(f"Missing required field: {required_field}")
    
    # Check field types and constraints
    properties = schema.get('properties', {})
    for field, rules in properties.items():
        if field not in data:
            continue
        
        value = data[field]
        field_type = rules.get('type')
        
        # Type validation
        if field_type == 'string' and not isinstance(value, str):
            errors.append(f"Field '{field}' must be a string")
        elif field_type == 'integer' and not isinstance(value, int):
            errors.append(f"Field '{field}' must be an integer")
        elif field_type == 'number' and not isinstance(value, (int, float)):
            errors.append(f"Field '{field}' must be a number")
        elif field_type == 'boolean' and not isinstance(value, bool):
            errors.append(f"Field '{field}' must be a boolean")
        elif field_type == 'array' and not isinstance(value, list):
            errors.append(f"Field '{field}' must be an array")
        elif field_type == 'object' and not isinstance(value, dict):
            errors.append(f"Field '{field}' must be an object")
        
        # String constraints
        if field_type == 'string':
            min_length = rules.get('minLength')
            max_length = rules.get('maxLength')
            pattern = rules.get('pattern')
            enum = rules.get('enum')
            
            if min_length and len(value) < min_length:
                errors.append(f"Field '{field}' must be at least {min_length} characters")
            if max_length and len(value) > max_length:
                errors.append(f"Field '{field}' must be at most {max_length} characters")
            if pattern and not re.match(pattern, value):
                errors.append(f"Field '{field}' has invalid format")
            if enum and value not in enum:
                errors.append(f"Field '{field}' must be one of: {', '.join(enum)}")
        
        # Number constraints
        if field_type in ['integer', 'number']:
            minimum = rules.get('minimum')
            maximum = rules.get('maximum')
            
            if minimum is not None and value < minimum:
                errors.append(f"Field '{field}' must be at least {minimum}")
            if maximum is not None and value > maximum:
                errors.append(f"Field '{field}' must be at most {maximum}")
        
        # Array constraints
        if field_type == 'array':
            min_items = rules.get('minItems')
            max_items = rules.get('maxItems')
            
            if min_items and len(value) < min_items:
                errors.append(f"Field '{field}' must have at least {min_items} items")
            if max_items and len(value) > max_items:
                errors.append(f"Field '{field}' must have at most {max_items} items")
    
    return len(errors) == 0, errors


def validate_schema(schema: Dict):
    """
    Decorator for request JSON validation
    Usage: @validate_schema(user_schema)
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not request.is_json:
                return jsonify({
                    'error': 'Invalid request',
                    'message': 'Content-Type must be application/json'
                }), 400
            
            data = request.get_json()
            is_valid, errors = validate_json(data, schema)
            
            if not is_valid:
                return jsonify({
                    'error': 'Validation failed',
                    'message': 'Request data validation failed',
                    'errors': errors
                }), 400
            
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator


# ============================================
# FIELD VALIDATORS
# ============================================

def validate_required_fields(data: Dict, required_fields: List[str]) -> Tuple[bool, List[str]]:
    """
    Validate that all required fields are present
    """
    missing = [field for field in required_fields if field not in data or data[field] is None]
    return len(missing) == 0, missing


def validate_email(email: str) -> bool:
    """
    Validate email format
    """
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def validate_phone(phone: str) -> bool:
    """
    Validate phone number format
    Supports: +91XXXXXXXXXX, 0XXXXXXXXXX, XXXXXXXXXX
    """
    # Remove any spaces or special characters
    phone = re.sub(r'[\s\-\(\)]', '', phone)
    pattern = r'^(\+?91|0)?[6-9]\d{9}$'
    return bool(re.match(pattern, phone))


def validate_password_strength(password: str) -> Tuple[bool, str]:
    """
    Validate password strength
    Returns (is_valid, message)
    """
    if len(password) < 8:
        return False, "Password must be at least 8 characters long"
    
    if not re.search(r'[A-Z]', password):
        return False, "Password must contain at least one uppercase letter"
    
    if not re.search(r'[a-z]', password):
        return False, "Password must contain at least one lowercase letter"
    
    if not re.search(r'\d', password):
        return False, "Password must contain at least one number"
    
    if not re.search(r'[!@#$%^&*(),.?":{}|<>]', password):
        return False, "Password must contain at least one special character"
    
    return True, "Password is strong"


def validate_pincode(pincode: str) -> bool:
    """
    Validate Indian pincode (6 digits)
    """
    return bool(re.match(r'^\d{6}$', pincode))


def validate_vehicle_number(vehicle_number: str) -> bool:
    """
    Validate Indian vehicle registration number
    Format: XX 00 XX 0000
    """
    pattern = r'^[A-Z]{2}[0-9]{1,2}[A-Z]{1,2}[0-9]{4}$'
    return bool(re.match(pattern, vehicle_number.upper()))


def validate_latitude(latitude: float) -> bool:
    """
    Validate latitude (-90 to 90)
    """
    return -90 <= latitude <= 90


def validate_longitude(longitude: float) -> bool:
    """
    Validate longitude (-180 to 180)
    """
    return -180 <= longitude <= 180


def validate_url(url: str) -> bool:
    """
    Validate URL format
    """
    pattern = r'^https?://(?:[-\w.]|(?:%[\da-fA-F]{2}))+[/]?'
    return bool(re.match(pattern, url))


# ============================================
# RANGE VALIDATORS
# ============================================

def validate_range(value: Union[int, float], min_val: Union[int, float], max_val: Union[int, float]) -> bool:
    """
    Validate that value is within range
    """
    return min_val <= value <= max_val


def validate_length(value: str, min_len: int, max_len: int) -> bool:
    """
    Validate string length
    """
    return min_len <= len(value) <= max_len


# ============================================
# EMERGENCY VEHICLE VALIDATORS
# ============================================

VALID_VEHICLE_TYPES = ['ambulance', 'fire_brigade', 'police', 'disaster_management', 'rescue']
VALID_INCIDENT_TYPES = ['medical_emergency', 'accident', 'fire', 'crime', 'natural_disaster', 'hazmat', 'rescue_operation', 'bomb_threat', 'public_disturbance', 'other']
VALID_SEVERITY_LEVELS = ['critical', 'high', 'medium', 'low']
VALID_STATUSES = ['available', 'on_duty', 'en_route', 'at_scene', 'returning', 'off_duty', 'maintenance', 'out_of_service']


def validate_vehicle_type(vehicle_type: str) -> bool:
    """
    Validate emergency vehicle type
    """
    return vehicle_type in VALID_VEHICLE_TYPES


def validate_incident_type(incident_type: str) -> bool:
    """
    Validate incident type
    """
    return incident_type in VALID_INCIDENT_TYPES


def validate_severity_level(severity: str) -> bool:
    """
    Validate severity level
    """
    return severity in VALID_SEVERITY_LEVELS


def validate_status_transition(current_status: str, new_status: str) -> Tuple[bool, str]:
    """
    Validate status transition rules for emergency vehicles
    """
    valid_transitions = {
        'available': ['on_duty', 'off_duty', 'maintenance'],
        'on_duty': ['en_route', 'off_duty'],
        'en_route': ['at_scene', 'off_duty'],
        'at_scene': ['returning', 'off_duty'],
        'returning': ['available', 'off_duty'],
        'off_duty': ['available', 'on_duty', 'maintenance'],
        'maintenance': ['available', 'off_duty'],
        'out_of_service': []
    }
    
    if new_status not in valid_transitions.get(current_status, []):
        return False, f"Invalid transition from {current_status} to {new_status}"
    
    return True, "Valid transition"


# ============================================
# CUSTOM VALIDATORS
# ============================================

def validate_coordinates(latitude: float, longitude: float) -> Tuple[bool, str]:
    """
    Validate coordinate pair
    """
    if not validate_latitude(latitude):
        return False, f"Invalid latitude: {latitude}. Must be between -90 and 90"
    
    if not validate_longitude(longitude):
        return False, f"Invalid longitude: {longitude}. Must be between -180 and 180"
    
    return True, "Valid coordinates"


def validate_timestamp(timestamp: str) -> Tuple[bool, Optional[datetime]]:
    """
    Validate ISO format timestamp and return datetime object
    """
    try:
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        return True, dt
    except (ValueError, AttributeError):
        return False, None


def validate_date_range(start_date: str, end_date: str) -> Tuple[bool, str]:
    """
    Validate that end_date is after start_date
    """
    is_valid_start, start_dt = validate_timestamp(start_date)
    is_valid_end, end_dt = validate_timestamp(end_date)
    
    if not is_valid_start:
        return False, "Invalid start date format"
    
    if not is_valid_end:
        return False, "Invalid end date format"
    
    if end_dt < start_dt:
        return False, "End date must be after start date"
    
    return True, "Valid date range"


# ============================================
# DATA SANITIZATION
# ============================================

def sanitize_string(value: str, strip_html: bool = True) -> str:
    """
    Sanitize string input
    """
    if not value:
        return ""
    
    # Remove extra whitespace
    value = ' '.join(value.split())
    
    # Remove HTML tags
    if strip_html:
        value = re.sub(r'<[^>]+>', '', value)
    
    return value


def sanitize_email(email: str) -> str:
    """
    Sanitize email address
    """
    if not email:
        return ""
    return email.lower().strip()


def sanitize_phone(phone: str) -> str:
    """
    Sanitize phone number
    """
    if not phone:
        return ""
    # Remove spaces, hyphens, parentheses
    return re.sub(r'[\s\-\(\)]', '', phone)


def sanitize_input(data: Dict, fields_to_sanitize: List[str]) -> Dict:
    """
    Sanitize specific fields in a dictionary
    """
    result = data.copy()
    
    for field in fields_to_sanitize:
        if field in result and isinstance(result[field], str):
            result[field] = sanitize_string(result[field])
    
    if 'email' in result:
        result['email'] = sanitize_email(result.get('email', ''))
    
    if 'phone' in result or 'phone_number' in result:
        phone_field = 'phone' if 'phone' in result else 'phone_number'
        result[phone_field] = sanitize_phone(result.get(phone_field, ''))
    
    return result


# ============================================
# BUSINESS RULE VALIDATORS
# ============================================

def validate_eta(distance_km: float, speed_kmh: float) -> Tuple[bool, float]:
    """
    Validate ETA calculation
    """
    if distance_km < 0:
        return False, 0
    
    if speed_kmh <= 0:
        speed_kmh = 40  # Default speed
    
    eta_seconds = (distance_km / speed_kmh) * 3600
    return True, eta_seconds


def validate_corridor_distance(distance_km: float, max_distance_km: float = 50) -> Tuple[bool, str]:
    """
    Validate corridor distance is within limits
    """
    if distance_km <= 0:
        return False, "Distance must be positive"
    
    if distance_km > max_distance_km:
        return False, f"Corridor distance exceeds maximum of {max_distance_km} km"
    
    return True, "Valid distance"


def validate_response_time(response_seconds: int, target_seconds: int = 300) -> Tuple[bool, str]:
    """
    Validate response time against target
    """
    if response_seconds <= target_seconds:
        return True, f"Response time within target ({response_seconds}s <= {target_seconds}s)"
    else:
        return False, f"Response time exceeds target ({response_seconds}s > {target_seconds}s)"


# ============================================
# REQUEST DATA EXTRACTORS
# ============================================

def get_validated_json(schema: Dict = None) -> Dict:
    """
    Get validated JSON from request
    """
    if not request.is_json:
        raise ValidationError("Content-Type must be application/json")
    
    data = request.get_json()
    
    if schema:
        is_valid, errors = validate_json(data, schema)
        if not is_valid:
            raise ValidationError(f"Validation failed: {', '.join(errors)}")
    
    return data


def get_pagination_params(default_page: int = 1, default_per_page: int = 20, max_per_page: int = 100) -> Tuple[int, int]:
    """
    Extract and validate pagination parameters
    """
    page = request.args.get('page', default_page, type=int)
    per_page = request.args.get('per_page', default_per_page, type=int)
    
    if page < 1:
        page = 1
    
    if per_page < 1:
        per_page = default_per_page
    elif per_page > max_per_page:
        per_page = max_per_page
    
    return page, per_page


def get_search_params() -> Dict:
    """
    Extract search parameters from request
    """
    params = {
        'search': request.args.get('search', ''),
        'field': request.args.get('field', ''),
        'order': request.args.get('order', 'asc')
    }
    
    if params['order'] not in ['asc', 'desc']:
        params['order'] = 'asc'
    
    if params['field']:
        params['field'] = sanitize_string(params['field'])
    
    return params


def get_filter_params(allowed_filters: List[str]) -> Dict:
    """
    Extract and validate filter parameters
    """
    filters = {}
    
    for filter_name in allowed_filters:
        value = request.args.get(filter_name)
        if value is not None:
            filters[filter_name] = value
    
    return filters


# ============================================
# EXPORTS
# ============================================

# Schema Validators
__all__ = [
    'ValidationError',
    'validate_json',
    'validate_schema',
    
    # Field Validators
    'validate_required_fields',
    'validate_email',
    'validate_phone',
    'validate_password_strength',
    'validate_pincode',
    'validate_vehicle_number',
    'validate_latitude',
    'validate_longitude',
    'validate_url',
    
    # Range Validators
    'validate_range',
    'validate_length',
    
    # Emergency Vehicle Validators
    'validate_vehicle_type',
    'validate_incident_type',
    'validate_severity_level',
    'validate_status_transition',
    'VALID_VEHICLE_TYPES',
    'VALID_INCIDENT_TYPES',
    'VALID_SEVERITY_LEVELS',
    
    # Custom Validators
    'validate_coordinates',
    'validate_timestamp',
    'validate_date_range',
    
    # Data Sanitization
    'sanitize_string',
    'sanitize_email',
    'sanitize_phone',
    'sanitize_input',
    
    # Business Rule Validators
    'validate_eta',
    'validate_corridor_distance',
    'validate_response_time',
    
    # Request Data Extractors
    'get_validated_json',
    'get_pagination_params',
    'get_search_params',
    'get_filter_params'
]