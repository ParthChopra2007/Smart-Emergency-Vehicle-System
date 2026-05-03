"""
Smart Emergency Vehicle Priority System - Authentication Routes
Handles user registration, login, logout, token refresh, and profile management
"""

from flask import Blueprint, request, jsonify, current_app
from flask_jwt_extended import (
    create_access_token, 
    create_refresh_token,
    jwt_required, 
    get_jwt_identity,
    get_jwt,
    set_access_cookies,
    set_refresh_cookies,
    unset_jwt_cookies
)
from datetime import datetime, timedelta
from loguru import logger
import re
from functools import wraps

from app.extensions import db, limiter
from app.models.user import (
    User, 
    UserRole, 
    UserStatus, 
    TokenBlocklist,
    UserSession,
    find_user_by_email,
    find_user_by_username,
    find_user_by_id
)

# Create Blueprint
auth_bp = Blueprint('auth', __name__)

# ============================================
# HELPER FUNCTIONS
# ============================================

def validate_email(email):
    """Validate email format"""
    email_regex = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
    return re.match(email_regex, email) is not None

def validate_password(password):
    """
    Validate password strength
    At least 8 characters, 1 uppercase, 1 lowercase, 1 number, 1 special character
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
    
    return True, "Password is valid"

def validate_username(username):
    """Validate username format"""
    if len(username) < 3 or len(username) > 50:
        return False, "Username must be between 3 and 50 characters"
    
    if not re.match(r'^[a-zA-Z0-9_.-]+$', username):
        return False, "Username can only contain letters, numbers, dots, underscores, and hyphens"
    
    return True, "Username is valid"

def get_client_ip():
    """Get client IP address from request"""
    if request.headers.get('X-Forwarded-For'):
        return request.headers.get('X-Forwarded-For').split(',')[0]
    return request.remote_addr

def get_user_agent():
    """Get user agent from request"""
    return request.headers.get('User-Agent', 'Unknown')

# ============================================
# CUSTOM DECORATORS
# ============================================

def role_required(*allowed_roles):
    """Decorator to check if user has required role"""
    def decorator(f):
        @wraps(f)
        @jwt_required()
        def decorated_function(*args, **kwargs):
            current_user_id = get_jwt_identity()
            user = find_user_by_id(current_user_id)
            
            if not user:
                return jsonify({'error': 'User not found'}), 404
            
            if user.role.value not in allowed_roles and 'admin' not in allowed_roles:
                return jsonify({
                    'error': 'Permission denied',
                    'message': f'Role {user.role.value} does not have access to this resource'
                }), 403
            
            return f(*args, **kwargs)
        return decorated_function
    return decorator

# ============================================
# PUBLIC ROUTES (No authentication required)
# ============================================

@auth_bp.route('/register', methods=['POST'])
@limiter.limit("5 per hour")  # Prevent spam registrations
def register():
    """
    Register a new user
    POST /api/v1/auth/register
    Body: {
        "email": "user@example.com",
        "username": "john_doe",
        "full_name": "John Doe",
        "password": "StrongP@ss123",
        "phone_number": "+1234567890",
        "role": "viewer"  # optional, default is viewer
    }
    """
    try:
        data = request.get_json()
        
        # Validate required fields
        required_fields = ['email', 'username', 'full_name', 'password']
        for field in required_fields:
            if not data.get(field):
                return jsonify({
                    'error': 'Missing required field',
                    'message': f'{field} is required'
                }), 400
        
        email = data['email'].lower()
        username = data['username']
        full_name = data['full_name']
        password = data['password']
        phone_number = data.get('phone_number')
        role_str = data.get('role', 'viewer')
        
        # Validate email format
        if not validate_email(email):
            return jsonify({
                'error': 'Invalid email',
                'message': 'Please provide a valid email address'
            }), 400
        
        # Validate username
        is_valid, message = validate_username(username)
        if not is_valid:
            return jsonify({
                'error': 'Invalid username',
                'message': message
            }), 400
        
        # Validate password strength
        is_valid, message = validate_password(password)
        if not is_valid:
            return jsonify({
                'error': 'Weak password',
                'message': message
            }), 400
        
        # Check if email already exists
        if find_user_by_email(email):
            return jsonify({
                'error': 'Email already registered',
                'message': 'This email is already in use'
            }), 409
        
        # Check if username already exists
        if find_user_by_username(username):
            return jsonify({
                'error': 'Username taken',
                'message': 'This username is already taken'
            }), 409
        
        # Validate role (only allow non-admin roles for self-registration)
        allowed_roles = ['viewer', 'emergency_driver']
        if role_str not in allowed_roles:
            role_str = 'viewer'
        
        role = UserRole(role_str)
        
        # Create new user
        user = User(
            email=email,
            username=username,
            full_name=full_name,
            password=password,
            phone_number=phone_number,
            role=role,
            status=UserStatus.ACTIVE
        )
        
        db.session.add(user)
        db.session.commit()
        
        logger.info(f"New user registered: {email} ({role_str})")
        
        # Generate tokens
        tokens = user.get_jwt_tokens()
        
        # Create session
        session_token = tokens['access_token'][:50]  # Use part of access token as session ID
        UserSession.create_session(
            user_id=user.id,
            session_token=session_token,
            ip_address=get_client_ip(),
            user_agent=get_user_agent(),
            expires_at=datetime.utcnow() + timedelta(days=7)
        )
        
        return jsonify({
            'success': True,
            'message': 'User registered successfully',
            'user': user.to_dict(),
            'tokens': tokens
        }), 201
        
    except Exception as e:
        logger.error(f"Registration error: {str(e)}")
        db.session.rollback()
        return jsonify({
            'error': 'Registration failed',
            'message': 'An error occurred during registration'
        }), 500


@auth_bp.route('/login', methods=['POST'])
@limiter.limit("10 per minute")  # Rate limiting to prevent brute force
def login():
    """
    Login user and return JWT tokens
    POST /api/v1/auth/login
    Body: {
        "email_or_username": "user@example.com or john_doe",
        "password": "StrongP@ss123"
    }
    """
    try:
        data = request.get_json()
        
        if not data.get('email_or_username') or not data.get('password'):
            return jsonify({
                'error': 'Missing credentials',
                'message': 'Both email/username and password are required'
            }), 400
        
        identifier = data['email_or_username']
        password = data['password']
        
        # Find user by email or username
        user = find_user_by_email(identifier)
        if not user:
            user = find_user_by_username(identifier)
        
        if not user:
            logger.warning(f"Login failed: User not found - {identifier}")
            return jsonify({
                'error': 'Invalid credentials',
                'message': 'Invalid email/username or password'
            }), 401
        
        # Check if account is locked
        if user.locked_until and user.locked_until > datetime.utcnow():
            remaining_minutes = (user.locked_until - datetime.utcnow()).seconds // 60
            return jsonify({
                'error': 'Account locked',
                'message': f'Too many failed attempts. Try again in {remaining_minutes} minutes'
            }), 423
        
        # Check password
        if not user.check_password(password):
            # Record failed attempt
            user.record_login_attempt(success=False, ip_address=get_client_ip())
            remaining_attempts = 5 - user.login_attempts
            return jsonify({
                'error': 'Invalid credentials',
                'message': f'Invalid password. {remaining_attempts} attempts remaining'
            }), 401
        
        # Check if account is active
        if not user.is_active():
            return jsonify({
                'error': 'Account inactive',
                'message': f'Your account is {user.status.value}. Please contact support.'
            }), 403
        
        # Record successful login
        user.record_login_attempt(success=True, ip_address=get_client_ip())
        
        # Generate tokens
        tokens = user.get_jwt_tokens()
        
        # Create session
        session_token = tokens['access_token'][:50]
        UserSession.create_session(
            user_id=user.id,
            session_token=session_token,
            ip_address=get_client_ip(),
            user_agent=get_user_agent(),
            expires_at=datetime.utcnow() + timedelta(days=7)
        )
        
        logger.info(f"User logged in: {user.email} from IP {get_client_ip()}")
        
        # Prepare response
        response_data = {
            'success': True,
            'message': 'Login successful',
            'user': user.to_dict(),
            'tokens': tokens
        }
        
        # If using cookie-based auth (optional)
        response = jsonify(response_data)
        # set_access_cookies(response, tokens['access_token'])
        # set_refresh_cookies(response, tokens['refresh_token'])
        
        return response, 200
        
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        return jsonify({
            'error': 'Login failed',
            'message': 'An error occurred during login'
        }), 500


@auth_bp.route('/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh_token():
    """
    Refresh access token using refresh token
    POST /api/v1/auth/refresh
    """
    try:
        current_user_id = get_jwt_identity()
        user = find_user_by_id(current_user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        if not user.is_active():
            return jsonify({'error': 'Account is inactive'}), 403
        
        # Create new access token
        new_access_token = create_access_token(
            identity=user.id,
            additional_claims={
                'user_id': user.id,
                'email': user.email,
                'username': user.username,
                'role': user.role.value if user.role else None,
                'full_name': user.full_name
            },
            expires_delta=timedelta(hours=1)
        )
        
        logger.info(f"Token refreshed for user: {user.email}")
        
        return jsonify({
            'success': True,
            'access_token': new_access_token,
            'expires_in': 3600
        }), 200
        
    except Exception as e:
        logger.error(f"Token refresh error: {str(e)}")
        return jsonify({
            'error': 'Token refresh failed',
            'message': 'Could not refresh token'
        }), 500


# ============================================
# PROTECTED ROUTES (Authentication required)
# ============================================

@auth_bp.route('/logout', methods=['POST'])
@jwt_required()
def logout():
    """
    Logout user - revoke current token
    POST /api/v1/auth/logout
    """
    try:
        jti = get_jwt()['jti']
        token_type = get_jwt()['type']
        user_id = get_jwt_identity()
        expires_at = datetime.fromtimestamp(get_jwt()['exp'])
        
        # Revoke the token
        TokenBlocklist.revoke_token(
            jti=jti,
            token_type=token_type,
            user_id=user_id,
            expires_at=expires_at,
            ip_address=get_client_ip()
        )
        
        # Terminate user session
        session_token = request.headers.get('Authorization', '').replace('Bearer ', '')[:50]
        session = UserSession.query.filter_by(session_token=session_token, user_id=user_id).first()
        if session:
            session.terminate()
        
        logger.info(f"User logged out: {user_id}")
        
        # Clear cookies if using cookie-based auth
        response = jsonify({
            'success': True,
            'message': 'Logged out successfully'
        })
        # unset_jwt_cookies(response)
        
        return response, 200
        
    except Exception as e:
        logger.error(f"Logout error: {str(e)}")
        return jsonify({
            'error': 'Logout failed',
            'message': 'An error occurred during logout'
        }), 500


@auth_bp.route('/logout-all', methods=['POST'])
@jwt_required()
def logout_all_devices():
    """
    Logout from all devices - revoke all user tokens
    POST /api/v1/auth/logout-all
    """
    try:
        user_id = get_jwt_identity()
        
        # Revoke all active sessions for this user
        sessions = UserSession.query.filter_by(user_id=user_id, is_active=True).all()
        for session in sessions:
            session.terminate()
        
        # Revoke all non-expired tokens for this user
        # Note: This requires storing all tokens, which we don't do by default
        # Alternative: Just mark all sessions as terminated
        
        logger.info(f"User logged out from all devices: {user_id}")
        
        return jsonify({
            'success': True,
            'message': f'Logged out from {len(sessions)} device(s)'
        }), 200
        
    except Exception as e:
        logger.error(f"Logout all error: {str(e)}")
        return jsonify({
            'error': 'Logout failed',
            'message': 'An error occurred'
        }), 500


@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def get_current_user():
    """
    Get current logged-in user information
    GET /api/v1/auth/me
    """
    try:
        user_id = get_jwt_identity()
        user = find_user_by_id(user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        return jsonify({
            'success': True,
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        logger.error(f"Get current user error: {str(e)}")
        return jsonify({
            'error': 'Failed to get user info',
            'message': 'An error occurred'
        }), 500


@auth_bp.route('/me', methods=['PUT'])
@jwt_required()
def update_current_user():
    """
    Update current user profile
    PUT /api/v1/auth/me
    Body: {
        "full_name": "Updated Name",
        "phone_number": "+9876543210",
        "notification_enabled": true
    }
    """
    try:
        user_id = get_jwt_identity()
        user = find_user_by_id(user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        data = request.get_json()
        
        # Update allowed fields
        allowed_fields = ['full_name', 'phone_number', 'notification_enabled', 
                         'email_notifications', 'sms_notifications']
        
        for field in allowed_fields:
            if field in data:
                setattr(user, field, data[field])
        
        # If updating location
        if 'current_location' in data:
            location = data['current_location']
            if 'latitude' in location and 'longitude' in location:
                user.update_location(location['latitude'], location['longitude'])
        
        db.session.commit()
        
        logger.info(f"User profile updated: {user.email}")
        
        return jsonify({
            'success': True,
            'message': 'Profile updated successfully',
            'user': user.to_dict()
        }), 200
        
    except Exception as e:
        logger.error(f"Update user error: {str(e)}")
        db.session.rollback()
        return jsonify({
            'error': 'Update failed',
            'message': 'An error occurred'
        }), 500


@auth_bp.route('/me/password', methods=['PUT'])
@jwt_required()
def change_password():
    """
    Change current user password
    PUT /api/v1/auth/me/password
    Body: {
        "current_password": "OldP@ss123",
        "new_password": "NewP@ss456"
    }
    """
    try:
        user_id = get_jwt_identity()
        user = find_user_by_id(user_id)
        
        if not user:
            return jsonify({'error': 'User not found'}), 404
        
        data = request.get_json()
        
        if not data.get('current_password') or not data.get('new_password'):
            return jsonify({
                'error': 'Missing fields',
                'message': 'Current password and new password are required'
            }), 400
        
        # Verify current password
        if not user.check_password(data['current_password']):
            return jsonify({
                'error': 'Invalid password',
                'message': 'Current password is incorrect'
            }), 401
        
        # Validate new password strength
        is_valid, message = validate_password(data['new_password'])
        if not is_valid:
            return jsonify({
                'error': 'Weak password',
                'message': message
            }), 400
        
        # Update password
        user.set_password(data['new_password'])
        db.session.commit()
        
        logger.info(f"Password changed for user: {user.email}")
        
        return jsonify({
            'success': True,
            'message': 'Password changed successfully'
        }), 200
        
    except Exception as e:
        logger.error(f"Change password error: {str(e)}")
        db.session.rollback()
        return jsonify({
            'error': 'Password change failed',
            'message': 'An error occurred'
        }), 500


@auth_bp.route('/me/sessions', methods=['GET'])
@jwt_required()
def get_my_sessions():
    """
    Get all active sessions for current user
    GET /api/v1/auth/me/sessions
    """
    try:
        user_id = get_jwt_identity()
        
        sessions = UserSession.query.filter_by(
            user_id=user_id, 
            is_active=True
        ).order_by(UserSession.last_activity.desc()).all()
        
        sessions_data = []
        for session in sessions:
            sessions_data.append({
                'id': session.id,
                'ip_address': session.ip_address,
                'user_agent': session.user_agent,
                'created_at': session.created_at.isoformat(),
                'last_activity': session.last_activity.isoformat(),
                'expires_at': session.expires_at.isoformat()
            })
        
        return jsonify({
            'success': True,
            'sessions': sessions_data,
            'total': len(sessions_data)
        }), 200
        
    except Exception as e:
        logger.error(f"Get sessions error: {str(e)}")
        return jsonify({
            'error': 'Failed to get sessions',
            'message': 'An error occurred'
        }), 500


@auth_bp.route('/me/sessions/<int:session_id>', methods=['DELETE'])
@jwt_required()
def terminate_session(session_id):
    """
    Terminate a specific session
    DELETE /api/v1/auth/me/sessions/<session_id>
    """
    try:
        user_id = get_jwt_identity()
        
        session = UserSession.query.filter_by(
            id=session_id, 
            user_id=user_id
        ).first()
        
        if not session:
            return jsonify({'error': 'Session not found'}), 404
        
        session.terminate()
        
        logger.info(f"Session {session_id} terminated for user {user_id}")
        
        return jsonify({
            'success': True,
            'message': 'Session terminated successfully'
        }), 200
        
    except Exception as e:
        logger.error(f"Terminate session error: {str(e)}")
        return jsonify({
            'error': 'Failed to terminate session',
            'message': 'An error occurred'
        }), 500


# ============================================
# PASSWORD RESET ROUTES (Email based)
# ============================================

@auth_bp.route('/forgot-password', methods=['POST'])
@limiter.limit("3 per hour")
def forgot_password():
    """
    Request password reset email
    POST /api/v1/auth/forgot-password
    Body: {"email": "user@example.com"}
    """
    try:
        data = request.get_json()
        email = data.get('email', '').lower()
        
        if not email:
            return jsonify({'error': 'Email is required'}), 400
        
        user = find_user_by_email(email)
        
        # Always return success even if user not found (security)
        if user:
            # Generate password reset token
            reset_token = jwt.encode(
                {
                    'user_id': user.id,
                    'exp': datetime.utcnow() + timedelta(hours=1)
                },
                current_app.config['SECRET_KEY'],
                algorithm='HS256'
            )
            
            # Store token in database (simplified - you'd want to store in a password_resets table)
            # For now, we'll just log it
            logger.info(f"Password reset requested for {email}. Token: {reset_token}")
            
            # TODO: Send email with reset link
            # reset_link = f"http://localhost:5000/reset-password?token={reset_token}"
            
        # Always return success to prevent email enumeration
        return jsonify({
            'success': True,
            'message': 'If an account exists with this email, you will receive a password reset link'
        }), 200
        
    except Exception as e:
        logger.error(f"Forgot password error: {str(e)}")
        return jsonify({
            'error': 'Request failed',
            'message': 'An error occurred'
        }), 500


# ============================================
# VERIFICATION ROUTES
# ============================================

@auth_bp.route('/verify-token', methods=['POST'])
@jwt_required()
def verify_token():
    """
    Verify if current token is valid
    POST /api/v1/auth/verify-token
    """
    try:
        user_id = get_jwt_identity()
        user = find_user_by_id(user_id)
        
        if not user:
            return jsonify({'valid': False, 'message': 'User not found'}), 401
        
        if not user.is_active():
            return jsonify({'valid': False, 'message': 'Account inactive'}), 401
        
        return jsonify({
            'valid': True,
            'user_id': user_id,
            'email': user.email,
            'role': user.role.value if user.role else None
        }), 200
        
    except Exception as e:
        return jsonify({'valid': False, 'message': str(e)}), 401


# ============================================
# EXPORTS
# ============================================

__all__ = ['auth_bp', 'role_required']