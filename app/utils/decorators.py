"""
Smart Emergency Vehicle Priority System - Custom Decorators
Provides decorators for authentication, rate limiting, caching,
logging, error handling, and other cross-cutting concerns
"""

import functools
import time
import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from functools import wraps
from loguru import logger

from flask import request, jsonify, current_app, g
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from app.extensions import cache, limiter

# ============================================
# AUTHENTICATION DECORATORS
# ============================================

def role_required(*allowed_roles):
    """
    Decorator to check if user has required role
    Usage: @role_required('admin', 'control_room')
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            try:
                # Verify JWT token first
                verify_jwt_in_request()
                current_user_id = get_jwt_identity()
                
                # Get user role from token claims or database
                # For now, get from JWT claims
                from flask_jwt_extended import get_jwt
                claims = get_jwt()
                user_role = claims.get('role')
                
                if user_role not in allowed_roles and 'super_admin' not in allowed_roles:
                    return jsonify({
                        'error': 'Permission denied',
                        'message': f'Role {user_role} does not have access to this resource'
                    }), 403
                
                return f(*args, **kwargs)
                
            except Exception as e:
                return jsonify({
                    'error': 'Authentication required',
                    'message': str(e)
                }), 401
        
        return decorated_function
    return decorator


def permission_required(permission: str):
    """
    Decorator to check if user has specific permission
    Usage: @permission_required('manage_users')
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            try:
                verify_jwt_in_request()
                claims = get_jwt()
                user_permissions = claims.get('permissions', [])
                
                if permission not in user_permissions:
                    return jsonify({
                        'error': 'Permission denied',
                        'message': f'Permission {permission} required'
                    }), 403
                
                return f(*args, **kwargs)
                
            except Exception as e:
                return jsonify({
                    'error': 'Authentication required',
                    'message': str(e)
                }), 401
        
        return decorated_function
    return decorator


def public_endpoint(f):
    """
    Decorator for public endpoints (no authentication required)
    Usage: @public_endpoint
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # No authentication check
        return f(*args, **kwargs)
    return decorated_function


def api_endpoint(version: str = "v1"):
    """
    Decorator for API endpoints with version tracking
    Usage: @api_endpoint(version="v1")
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Add API version header
            response = f(*args, **kwargs)
            
            if isinstance(response, tuple):
                response_data, status_code = response
                if isinstance(response_data, dict):
                    response_data['api_version'] = version
                    return response_data, status_code
            
            return response
        
        return decorated_function
    return decorator


# ============================================
# RATE LIMITING DECORATORS
# ============================================

def rate_limit(limit: str, key_func: callable = None):
    """
    Custom rate limiting decorator
    Usage: @rate_limit("100 per minute")
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Use Flask-Limiter's decorator
            if key_func:
                return limiter.limit(limit, key_func=key_func)(f)(*args, **kwargs)
            return limiter.limit(limit)(f)(*args, **kwargs)
        
        return decorated_function
    return decorator


def user_rate_limit(limit: str):
    """
    Rate limit per user
    Usage: @user_rate_limit("10 per minute")
    """
    def get_user_key():
        try:
            verify_jwt_in_request()
            user_id = get_jwt_identity()
            return f"user_{user_id}"
        except:
            return request.remote_addr
    
    return rate_limit(limit, key_func=get_user_key)


def ip_rate_limit(limit: str):
    """
    Rate limit per IP address
    Usage: @ip_rate_limit("50 per minute")
    """
    def get_ip_key():
        return request.remote_addr
    
    return rate_limit(limit, key_func=get_ip_key)


# ============================================
# CACHE DECORATORS
# ============================================

def cached(timeout: int = 300, key_prefix: str = None):
    """
    Cache decorator for functions
    Usage: @cached(timeout=60)
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Generate cache key
            cache_key = key_prefix
            if not cache_key:
                cache_key = f"{f.__module__}.{f.__name__}"
                if args:
                    cache_key += f":{args}"
                if kwargs:
                    cache_key += f":{sorted(kwargs.items())}"
            
            # Try to get from cache
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                return cached_value
            
            # Execute function and cache result
            result = f(*args, **kwargs)
            cache.set(cache_key, result, timeout=timeout)
            return result
        
        return decorated_function
    return decorator


def cached_response(timeout: int = 300):
    """
    Cache decorator for Flask response objects
    Usage: @cached_response(timeout=60)
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            # Generate cache key from request path and query params
            cache_key = f"response:{request.path}:{request.args}"
            
            # Try to get from cache
            cached_value = cache.get(cache_key)
            if cached_value is not None:
                return cached_value
            
            # Execute function and cache response
            response = f(*args, **kwargs)
            
            # Only cache successful responses
            if response.status_code == 200:
                cache.set(cache_key, response, timeout=timeout)
            
            return response
        
        return decorated_function
    return decorator


# ============================================
# LOGGING DECORATORS
# ============================================

def log_execution_time(log_level: str = "INFO"):
    """
    Log function execution time
    Usage: @log_execution_time()
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            start_time = time.time()
            result = f(*args, **kwargs)
            end_time = time.time()
            duration_ms = (end_time - start_time) * 1000
            
            log_func = logger.info
            if log_level == "DEBUG":
                log_func = logger.debug
            elif log_level == "WARNING":
                log_func = logger.warning
            
            log_func(f"{f.__name__} took {duration_ms:.2f}ms")
            return result
        
        return decorated_function
    return decorator


def log_function_call(log_args: bool = True, log_result: bool = False):
    """
    Log function calls with arguments and results
    Usage: @log_function_call()
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            call_info = f"Calling {f.__name__}"
            
            if log_args:
                if args:
                    call_info += f" with args: {args[:5]}"  # Limit args
                if kwargs:
                    call_info += f" with kwargs: {kwargs}"
            
            logger.debug(call_info)
            
            result = f(*args, **kwargs)
            
            if log_result:
                logger.debug(f"{f.__name__} returned: {str(result)[:200]}")
            
            return result
        
        return decorated_function
    return decorator


# ============================================
# VALIDATION DECORATORS
# ============================================

def validate_json_schema(schema: Dict):
    """
    Validate request JSON against schema
    Usage: @validate_json_schema(user_schema)
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
            
            # Basic schema validation
            for required_field in schema.get('required', []):
                if required_field not in data:
                    return jsonify({
                        'error': 'Validation error',
                        'message': f'Missing required field: {required_field}'
                    }), 400
            
            # Type validation
            properties = schema.get('properties', {})
            for field, field_schema in properties.items():
                if field in data:
                    field_type = field_schema.get('type')
                    if field_type == 'string' and not isinstance(data[field], str):
                        return jsonify({
                            'error': 'Validation error',
                            'message': f'Field {field} must be a string'
                        }), 400
                    elif field_type == 'number' and not isinstance(data[field], (int, float)):
                        return jsonify({
                            'error': 'Validation error',
                            'message': f'Field {field} must be a number'
                        }), 400
                    elif field_type == 'integer' and not isinstance(data[field], int):
                        return jsonify({
                            'error': 'Validation error',
                            'message': f'Field {field} must be an integer'
                        }), 400
                    elif field_type == 'boolean' and not isinstance(data[field], bool):
                        return jsonify({
                            'error': 'Validation error',
                            'message': f'Field {field} must be a boolean'
                        }), 400
            
            g.validated_data = data
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator


def validate_query_params(schema: Dict):
    """
    Validate query parameters against schema
    Usage: @validate_query_params({'page': {'type': 'int'}})
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            errors = []
            validated_params = {}
            
            for param, param_schema in schema.items():
                value = request.args.get(param)
                
                if param_schema.get('required') and value is None:
                    errors.append(f"Missing required query parameter: {param}")
                    continue
                
                if value is not None:
                    param_type = param_schema.get('type', 'string')
                    
                    if param_type == 'int':
                        try:
                            value = int(value)
                            validated_params[param] = value
                        except ValueError:
                            errors.append(f"Parameter {param} must be an integer")
                    
                    elif param_type == 'float':
                        try:
                            value = float(value)
                            validated_params[param] = value
                        except ValueError:
                            errors.append(f"Parameter {param} must be a float")
                    
                    elif param_type == 'bool':
                        value = value.lower() in ['true', '1', 'yes']
                        validated_params[param] = value
                    
                    else:
                        validated_params[param] = value
            
            if errors:
                return jsonify({
                    'error': 'Validation error',
                    'message': 'Invalid query parameters',
                    'errors': errors
                }), 400
            
            g.validated_params = validated_params
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator


# ============================================
# ERROR HANDLING DECORATORS
# ============================================

def handle_errors(default_message: str = "Internal server error"):
    """
    Handle exceptions in decorated function
    Usage: @handle_errors()
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            try:
                return f(*args, **kwargs)
            except Exception as e:
                logger.error(f"Error in {f.__name__}: {str(e)}")
                
                return jsonify({
                    'error': 'Internal server error',
                    'message': default_message,
                    'type': e.__class__.__name__
                }), 500
        
        return decorated_function
    return decorator


def retry_on_failure(max_retries: int = 3, delay_seconds: float = 1.0, backoff: float = 2.0):
    """
    Retry function on failure
    Usage: @retry_on_failure(max_retries=3)
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            last_exception = None
            current_delay = delay_seconds
            
            for attempt in range(max_retries):
                try:
                    return f(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        time.sleep(current_delay)
                        current_delay *= backoff
            
            logger.error(f"Failed after {max_retries} retries: {last_exception}")
            raise last_exception
        
        return decorated_function
    return decorator


# ============================================
# ASYNC DECORATORS
# ============================================

def async_task(f):
    """
    Run function as async background task
    Usage: @async_task
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        def run_task():
            try:
                result = f(*args, **kwargs)
                logger.debug(f"Async task {f.__name__} completed: {result}")
            except Exception as e:
                logger.error(f"Async task {f.__name__} failed: {e}")
        
        thread = threading.Thread(target=run_task)
        thread.daemon = True
        thread.start()
        
        return {"message": "Task started", "task": f.__name__}
    
    return decorated_function


def background_task(f):
    """
    Run function as background task (alias for async_task)
    """
    return async_task(f)


# ============================================
# DATABASE DECORATORS
# ============================================

def transactional(f):
    """
    Wrap function in database transaction
    Usage: @transactional
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        from app.extensions import db
        
        try:
            result = f(*args, **kwargs)
            db.session.commit()
            return result
        except Exception as e:
            db.session.rollback()
            logger.error(f"Transaction failed in {f.__name__}: {e}")
            raise e
    
    return decorated_function


def master_only(f):
    """
    Ensure operation uses master database
    Usage: @master_only
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # In production, would switch to master DB connection
        return f(*args, **kwargs)
    
    return decorated_function


def replica_only(f):
    """
    Ensure operation uses replica database
    Usage: @replica_only
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # In production, would switch to replica DB connection
        return f(*args, **kwargs)
    
    return decorated_function


# ============================================
# PERFORMANCE DECORATORS
# ============================================

def profile(f):
    """
    Profile function performance
    Usage: @profile
    """
    @wraps(f)
    def decorated_function(*args, **kwargs):
        import cProfile
        import pstats
        import io
        
        profiler = cProfile.Profile()
        profiler.enable()
        
        result = f(*args, **kwargs)
        
        profiler.disable()
        stream = io.StringIO()
        stats = pstats.Stats(profiler, stream=stream)
        stats.sort_stats('cumulative')
        stats.print_stats(20)
        
        logger.debug(f"Profile for {f.__name__}:\n{stream.getvalue()}")
        return result
    
    return decorated_function


def slow_down(delay_seconds: float = 0.1):
    """
    Add artificial delay (for testing)
    Usage: @slow_down(0.5)
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            time.sleep(delay_seconds)
            return f(*args, **kwargs)
        
        return decorated_function
    return decorator


# ============================================
# DEPRECATION DECORATOR
# ============================================

def deprecated(replacement: str = None):
    """
    Mark function as deprecated
    Usage: @deprecated(replacement="new_function")
    """
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            message = f"Warning: {f.__name__} is deprecated"
            if replacement:
                message += f". Use {replacement} instead"
            
            logger.warning(message)
            
            # Add deprecation warning header if Flask response
            response = f(*args, **kwargs)
            if hasattr(response, 'headers'):
                response.headers['X-Deprecated'] = f.__name__
            
            return response
        
        return decorated_function
    return decorator


# ============================================
# EXPORTS
# ============================================

__all__ = [
    # Authentication
    'role_required',
    'permission_required',
    'public_endpoint',
    'api_endpoint',
    
    # Rate Limiting
    'rate_limit',
    'user_rate_limit',
    'ip_rate_limit',
    
    # Caching
    'cached',
    'cached_response',
    
    # Logging
    'log_execution_time',
    'log_function_call',
    
    # Validation
    'validate_json_schema',
    'validate_query_params',
    
    # Error Handling
    'handle_errors',
    'retry_on_failure',
    
    # Async
    'async_task',
    'background_task',
    
    # Database
    'transactional',
    'master_only',
    'replica_only',
    
    # Performance
    'profile',
    'slow_down',
    
    # Deprecation
    'deprecated'
]

# Required import for threading
import threading