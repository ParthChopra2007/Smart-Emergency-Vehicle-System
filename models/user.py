"""
Smart Emergency Vehicle Priority System - User Model
This file defines the User, Role, and TokenBlocklist models for authentication and authorization
"""

from datetime import datetime, timedelta
from flask import current_app
from flask_jwt_extended import create_access_token, create_refresh_token
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum, Float, JSON
from sqlalchemy.orm import relationship
import enum
import jwt
from app.extensions import db, bcrypt
from loguru import logger

# ============================================
# ENUMS (Choices for dropdown fields)
# ============================================

class UserRole(enum.Enum):
    """User roles for role-based access control (RBAC)"""
    ADMIN = "admin"           # Full system access
    CONTROL_ROOM = "control_room"  # Can view dashboard and manage corridors
    EMERGENCY_DRIVER = "emergency_driver"  # Ambulance/Fire/Police driver
    TRAFFIC_OFFICER = "traffic_officer"   # Can manually control signals
    VIEWER = "viewer"         # Read-only access
    SUPER_ADMIN = "super_admin"  # Highest privilege

class UserStatus(enum.Enum):
    """User account status"""
    ACTIVE = "active"
    INACTIVE = "inactive"
    SUSPENDED = "suspended"
    DELETED = "deleted"

class VehicleType(enum.Enum):
    """Types of emergency vehicles"""
    AMBULANCE = "ambulance"
    FIRE_BRIGADE = "fire_brigade"
    POLICE = "police"
    DISASTER_MANAGEMENT = "disaster_management"

# ============================================
# USER MODEL (Main authentication model)
# ============================================

class User(db.Model):
    """
    User model for authentication and authorization
    Stores user information, credentials, and permissions
    """
    __tablename__ = 'users'
    __table_args__ = (
        db.Index('idx_user_email', 'email'),
        db.Index('idx_user_role', 'role'),
        db.Index('idx_user_status', 'status'),
        {'schema': 'public'}
    )

    # Basic Information
    id = Column(Integer, primary_key=True)
    email = Column(String(255), unique=True, nullable=False, index=True)
    username = Column(String(100), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    
    # Personal Information
    full_name = Column(String(255), nullable=False)
    phone_number = Column(String(20), nullable=True)
    profile_picture = Column(String(500), nullable=True)
    
    # Role and Permissions
    role = Column(Enum(UserRole), default=UserRole.VIEWER, nullable=False)
    status = Column(Enum(UserStatus), default=UserStatus.ACTIVE, nullable=False)
    
    # Location Information (for control room and drivers)
    current_latitude = Column(Float, nullable=True)
    current_longitude = Column(Float, nullable=True)
    last_location_update = Column(DateTime, nullable=True)
    
    # Organization/Department
    department = Column(String(255), nullable=True)  # e.g., "City Police", "Fire Department"
    employee_id = Column(String(100), nullable=True)
    
    # Emergency Vehicle Association (if driver)
    assigned_vehicle_id = Column(Integer, db.ForeignKey('emergency_vehicles.id'), nullable=True)
    
    # Preferences
    notification_enabled = Column(Boolean, default=True)
    email_notifications = Column(Boolean, default=True)
    sms_notifications = Column(Boolean, default=False)
    
    # Activity Tracking
    last_login = Column(DateTime, nullable=True)
    last_ip_address = Column(String(45), nullable=True)
    login_attempts = Column(Integer, default=0)
    locked_until = Column(DateTime, nullable=True)
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(Integer, nullable=True)  # Admin who created this user
    notes = Column(db.Text, nullable=True)
    
    # JSON field for additional data
    metadata = Column(JSON, default={})
    
    # Relationships
    assigned_vehicle = relationship("EmergencyVehicle", back_populates="assigned_driver", foreign_keys=[assigned_vehicle_id])
    created_corridors = relationship("GreenCorridor", back_populates="requested_by", foreign_keys="GreenCorridor.requested_by_id")
    audit_logs = relationship("AuditLog", back_populates="user")
    
    def __init__(self, email, username, full_name, password, **kwargs):
        self.email = email.lower()
        self.username = username
        self.full_name = full_name
        self.set_password(password)
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    def set_password(self, password):
        """Hash and set the password"""
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')
        logger.debug(f"Password set for user {self.email}")
    
    def check_password(self, password):
        """Verify the password"""
        return bcrypt.check_password_hash(self.password_hash, password)
    
    def get_full_name(self):
        """Return user's full name"""
        return self.full_name
    
    def is_active(self):
        """Check if user account is active"""
        if self.status != UserStatus.ACTIVE:
            return False
        if self.locked_until and self.locked_until > datetime.utcnow():
            return False
        return True
    
    def is_admin(self):
        """Check if user has admin privileges"""
        return self.role in [UserRole.ADMIN, UserRole.SUPER_ADMIN]
    
    def is_driver(self):
        """Check if user is an emergency vehicle driver"""
        return self.role == UserRole.EMERGENCY_DRIVER
    
    def get_permissions(self):
        """Get user permissions based on role"""
        permissions = {
            'view_dashboard': False,
            'request_corridor': False,
            'control_signals': False,
            'manage_vehicles': False,
            'manage_users': False,
            'view_analytics': False,
            'manage_system': False
        }
        
        if self.role == UserRole.VIEWER:
            permissions['view_dashboard'] = True
            permissions['view_analytics'] = True
            
        elif self.role == UserRole.EMERGENCY_DRIVER:
            permissions['view_dashboard'] = True
            permissions['request_corridor'] = True
            permissions['view_analytics'] = True
            
        elif self.role == UserRole.TRAFFIC_OFFICER:
            permissions['view_dashboard'] = True
            permissions['request_corridor'] = True
            permissions['control_signals'] = True
            permissions['view_analytics'] = True
            
        elif self.role == UserRole.CONTROL_ROOM:
            permissions['view_dashboard'] = True
            permissions['request_corridor'] = True
            permissions['control_signals'] = True
            permissions['manage_vehicles'] = True
            permissions['view_analytics'] = True
            
        elif self.role == UserRole.ADMIN:
            permissions['view_dashboard'] = True
            permissions['request_corridor'] = True
            permissions['control_signals'] = True
            permissions['manage_vehicles'] = True
            permissions['manage_users'] = True
            permissions['view_analytics'] = True
            
        elif self.role == UserRole.SUPER_ADMIN:
            permissions['view_dashboard'] = True
            permissions['request_corridor'] = True
            permissions['control_signals'] = True
            permissions['manage_vehicles'] = True
            permissions['manage_users'] = True
            permissions['view_analytics'] = True
            permissions['manage_system'] = True
            
        return permissions
    
    def get_jwt_tokens(self):
        """Generate JWT access and refresh tokens for the user"""
        additional_claims = {
            'user_id': self.id,
            'email': self.email,
            'username': self.username,
            'role': self.role.value if self.role else None,
            'full_name': self.full_name
        }
        
        access_token = create_access_token(
            identity=self.id,
            additional_claims=additional_claims,
            expires_delta=timedelta(hours=1)
        )
        
        refresh_token = create_refresh_token(
            identity=self.id,
            additional_claims=additional_claims,
            expires_delta=timedelta(days=7)
        )
        
        return {
            'access_token': access_token,
            'refresh_token': refresh_token,
            'expires_in': 3600  # 1 hour in seconds
        }
    
    def update_location(self, latitude, longitude):
        """Update user's current location"""
        self.current_latitude = latitude
        self.current_longitude = longitude
        self.last_location_update = datetime.utcnow()
        db.session.commit()
        logger.debug(f"Location updated for user {self.id}: ({latitude}, {longitude})")
    
    def record_login_attempt(self, success, ip_address=None):
        """Record login attempt for security monitoring"""
        if success:
            self.last_login = datetime.utcnow()
            self.last_ip_address = ip_address
            self.login_attempts = 0
            self.locked_until = None
        else:
            self.login_attempts += 1
            # Lock account after 5 failed attempts
            if self.login_attempts >= 5:
                self.locked_until = datetime.utcnow() + timedelta(minutes=30)
                logger.warning(f"User {self.email} locked until {self.locked_until}")
        
        db.session.commit()
    
    def to_dict(self, include_sensitive=False):
        """Convert user object to dictionary"""
        user_dict = {
            'id': self.id,
            'email': self.email,
            'username': self.username,
            'full_name': self.full_name,
            'phone_number': self.phone_number,
            'role': self.role.value if self.role else None,
            'status': self.status.value if self.status else None,
            'department': self.department,
            'employee_id': self.employee_id,
            'assigned_vehicle_id': self.assigned_vehicle_id,
            'notification_enabled': self.notification_enabled,
            'last_login': self.last_login.isoformat() if self.last_login else None,
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'permissions': self.get_permissions() if not include_sensitive else None
        }
        
        # Include sensitive info only if requested
        if include_sensitive:
            user_dict['password_hash'] = self.password_hash
            user_dict['login_attempts'] = self.login_attempts
            user_dict['locked_until'] = self.locked_until.isoformat() if self.locked_until else None
            user_dict['last_ip_address'] = self.last_ip_address
            user_dict['metadata'] = self.metadata
            user_dict['notes'] = self.notes
        
        # Include location if available
        if self.current_latitude and self.current_longitude:
            user_dict['current_location'] = {
                'latitude': self.current_latitude,
                'longitude': self.current_longitude,
                'last_update': self.last_location_update.isoformat() if self.last_location_update else None
            }
        
        return user_dict
    
    def __repr__(self):
        return f"<User {self.email} ({self.role.value if self.role else 'no role'})>"


# ============================================
# TOKEN BLOCKLIST MODEL (For logout)
# ============================================

class TokenBlocklist(db.Model):
    """
    Model to store revoked JWT tokens
    Used for logout functionality
    """
    __tablename__ = 'token_blocklist'
    
    id = Column(Integer, primary_key=True)
    jti = Column(String(36), nullable=False, unique=True, index=True)  # JWT ID
    token_type = Column(String(50), nullable=False)  # 'access' or 'refresh'
    user_id = Column(Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    revoked_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    ip_address = Column(String(45), nullable=True)
    
    # Relationship
    user = relationship("User", backref="revoked_tokens")
    
    @classmethod
    def revoke_token(cls, jti, token_type, user_id, expires_at, ip_address=None):
        """Revoke a token by adding it to blocklist"""
        token = cls(
            jti=jti,
            token_type=token_type,
            user_id=user_id,
            expires_at=expires_at,
            ip_address=ip_address
        )
        db.session.add(token)
        db.session.commit()
        logger.info(f"Token {jti} revoked for user {user_id}")
        return token
    
    @classmethod
    def is_token_revoked(cls, jti):
        """Check if a token is revoked"""
        token = cls.query.filter_by(jti=jti).first()
        if token:
            # Check if token is expired
            if token.expires_at < datetime.utcnow():
                db.session.delete(token)
                db.session.commit()
                return False
            return True
        return False
    
    def __repr__(self):
        return f"<TokenBlocklist {self.jti} for user {self.user_id}>"


# ============================================
# USER SESSION MODEL (Optional - for tracking)
# ============================================

class UserSession(db.Model):
    """
    Track user sessions for security monitoring
    """
    __tablename__ = 'user_sessions'
    
    id = Column(Integer, primary_key=True)
    user_id = Column(Integer, db.ForeignKey('users.id', ondelete='CASCADE'), nullable=False)
    session_token = Column(String(255), unique=True, nullable=False)
    ip_address = Column(String(45), nullable=False)
    user_agent = Column(String(500), nullable=True)
    device_info = Column(JSON, default={})
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    last_activity = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    
    # Relationship
    user = relationship("User", backref="sessions")
    
    @classmethod
    def create_session(cls, user_id, session_token, ip_address, user_agent, expires_at):
        """Create a new user session"""
        session = cls(
            user_id=user_id,
            session_token=session_token,
            ip_address=ip_address,
            user_agent=user_agent,
            expires_at=expires_at
        )
        db.session.add(session)
        db.session.commit()
        return session
    
    def update_activity(self):
        """Update last activity timestamp"""
        self.last_activity = datetime.utcnow()
        db.session.commit()
    
    def terminate(self):
        """Terminate the session"""
        self.is_active = False
        db.session.commit()
    
    def __repr__(self):
        return f"<UserSession {self.user_id} - {'Active' if self.is_active else 'Terminated'}>"


# ============================================
# INVITATION MODEL (For admin to invite users)
# ============================================

class UserInvitation(db.Model):
    """
    Model for user invitations (admin invites new users)
    """
    __tablename__ = 'user_invitations'
    
    id = Column(Integer, primary_key=True)
    email = Column(String(255), nullable=False, index=True)
    role = Column(Enum(UserRole), nullable=False)
    invited_by = Column(Integer, db.ForeignKey('users.id'), nullable=False)
    invitation_token = Column(String(255), unique=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    is_used = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    accepted_at = Column(DateTime, nullable=True)
    
    # Relationship
    inviter = relationship("User", foreign_keys=[invited_by])
    
    def is_valid(self):
        """Check if invitation is still valid"""
        return not self.is_used and self.expires_at > datetime.utcnow()
    
    def accept(self):
        """Mark invitation as accepted"""
        self.is_used = True
        self.accepted_at = datetime.utcnow()
        db.session.commit()
    
    def __repr__(self):
        return f"<Invitation for {self.email} - {self.role.value}>"


# ============================================
# HELPER FUNCTIONS
# ============================================

def find_user_by_email(email):
    """Find user by email address"""
    return User.query.filter_by(email=email.lower()).first()

def find_user_by_username(username):
    """Find user by username"""
    return User.query.filter_by(username=username).first()

def find_user_by_id(user_id):
    """Find user by ID"""
    return User.query.get(user_id)

def get_all_active_users():
    """Get all active users"""
    return User.query.filter_by(status=UserStatus.ACTIVE).all()

def get_users_by_role(role):
    """Get all users with a specific role"""
    return User.query.filter_by(role=role).all()

def create_default_admin():
    """Create default admin user if no admin exists"""
    admin_email = "admin@sevps.com"
    admin = find_user_by_email(admin_email)
    
    if not admin:
        admin = User(
            email=admin_email,
            username="admin",
            full_name="System Administrator",
            password="Admin@123",  # Change this in production!
            role=UserRole.SUPER_ADMIN,
            department="System Administration",
            notification_enabled=True
        )
        db.session.add(admin)
        db.session.commit()
        logger.info(f"✅ Default admin created: {admin_email}")
        logger.warning("⚠️ Please change default admin password immediately!")
    else:
        logger.info(f"Default admin already exists: {admin_email}")
    
    return admin


# ============================================
# EXPORTS
# ============================================

__all__ = [
    'User',
    'UserRole',
    'UserStatus',
    'VehicleType',
    'TokenBlocklist',
    'UserSession',
    'UserInvitation',
    'find_user_by_email',
    'find_user_by_username',
    'find_user_by_id',
    'get_all_active_users',
    'get_users_by_role',
    'create_default_admin'
]