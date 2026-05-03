"""
Smart Emergency Vehicle Priority System - Signal Updates Socket Events
Handles real-time traffic signal status updates, green corridor activation,
signal control commands, and traffic density broadcasts via WebSocket
"""

from flask_socketio import emit, join_room, leave_room
from datetime import datetime
from loguru import logger
import json

from app.extensions import db, cache

# Store active signal subscriptions
signal_subscribers = {}  # signal_id -> list of session_ids
active_signal_sessions = {}  # session_id -> signal_id

# Store last known signal statuses
last_known_signal_status = {}  # signal_id -> status_data

# Store active green corridors for signals
active_green_corridors = {}  # signal_id -> corridor_info


def register_signal_events(socketio):
    """
    Register all traffic signal related WebSocket events
    """
    
    # ============================================
    # SIGNAL STATUS SUBSCRIPTION
    # ============================================
    
    @socketio.on('subscribe_signal')
    def handle_subscribe_signal(data):
        """Subscribe to real-time updates for a specific traffic signal"""
        session_id = request.sid
        signal_id = data.get('signal_id')
        
        if not signal_id:
            emit('signal_subscribed', {
                'success': False,
                'message': 'signal_id required'
            })
            return
        
        # Join signal-specific room
        join_room(f'signal_{signal_id}')
        
        # Track subscription
        if signal_id not in signal_subscribers:
            signal_subscribers[signal_id] = []
        if session_id not in signal_subscribers[signal_id]:
            signal_subscribers[signal_id].append(session_id)
        
        active_signal_sessions[session_id] = signal_id
        
        # Send last known status immediately
        if signal_id in last_known_signal_status:
            emit('signal_status_update', {
                'signal_id': signal_id,
                'status': last_known_signal_status[signal_id],
                'is_replay': True,
                'timestamp': datetime.utcnow().isoformat()
            })
        
        # Also send green corridor status if active
        if signal_id in active_green_corridors:
            emit('signal_green_corridor_active', {
                'signal_id': signal_id,
                'corridor_info': active_green_corridors[signal_id],
                'timestamp': datetime.utcnow().isoformat()
            })
        
        emit('signal_subscribed', {
            'success': True,
            'signal_id': signal_id,
            'message': f'Subscribed to signal {signal_id} updates',
            'timestamp': datetime.utcnow().isoformat()
        })
        
        logger.debug(f"Session {session_id} subscribed to signal {signal_id}")
    
    @socketio.on('unsubscribe_signal')
    def handle_unsubscribe_signal(data):
        """Unsubscribe from signal updates"""
        session_id = request.sid
        signal_id = data.get('signal_id')
        
        if signal_id:
            leave_room(f'signal_{signal_id}')
            
            # Remove from subscribers
            if signal_id in signal_subscribers:
                if session_id in signal_subscribers[signal_id]:
                    signal_subscribers[signal_id].remove(session_id)
        
        if session_id in active_signal_sessions:
            del active_signal_sessions[session_id]
        
        emit('signal_unsubscribed', {
            'success': True,
            'signal_id': signal_id,
            'message': f'Unsubscribed from signal {signal_id} updates',
            'timestamp': datetime.utcnow().isoformat()
        })
    
    # ============================================
    # SUBSCRIBE TO ALL SIGNALS (for control room)
    # ============================================
    
    @socketio.on('subscribe_all_signals')
    def handle_subscribe_all_signals(data):
        """Subscribe to all traffic signal updates (control room only)"""
        session_id = request.sid
        
        # Check authorization (should be control room or admin)
        # For now, allow all authenticated users
        
        join_room('all_signals')
        
        # Send all current signal statuses
        all_statuses = []
        for signal_id, status in last_known_signal_status.items():
            all_statuses.append({
                'signal_id': signal_id,
                'status': status,
                'green_corridor_active': signal_id in active_green_corridors
            })
        
        emit('all_signals_status', {
            'success': True,
            'signal_count': len(all_statuses),
            'signals': all_statuses,
            'timestamp': datetime.utcnow().isoformat()
        })
        
        emit('subscribed_all_signals', {
            'success': True,
            'message': 'Subscribed to all signal updates',
            'timestamp': datetime.utcnow().isoformat()
        })
        
        logger.debug(f"Session {session_id} subscribed to all signals")
    
    @socketio.on('unsubscribe_all_signals')
    def handle_unsubscribe_all_signals():
        """Unsubscribe from all signal updates"""
        session_id = request.sid
        leave_room('all_signals')
        
        emit('unsubscribed_all_signals', {
            'success': True,
            'message': 'Unsubscribed from all signal updates',
            'timestamp': datetime.utcnow().isoformat()
        })
    
    # ============================================
    # SIGNAL STATUS UPDATE (from IoT/Controller)
    # ============================================
    
    @socketio.on('signal_status_update')
    def handle_signal_status_update(data):
        """
        Receive status update from traffic signal controller
        This is the main endpoint for real-time signal data
        """
        signal_id = data.get('signal_id')
        current_status = data.get('current_status')
        current_green_direction = data.get('current_green_direction')
        cycle_remaining = data.get('cycle_remaining', 0)
        is_online = data.get('is_online', True)
        error_code = data.get('error_code', 0)
        
        # Validate input
        if not signal_id:
            emit('signal_update_response', {
                'success': False,
                'message': 'signal_id required'
            })
            return
        
        # Create status data object
        status_data = {
            'current_status': current_status,
            'current_green_direction': current_green_direction,
            'cycle_remaining_seconds': cycle_remaining,
            'is_online': is_online,
            'error_code': error_code,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Store last known status
        last_known_signal_status[signal_id] = status_data
        
        # Cache in Redis for quick access
        if hasattr(cache, 'redis_client') and cache.redis_client:
            cache.redis_client.setex(
                f'signal_status:{signal_id}',
                30,
                json.dumps(status_data)
            )
        
        # Broadcast to signal subscribers
        emit('signal_status_update', {
            'signal_id': signal_id,
            'status': status_data,
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'signal_{signal_id}', include_self=False)
        
        # Broadcast to all signals room if subscribed
        emit('signal_status_broadcast', {
            'signal_id': signal_id,
            'status': status_data,
            'timestamp': datetime.utcnow().isoformat()
        }, room='all_signals')
        
        # Also broadcast to control room for monitoring
        emit('realtime_signal_update', {
            'signal_id': signal_id,
            'status': status_data,
            'timestamp': datetime.utcnow().isoformat()
        }, room='control_room')
        
        # Update database in background (handled by services)
        
        emit('signal_update_response', {
            'success': True,
            'message': 'Signal status updated',
            'timestamp': datetime.utcnow().isoformat()
        })
        
        logger.debug(f"Signal {signal_id} status updated: {current_status}, direction: {current_green_direction}")
    
    # ============================================
    # GREEN CORRIDOR ACTIVATION
    # ============================================
    
    @socketio.on('activate_green_corridor')
    def handle_activate_green_corridor(data):
        """
        Activate green corridor on a signal (from control room or system)
        """
        signal_id = data.get('signal_id')
        corridor_id = data.get('corridor_id')
        vehicle_id = data.get('vehicle_id')
        duration_seconds = data.get('duration_seconds', 60)
        green_direction = data.get('green_direction')
        
        if not all([signal_id, corridor_id, vehicle_id]):
            emit('green_corridor_response', {
                'success': False,
                'message': 'Missing required fields: signal_id, corridor_id, vehicle_id'
            })
            return
        
        # Store active corridor info
        corridor_info = {
            'corridor_id': corridor_id,
            'vehicle_id': vehicle_id,
            'duration_seconds': duration_seconds,
            'green_direction': green_direction,
            'activated_at': datetime.utcnow().isoformat(),
            'expires_at': (datetime.utcnow() + timedelta(seconds=duration_seconds)).isoformat()
        }
        
        active_green_corridors[signal_id] = corridor_info
        
        # Update last known status to reflect green corridor
        if signal_id in last_known_signal_status:
            last_known_signal_status[signal_id]['current_status'] = 'green_corridor'
            last_known_signal_status[signal_id]['current_green_direction'] = green_direction
        
        # Broadcast green corridor activation
        emit('green_corridor_activated', {
            'signal_id': signal_id,
            'corridor_info': corridor_info,
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'signal_{signal_id}')
        
        # Broadcast to all signals room
        emit('green_corridor_broadcast', {
            'signal_id': signal_id,
            'corridor_info': corridor_info,
            'timestamp': datetime.utcnow().isoformat()
        }, room='all_signals')
        
        # Broadcast to control room
        emit('green_corridor_control', {
            'signal_id': signal_id,
            'corridor_info': corridor_info,
            'timestamp': datetime.utcnow().isoformat()
        }, room='control_room')
        
        emit('green_corridor_response', {
            'success': True,
            'signal_id': signal_id,
            'corridor_id': corridor_id,
            'message': f'Green corridor activated on signal {signal_id} for {duration_seconds}s',
            'expires_at': corridor_info['expires_at']
        })
        
        # Schedule auto-deactivation after duration
        socketio.sleep(duration_seconds)
        # Check if still active and deactivate
        if signal_id in active_green_corridors:
            handle_deactivate_green_corridor({'signal_id': signal_id, 'corridor_id': corridor_id})
        
        logger.info(f"Green corridor {corridor_id} activated on signal {signal_id} for vehicle {vehicle_id}")
    
    @socketio.on('deactivate_green_corridor')
    def handle_deactivate_green_corridor(data):
        """Deactivate green corridor on a signal"""
        signal_id = data.get('signal_id')
        corridor_id = data.get('corridor_id')
        
        if not signal_id:
            emit('green_corridor_response', {
                'success': False,
                'message': 'signal_id required'
            })
            return
        
        removed_info = None
        if signal_id in active_green_corridors:
            removed_info = active_green_corridors.pop(signal_id)
        
        # Update last known status to normal
        if signal_id in last_known_signal_status:
            last_known_signal_status[signal_id]['current_status'] = 'normal'
            last_known_signal_status[signal_id]['current_green_direction'] = None
        
        # Broadcast deactivation
        emit('green_corridor_deactivated', {
            'signal_id': signal_id,
            'corridor_id': corridor_id,
            'previous_corridor': removed_info,
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'signal_{signal_id}')
        
        emit('green_corridor_deactivated_broadcast', {
            'signal_id': signal_id,
            'timestamp': datetime.utcnow().isoformat()
        }, room='all_signals')
        
        emit('green_corridor_response', {
            'success': True,
            'signal_id': signal_id,
            'message': f'Green corridor deactivated on signal {signal_id}'
        })
        
        logger.info(f"Green corridor deactivated on signal {signal_id}")
    
    # ============================================
    # TRAFFIC DENSITY UPDATE
    # ============================================
    
    @socketio.on('traffic_density_update')
    def handle_traffic_density_update(data):
        """Receive traffic density update from sensor/camera"""
        signal_id = data.get('signal_id')
        density_level = data.get('density_level')  # low, medium, high, gridlock
        vehicle_count = data.get('vehicle_count', 0)
        average_speed = data.get('average_speed', 0)
        density_data = data.get('density_data', {})
        
        if not signal_id:
            return
        
        density_info = {
            'signal_id': signal_id,
            'density_level': density_level,
            'vehicle_count': vehicle_count,
            'average_speed_kmh': average_speed,
            'density_data': density_data,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Update last known status
        if signal_id in last_known_signal_status:
            last_known_signal_status[signal_id]['density_level'] = density_level
            last_known_signal_status[signal_id]['vehicle_count'] = vehicle_count
        
        # Broadcast density update
        emit('traffic_density_updated', density_info, room=f'signal_{signal_id}')
        
        # If high or gridlock, send alert to control room
        if density_level in ['high', 'gridlock']:
            emit('high_traffic_alert', {
                'signal_id': signal_id,
                'density_level': density_level,
                'vehicle_count': vehicle_count,
                'timestamp': datetime.utcnow().isoformat()
            }, room='control_room')
        
        logger.debug(f"Signal {signal_id} traffic density: {density_level}, vehicles: {vehicle_count}")
    
    # ============================================
    # SIGNAL CONTROL COMMANDS
    # ============================================
    
    @socketio.on('send_signal_command')
    def handle_signal_command(data):
        """Send control command to a signal (from control room)"""
        signal_id = data.get('signal_id')
        command = data.get('command')  # manual_control, reset, timing_update
        command_params = data.get('params', {})
        
        if not signal_id or not command:
            emit('signal_command_response', {
                'success': False,
                'message': 'signal_id and command required'
            })
            return
        
        command_info = {
            'signal_id': signal_id,
            'command': command,
            'params': command_params,
            'issued_by': request.sid,
            'issued_at': datetime.utcnow().isoformat()
        }
        
        # Broadcast command to signal controller (via room)
        emit('signal_command', command_info, room=f'signal_{signal_id}')
        
        # Log to control room
        emit('signal_command_issued', command_info, room='control_room')
        
        emit('signal_command_response', {
            'success': True,
            'signal_id': signal_id,
            'command': command,
            'message': f'Command {command} sent to signal {signal_id}'
        })
        
        logger.info(f"Command {command} sent to signal {signal_id}")
    
    # ============================================
    # SIGNAL ALERT HANDLING
    # ============================================
    
    @socketio.on('report_signal_alert')
    def handle_signal_alert(data):
        """Report alert from signal (fault, offline, etc.)"""
        signal_id = data.get('signal_id')
        alert_type = data.get('alert_type')  # offline, fault, maintenance, emergency
        alert_message = data.get('message')
        severity = data.get('severity', 'medium')  # low, medium, high, critical
        
        if not signal_id or not alert_type:
            return
        
        alert_info = {
            'signal_id': signal_id,
            'alert_type': alert_type,
            'message': alert_message,
            'severity': severity,
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Broadcast to control room
        emit('signal_alert', alert_info, room='control_room')
        
        # If critical, also broadcast to all signals room
        if severity == 'critical':
            emit('critical_signal_alert', alert_info, room='all_signals')
        
        # Update signal status
        if signal_id in last_known_signal_status:
            last_known_signal_status[signal_id]['alert'] = alert_info
            if alert_type == 'offline':
                last_known_signal_status[signal_id]['is_online'] = False
        
        emit('signal_alert_response', {
            'success': True,
            'message': 'Alert reported'
        })
        
        logger.warning(f"Signal {signal_id} alert: {alert_type} - {alert_message}")
    
    @socketio.on('acknowledge_signal_alert')
    def handle_acknowledge_alert(data):
        """Acknowledge signal alert from control room"""
        signal_id = data.get('signal_id')
        alert_id = data.get('alert_id')
        acknowledged_by = data.get('acknowledged_by', request.sid)
        
        if not signal_id:
            return
        
        emit('signal_alert_acknowledged', {
            'signal_id': signal_id,
            'alert_id': alert_id,
            'acknowledged_by': acknowledged_by,
            'acknowledged_at': datetime.utcnow().isoformat()
        }, room='control_room')
        
        logger.info(f"Signal {signal_id} alert acknowledged by {acknowledged_by}")
    
    # ============================================
    # HELPER FUNCTIONS FOR PROGRAMMATIC USE
    # ============================================
    
    def broadcast_signal_status(signal_id, status_data):
        """Programmatically broadcast signal status update"""
        socketio.emit('signal_status_update', {
            'signal_id': signal_id,
            'status': status_data,
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'signal_{signal_id}')
    
    def broadcast_green_corridor(signal_id, corridor_id, vehicle_id, duration):
        """Programmatically broadcast green corridor activation"""
        socketio.emit('green_corridor_activated', {
            'signal_id': signal_id,
            'corridor_id': corridor_id,
            'vehicle_id': vehicle_id,
            'duration_seconds': duration,
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'signal_{signal_id}')
    
    def broadcast_traffic_density(signal_id, density_level, vehicle_count):
        """Programmatically broadcast traffic density update"""
        socketio.emit('traffic_density_updated', {
            'signal_id': signal_id,
            'density_level': density_level,
            'vehicle_count': vehicle_count,
            'timestamp': datetime.utcnow().isoformat()
        }, room=f'signal_{signal_id}')
    
    def get_signal_status(signal_id):
        """Get last known status for a signal"""
        return last_known_signal_status.get(signal_id)
    
    def get_all_signal_statuses():
        """Get all last known signal statuses"""
        return last_known_signal_status.copy()
    
    def get_active_green_corridors():
        """Get all signals with active green corridors"""
        return active_green_corridors.copy()
    
    # Store functions for external use
    socketio.broadcast_signal_status = broadcast_signal_status
    socketio.broadcast_green_corridor = broadcast_green_corridor
    socketio.broadcast_traffic_density = broadcast_traffic_density
    socketio.get_signal_status = get_signal_status
    socketio.get_all_signal_statuses = get_all_signal_statuses
    socketio.get_active_green_corridors = get_active_green_corridors
    
    logger.info("✅ Signal updates WebSocket events registered")
    
    return socketio


# ============================================
# HELPER FUNCTIONS (for use by other modules)
# ============================================

def notify_signal_status_change(signal_id: int, old_status: str, new_status: str):
    """Notify about signal status change"""
    if socketio:
        socketio.emit('signal_status_changed', {
            'signal_id': signal_id,
            'old_status': old_status,
            'new_status': new_status,
            'timestamp': datetime.utcnow().isoformat()
        }, room='control_room')


def notify_signal_offline(signal_id: int, intersection_name: str):
    """Notify that signal is offline"""
    if socketio:
        socketio.emit('signal_offline_alert', {
            'signal_id': signal_id,
            'intersection_name': intersection_name,
            'timestamp': datetime.utcnow().isoformat()
        }, room='control_room')


def update_signal_status_db(signal_id: int, status_data: dict):
    """Update signal status in database"""
    try:
        from app.models.traffic_signal import find_signal_by_id
        signal = find_signal_by_id(signal_id)
        if signal:
            # Update signal in database
            signal.current_status = status_data.get('current_status')
            signal.current_green_direction = status_data.get('current_green_direction')
            signal.is_online = status_data.get('is_online', True)
            db.session.commit()
    except Exception as e:
        logger.error(f"Failed to update signal {signal_id} in DB: {e}")


def get_signal_count() -> int:
    """Get number of signals with known status"""
    return len(last_known_signal_status)


def get_active_corridor_count() -> int:
    """Get number of signals with active green corridors"""
    return len(active_green_corridors)


# ============================================
# EXPORTS
# ============================================

__all__ = [
    'register_signal_events',
    'notify_signal_status_change',
    'notify_signal_offline',
    'update_signal_status_db',
    'get_signal_count',
    'get_active_corridor_count'
]

# Import for request context
from flask_socketio import request
from datetime import timedelta