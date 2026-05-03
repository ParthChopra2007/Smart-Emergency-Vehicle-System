"""
Smart Emergency Vehicle Priority System - Socket Events Package
This file initializes all WebSocket event handlers for real-time communication
including vehicle tracking, signal updates, corridor monitoring, and alerts
"""

from flask import request
from flask_socketio import SocketIO, emit, join_room, leave_room, disconnect
from flask_jwt_extended import decode_token
from loguru import logger
from datetime import datetime
import json

# Global SocketIO instance (will be set from app)
socketio = None

# Store active connections
active_connections = {}  # session_id -> user_info
room_members = {}  # room_name -> set of session_ids


# ============================================
# SOCKET EVENT HANDLERS REGISTRATION
# ============================================

def register_socket_events(sio):
    """
    Register all WebSocket event handlers with SocketIO instance
    Call this from app/__init__.py after creating socketio
    """
    global socketio
    socketio = sio
    
    # ============================================
    # CONNECTION EVENTS
    # ============================================
    
    @socketio.on('connect')
    def handle_connect():
        """Handle client connection"""
        try:
            # Try to get auth token from headers
            token = request.headers.get('Authorization', '').replace('Bearer ', '')
            
            if token:
                try:
                    decoded = decode_token(token)
                    user_id = decoded.get('sub')
                    user_email = decoded.get('email')
                    user_role = decoded.get('role')
                    
                    # Store connection info
                    session_id = request.sid
                    active_connections[session_id] = {
                        'user_id': user_id,
                        'user_email': user_email,
                        'user_role': user_role,
                        'connected_at': datetime.utcnow().isoformat()
                    }
                    
                    # Join user to their personal room
                    join_room(f"user_{user_id}")
                    
                    # Join role-based room
                    if user_role:
                        join_room(f"role_{user_role}")
                    
                    # Join control room if role is control_room or admin
                    if user_role in ['control_room', 'admin', 'super_admin']:
                        join_room("control_room")
                    
                    logger.info(f"Socket connected: user {user_id} ({user_email}) - Session: {session_id}")
                    emit('connected', {
                        'status': 'success',
                        'message': 'Connected to SEVPS real-time server',
                        'timestamp': datetime.utcnow().isoformat()
                    })
                    
                except Exception as e:
                    logger.warning(f"Socket auth failed: {e}")
                    emit('connected', {
                        'status': 'warning',
                        'message': 'Connected without authentication. Limited features available.',
                        'timestamp': datetime.utcnow().isoformat()
                    })
            else:
                # Guest connection (limited features)
                emit('connected', {
                    'status': 'info',
                    'message': 'Connected as guest. Please authenticate for full features.',
                    'timestamp': datetime.utcnow().isoformat()
                })
                
        except Exception as e:
            logger.error(f"Socket connect error: {e}")
            emit('connected', {
                'status': 'error',
                'message': 'Connection failed'
            })
    
    @socketio.on('disconnect')
    def handle_disconnect():
        """Handle client disconnection"""
        session_id = request.sid
        if session_id in active_connections:
            user_info = active_connections.pop(session_id)
            logger.info(f"Socket disconnected: user {user_info.get('user_id')} - Session: {session_id}")
        
        # Remove from all rooms
        for room, members in room_members.items():
            if session_id in members:
                members.discard(session_id)
    
    # ============================================
    # AUTHENTICATION EVENT
    # ============================================
    
    @socketio.on('authenticate')
    def handle_authenticate(data):
        """Authenticate WebSocket connection with JWT token"""
        session_id = request.sid
        token = data.get('token')
        
        if not token:
            emit('auth_response', {
                'success': False,
                'message': 'No token provided'
            })
            return
        
        try:
            decoded = decode_token(token)
            user_id = decoded.get('sub')
            user_email = decoded.get('email')
            user_role = decoded.get('role')
            
            # Update connection info
            if session_id in active_connections:
                active_connections[session_id].update({
                    'user_id': user_id,
                    'user_email': user_email,
                    'user_role': user_role,
                    'authenticated_at': datetime.utcnow().isoformat()
                })
            else:
                active_connections[session_id] = {
                    'user_id': user_id,
                    'user_email': user_email,
                    'user_role': user_role,
                    'authenticated_at': datetime.utcnow().isoformat()
                }
            
            # Join user rooms
            join_room(f"user_{user_id}")
            if user_role:
                join_room(f"role_{user_role}")
            if user_role in ['control_room', 'admin', 'super_admin']:
                join_room("control_room")
            
            emit('auth_response', {
                'success': True,
                'message': 'Authentication successful',
                'user_id': user_id,
                'user_role': user_role,
                'timestamp': datetime.utcnow().isoformat()
            })
            
            logger.info(f"Socket authenticated: user {user_id} ({user_email})")
            
        except Exception as e:
            logger.error(f"Socket authentication error: {e}")
            emit('auth_response', {
                'success': False,
                'message': f'Authentication failed: {str(e)}'
            })
    
    # ============================================
    # ROOM MANAGEMENT EVENTS
    # ============================================
    
    @socketio.on('join_room')
    def handle_join_room(data):
        """Join a specific room"""
        room_name = data.get('room')
        if not room_name:
            emit('room_joined', {
                'success': False,
                'message': 'Room name required'
            })
            return
        
        join_room(room_name)
        
        # Track room membership
        session_id = request.sid
        if room_name not in room_members:
            room_members[room_name] = set()
        room_members[room_name].add(session_id)
        
        emit('room_joined', {
            'success': True,
            'room': room_name,
            'message': f'Joined room: {room_name}',
            'timestamp': datetime.utcnow().isoformat()
        })
        
        logger.debug(f"Session {session_id} joined room {room_name}")
    
    @socketio.on('leave_room')
    def handle_leave_room(data):
        """Leave a room"""
        room_name = data.get('room')
        if not room_name:
            emit('room_left', {
                'success': False,
                'message': 'Room name required'
            })
            return
        
        leave_room(room_name)
        
        # Remove from room tracking
        session_id = request.sid
        if room_name in room_members:
            room_members[room_name].discard(session_id)
        
        emit('room_left', {
            'success': True,
            'room': room_name,
            'message': f'Left room: {room_name}',
            'timestamp': datetime.utcnow().isoformat()
        })
    
    # ============================================
    # PING/PONG FOR CONNECTION HEALTH
    # ============================================
    
    @socketio.on('ping')
    def handle_ping():
        """Respond to ping with pong for connection health check"""
        emit('pong', {
            'timestamp': datetime.utcnow().isoformat()
        })
    
    # ============================================
    # IMPORT AND REGISTER MODULE-SPECIFIC HANDLERS
    # ============================================
    
    # Import handlers from submodules
    from app.socket_events.live_tracking import register_tracking_events
    from app.socket_events.signal_updates import register_signal_events
    
    # Register module handlers
    register_tracking_events(socketio)
    register_signal_events(socketio)
    
    logger.info("✅ All WebSocket event handlers registered successfully")
    
    return socketio


# ============================================
# HELPER FUNCTIONS
# ============================================

def get_connection_count() -> int:
    """Get number of active WebSocket connections"""
    return len(active_connections)


def get_connections_by_role(role: str) -> list:
    """Get all connections with a specific role"""
    return [
        {'session_id': sid, 'user_info': info}
        for sid, info in active_connections.items()
        if info.get('user_role') == role
    ]


def get_room_members(room_name: str) -> list:
    """Get list of session IDs in a room"""
    return list(room_members.get(room_name, set()))


def broadcast_to_role(role: str, event: str, data: dict):
    """Broadcast an event to all users with a specific role"""
    if socketio:
        socketio.emit(event, data, room=f"role_{role}")
        logger.debug(f"Broadcast to role {role}: {event}")


def broadcast_to_control_room(event: str, data: dict):
    """Broadcast an event to control room only"""
    if socketio:
        socketio.emit(event, data, room="control_room")
        logger.debug(f"Broadcast to control room: {event}")


def send_to_user(user_id: int, event: str, data: dict):
    """Send an event to a specific user"""
    if socketio:
        socketio.emit(event, data, room=f"user_{user_id}")
        logger.debug(f"Sent to user {user_id}: {event}")


def get_connection_stats() -> dict:
    """Get WebSocket connection statistics"""
    role_counts = {}
    for info in active_connections.values():
        role = info.get('user_role', 'guest')
        role_counts[role] = role_counts.get(role, 0) + 1
    
    return {
        'total_connections': len(active_connections),
        'by_role': role_counts,
        'rooms': list(room_members.keys()),
        'timestamp': datetime.utcnow().isoformat()
    }


# ============================================
# EXPORTS
# ============================================

__all__ = [
    'socketio',
    'register_socket_events',
    'get_connection_count',
    'get_connections_by_role',
    'get_room_members',
    'broadcast_to_role',
    'broadcast_to_control_room',
    'send_to_user',
    'get_connection_stats'
]