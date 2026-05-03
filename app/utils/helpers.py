"""
Smart Emergency Vehicle Priority System - Helper Functions
Common utility functions used across the application
"""

import re
import uuid
import json
import secrets
import string
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional, Any, Union
from functools import wraps
from loguru import logger
import hashlib
import hmac

from geopy.distance import geodesic
from flask import jsonify, request, current_app

# ============================================
# DATE/TIME HELPERS
# ============================================

def format_datetime(dt: datetime, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    Format datetime to string
    """
    if dt is None:
        return ""
    return dt.strftime(format_str)


def format_duration(seconds: int) -> str:
    """
    Format duration in seconds to readable string
    Example: 3665 -> "1h 1m 5s"
    """
    if seconds < 0:
        return "0s"
    
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    secs = seconds % 60
    
    parts = []
    if hours > 0:
        parts.append(f"{hours}h")
    if minutes > 0:
        parts.append(f"{minutes}m")
    if secs > 0 or not parts:
        parts.append(f"{secs}s")
    
    return " ".join(parts)


def get_current_ist() -> datetime:
    """
    Get current time in IST (UTC+5:30)
    """
    from datetime import timezone
    ist_offset = timedelta(hours=5, minutes=30)
    return datetime.utcnow() + ist_offset


def time_ago(dt: datetime) -> str:
    """
    Get human-readable time difference
    Example: "5 minutes ago", "2 hours ago", "3 days ago"
    """
    if dt is None:
        return "Unknown"
    
    now = datetime.utcnow()
    diff = now - dt
    
    seconds = diff.total_seconds()
    
    if seconds < 60:
        return "just now"
    elif seconds < 3600:
        minutes = int(seconds // 60)
        return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
    elif seconds < 86400:
        hours = int(seconds // 3600)
        return f"{hours} hour{'s' if hours != 1 else ''} ago"
    elif seconds < 604800:
        days = int(seconds // 86400)
        return f"{days} day{'s' if days != 1 else ''} ago"
    else:
        return dt.strftime("%Y-%m-%d")


# ============================================
# STRING HELPERS
# ============================================

def generate_random_string(length: int = 8, include_digits: bool = True) -> str:
    """
    Generate random string
    """
    chars = string.ascii_letters
    if include_digits:
        chars += string.digits
    return ''.join(secrets.choice(chars) for _ in range(length))


def truncate_string(s: str, max_length: int = 50, suffix: str = "...") -> str:
    """
    Truncate string to max length
    """
    if len(s) <= max_length:
        return s
    return s[:max_length - len(suffix)] + suffix


def slugify(text: str) -> str:
    """
    Convert text to URL-friendly slug
    """
    # Convert to lowercase
    text = text.lower()
    # Replace spaces with hyphens
    text = re.sub(r'\s+', '-', text)
    # Remove special characters
    text = re.sub(r'[^a-z0-9-]', '', text)
    # Remove multiple hyphens
    text = re.sub(r'-+', '-', text)
    # Strip hyphens from ends
    return text.strip('-')


def validate_email_format(email: str) -> bool:
    """
    Validate email format
    """
    pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return bool(re.match(pattern, email))


def validate_phone_format(phone: str) -> bool:
    """
    Validate phone number format
    Supports: +91XXXXXXXXXX, 0XXXXXXXXXX, XXXXXXXXXX
    """
    pattern = r'^(\+?91|0)?[6-9]\d{9}$'
    return bool(re.match(pattern, phone))


# ============================================
# DISTANCE/GEO HELPERS
# ============================================

def calculate_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Calculate distance between two coordinates in kilometers
    """
    return geodesic((lat1, lng1), (lat2, lng2)).kilometers


def calculate_bearing(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Calculate bearing between two coordinates in degrees
    """
    import math
    
    lat1_rad = math.radians(lat1)
    lat2_rad = math.radians(lat2)
    delta_lng = math.radians(lng2 - lng1)
    
    x = math.sin(delta_lng) * math.cos(lat2_rad)
    y = math.cos(lat1_rad) * math.sin(lat2_rad) - \
        math.sin(lat1_rad) * math.cos(lat2_rad) * math.cos(delta_lng)
    
    bearing = math.atan2(x, y)
    bearing_deg = math.degrees(bearing)
    
    return (bearing_deg + 360) % 360


def midpoint(lat1: float, lng1: float, lat2: float, lng2: float) -> Tuple[float, float]:
    """
    Calculate midpoint between two coordinates
    """
    mid_lat = (lat1 + lat2) / 2
    mid_lng = (lng1 + lng2) / 2
    return (mid_lat, mid_lng)


def is_point_in_polygon(lat: float, lng: float, polygon: List[Tuple[float, float]]) -> bool:
    """
    Check if point is inside polygon using ray casting algorithm
    """
    inside = False
    n = len(polygon)
    
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i + 1) % n]
        
        # Check if point is on the horizontal edge
        if (y1 > lng) != (y2 > lng):
            x_intersect = x1 + (lng - y1) * (x2 - x1) / (y2 - y1)
            if lat < x_intersect:
                inside = not inside
    
    return inside


# ============================================
# JSON/DATA HELPERS
# ============================================

def safe_json_parse(json_str: str, default: Any = None) -> Any:
    """
    Safely parse JSON string
    """
    try:
        return json.loads(json_str)
    except (json.JSONDecodeError, TypeError):
        return default


def safe_json_dumps(data: Any, default: str = "{}") -> str:
    """
    Safely convert to JSON string
    """
    try:
        return json.dumps(data, default=str)
    except Exception:
        return default


def deep_merge(base: Dict, updates: Dict) -> Dict:
    """
    Deep merge two dictionaries
    """
    result = base.copy()
    
    for key, value in updates.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = value
    
    return result


# ============================================
# RESPONSE HELPERS
# ============================================

def success_response(data: Any = None, message: str = "Success", status_code: int = 200) -> tuple:
    """
    Create success response
    """
    response = {
        "success": True,
        "message": message,
        "timestamp": datetime.utcnow().isoformat()
    }
    if data is not None:
        response["data"] = data
    
    return jsonify(response), status_code


def error_response(error: str, message: str = None, status_code: int = 400) -> tuple:
    """
    Create error response
    """
    response = {
        "success": False,
        "error": error,
        "timestamp": datetime.utcnow().isoformat()
    }
    if message:
        response["message"] = message
    
    return jsonify(response), status_code


def paginated_response(items: List, total: int, page: int, per_page: int) -> Dict:
    """
    Create paginated response dictionary
    """
    return {
        "items": items,
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "pages": (total + per_page - 1) // per_page if total > 0 else 0
        }
    }


# ============================================
# TOKEN/ID HELPERS
# ============================================

def generate_uuid() -> str:
    """
    Generate UUID string
    """
    return str(uuid.uuid4())


def generate_otp(length: int = 6) -> str:
    """
    Generate OTP (numeric)
    """
    return ''.join(secrets.choice(string.digits) for _ in range(length))


def generate_tracking_id(prefix: str = "TRK") -> str:
    """
    Generate tracking ID
    Format: PREFIX + timestamp + random
    """
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    random_part = generate_random_string(4, include_digits=True)
    return f"{prefix}{timestamp}{random_part}"


# ============================================
# FILE HELPERS
# ============================================

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'pdf', 'mp4', 'csv'}


def allowed_file(filename: str, allowed: set = None) -> bool:
    """
    Check if file extension is allowed
    """
    if allowed is None:
        allowed = ALLOWED_EXTENSIONS
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed


def get_file_extension(filename: str) -> str:
    """
    Get file extension from filename
    """
    if '.' not in filename:
        return ""
    return filename.rsplit('.', 1)[1].lower()


def unique_filename(original_filename: str) -> str:
    """
    Generate unique filename
    """
    ext = get_file_extension(original_filename)
    unique_id = generate_uuid()[:8]
    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    
    if ext:
        return f"{timestamp}_{unique_id}.{ext}"
    return f"{timestamp}_{unique_id}"


# ============================================
# NETWORK HELPERS
# ============================================

def get_client_ip() -> str:
    """
    Get client IP address from request
    """
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0]
    return request.remote_addr or '0.0.0.0'


def is_safe_url(target: str) -> bool:
    """
    Check if URL is safe for redirect
    """
    from urllib.parse import urlparse
    ref_url = urlparse(request.host_url)
    test_url = urlparse(target)
    return test_url.scheme in ('http', 'https') and ref_url.netloc == test_url.netloc


# ============================================
# CACHE HELPERS
# ============================================

def cache_key(prefix: str, *args) -> str:
    """
    Generate cache key
    """
    parts = [prefix]
    for arg in args:
        parts.append(str(arg))
    return ":".join(parts)


def invalidate_cache_pattern(pattern: str):
    """
    Invalidate cache keys matching pattern
    Requires redis client
    """
    try:
        from app.extensions import redis_client
        if redis_client:
            keys = redis_client.keys(f"*{pattern}*")
            if keys:
                redis_client.delete(*keys)
                logger.debug(f"Invalidated {len(keys)} cache keys matching {pattern}")
    except Exception as e:
        logger.error(f"Failed to invalidate cache: {e}")


# ============================================
# LOGGING HELPERS
# ============================================

def log_error(error: Exception, context: Dict = None) -> None:
    """
    Log error with context
    """
    error_msg = f"Error: {str(error)}"
    if context:
        error_msg += f" | Context: {context}"
    logger.error(error_msg)


def log_api_call(endpoint: str, method: str, status_code: int, duration_ms: float) -> None:
    """
    Log API call details
    """
    logger.info(f"API Call: {method} {endpoint} - {status_code} - {duration_ms:.2f}ms")


# ============================================
# DICTIONARY HELPERS
# ============================================

def filter_dict(data: Dict, predicate: callable) -> Dict:
    """
    Filter dictionary by predicate
    """
    return {k: v for k, v in data.items() if predicate(k, v)}


def exclude_keys(data: Dict, keys: List[str]) -> Dict:
    """
    Exclude specific keys from dictionary
    """
    return {k: v for k, v in data.items() if k not in keys}


def pick_keys(data: Dict, keys: List[str]) -> Dict:
    """
    Pick specific keys from dictionary
    """
    return {k: v for k, v in data.items() if k in keys}


# ============================================
# LIST HELPERS
# ============================================

def chunk_list(lst: List, chunk_size: int) -> List[List]:
    """
    Split list into chunks
    """
    return [lst[i:i + chunk_size] for i in range(0, len(lst), chunk_size)]


def unique_list(lst: List, key: callable = None) -> List:
    """
    Get unique items from list
    """
    if key:
        seen = set()
        result = []
        for item in lst:
            item_key = key(item)
            if item_key not in seen:
                seen.add(item_key)
                result.append(item)
        return result
    return list(dict.fromkeys(lst))


# ============================================
# NUMBER HELPERS
# ============================================

def round_km(value: float, decimals: int = 2) -> float:
    """
    Round kilometers to specified decimals
    """
    return round(value, decimals)


def format_percentage(value: float, decimals: int = 1) -> str:
    """
    Format as percentage string
    """
    return f"{value:.{decimals}f}%"


def format_currency(amount: float, currency: str = "₹") -> str:
    """
    Format as currency string
    """
    return f"{currency}{amount:,.2f}"


# ============================================
# HASHING HELPERS
# ============================================

def hash_string(text: str, algorithm: str = "sha256") -> str:
    """
    Hash a string using specified algorithm
    """
    if algorithm == "md5":
        return hashlib.md5(text.encode()).hexdigest()
    elif algorithm == "sha256":
        return hashlib.sha256(text.encode()).hexdigest()
    elif algorithm == "sha512":
        return hashlib.sha512(text.encode()).hexdigest()
    else:
        return hashlib.sha256(text.encode()).hexdigest()


def verify_hmac_signature(data: str, signature: str, secret: str) -> bool:
    """
    Verify HMAC signature
    """
    expected = hmac.new(
        secret.encode(),
        data.encode(),
        hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


# ============================================
# EXPORTS
# ============================================

__all__ = [
    # Date/Time Helpers
    'format_datetime',
    'format_duration',
    'get_current_ist',
    'time_ago',
    
    # String Helpers
    'generate_random_string',
    'truncate_string',
    'slugify',
    'validate_email_format',
    'validate_phone_format',
    
    # Distance/Geo Helpers
    'calculate_distance',
    'calculate_bearing',
    'midpoint',
    'is_point_in_polygon',
    
    # JSON/Data Helpers
    'safe_json_parse',
    'safe_json_dumps',
    'deep_merge',
    
    # Response Helpers
    'success_response',
    'error_response',
    'paginated_response',
    
    # Token/ID Helpers
    'generate_uuid',
    'generate_otp',
    'generate_tracking_id',
    
    # File Helpers
    'allowed_file',
    'get_file_extension',
    'unique_filename',
    
    # Network Helpers
    'get_client_ip',
    'is_safe_url',
    
    # Cache Helpers
    'cache_key',
    'invalidate_cache_pattern',
    
    # Logging Helpers
    'log_error',
    'log_api_call',
    
    # Dictionary Helpers
    'filter_dict',
    'exclude_keys',
    'pick_keys',
    
    # List Helpers
    'chunk_list',
    'unique_list',
    
    # Number Helpers
    'round_km',
    'format_percentage',
    'format_currency',
    
    # Hashing Helpers
    'hash_string',
    'verify_hmac_signature'
]