"""
Smart Emergency Vehicle Priority System - Notification Service
Handles email, SMS, push notifications, and real-time alerts for
emergency vehicles, corridor requests, incident updates, and system alerts
"""

import smtplib
import threading
import json
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from collections import deque
from loguru import logger
import uuid

from app.extensions import db, socketio, redis_client

# ============================================
# DATA CLASSES
# ============================================

@dataclass
class Notification:
    """Represents a notification message"""
    id: str
    type: str  # email, sms, push, alert
    recipient: str
    title: str
    body: str
    priority: int = 1  # 1=high, 2=medium, 3=low
    data: Dict = field(default_factory=dict)
    status: str = "pending"  # pending, sent, failed
    created_at: datetime = field(default_factory=datetime.utcnow)
    sent_at: datetime = None
    error_message: str = None
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'type': self.type,
            'recipient': self.recipient,
            'title': self.title,
            'body': self.body,
            'priority': self.priority,
            'data': self.data,
            'status': self.status,
            'created_at': self.created_at.isoformat(),
            'sent_at': self.sent_at.isoformat() if self.sent_at else None
        }


@dataclass
class Alert:
    """Represents a real-time alert"""
    id: str
    type: str  # emergency, corridor, incident, system, weather
    severity: str  # critical, high, medium, low, info
    title: str
    message: str
    source: str  # system, vehicle, signal, control_room
    entity_id: int = None
    entity_type: str = None
    data: Dict = field(default_factory=dict)
    is_read: bool = False
    created_at: datetime = field(default_factory=datetime.utcnow)
    
    def to_dict(self) -> Dict:
        return {
            'id': self.id,
            'type': self.type,
            'severity': self.severity,
            'title': self.title,
            'message': self.message,
            'source': self.source,
            'entity_id': self.entity_id,
            'entity_type': self.entity_type,
            'data': self.data,
            'is_read': self.is_read,
            'created_at': self.created_at.isoformat()
        }


# ============================================
# EMAIL NOTIFIER
# ============================================

class EmailNotifier:
    """
    Handles email notifications using SMTP
    Supports HTML emails, attachments, and templates
    """
    
    def __init__(self, app=None):
        self.app = app
        self.smtp_server = None
        self.smtp_port = None
        self.smtp_username = None
        self.smtp_password = None
        self.default_sender = None
        self.is_configured = False
        self.queue = deque(maxlen=1000)
        self._processing_thread = None
        self._is_running = False
        
        if app:
            self.init_email(app)
    
    def init_email(self, app):
        """Initialize email configuration"""
        self.smtp_server = app.config.get('MAIL_SERVER')
        self.smtp_port = app.config.get('MAIL_PORT', 587)
        self.smtp_username = app.config.get('MAIL_USERNAME')
        self.smtp_password = app.config.get('MAIL_PASSWORD')
        self.default_sender = app.config.get('MAIL_DEFAULT_SENDER', 'noreply@sevps.com')
        
        if self.smtp_server and self.smtp_username:
            self.is_configured = True
            self.start_processor()
            logger.info(f"Email notifier configured: {self.smtp_server}:{self.smtp_port}")
        else:
            logger.warning("Email not configured. Email notifications disabled.")
    
    def start_processor(self):
        """Start background email processor"""
        if self._processing_thread is None:
            self._is_running = True
            self._processing_thread = threading.Thread(target=self._process_emails)
            self._processing_thread.daemon = True
            self._processing_thread.start()
            logger.info("Email processor started")
    
    def _process_emails(self):
        """Process queued emails in background"""
        while self._is_running:
            try:
                if self.queue:
                    notification = self.queue.popleft()
                    self._send_email(notification)
                else:
                    import time
                    time.sleep(0.5)
            except Exception as e:
                logger.error(f"Email processor error: {e}")
    
    def _send_email(self, notification: Notification):
        """Send an email"""
        if not self.is_configured:
            notification.status = "failed"
            notification.error_message = "Email not configured"
            return
        
        try:
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.smtp_username, self.smtp_password)
                
                # Create message
                subject = notification.title
                body = notification.body
                
                message = f"Subject: {subject}\r\n"
                message += f"From: {self.default_sender}\r\n"
                message += f"To: {notification.recipient}\r\n"
                message += f"Content-Type: text/html; charset=utf-8\r\n\r\n"
                message += f"<html><body>{body}</body></html>"
                
                server.sendmail(self.default_sender, notification.recipient, message.encode('utf-8'))
                
                notification.status = "sent"
                notification.sent_at = datetime.utcnow()
                logger.info(f"Email sent to {notification.recipient}: {notification.title}")
                
        except Exception as e:
            notification.status = "failed"
            notification.error_message = str(e)
            logger.error(f"Email send failed: {e}")
    
    def send_email(self, to: str, subject: str, body: str, priority: int = 2, data: Dict = None) -> str:
        """Queue an email for sending"""
        notification = Notification(
            id=str(uuid.uuid4()),
            type="email",
            recipient=to,
            title=subject,
            body=body,
            priority=priority,
            data=data or {}
        )
        self.queue.append(notification)
        logger.debug(f"Email queued: {subject} to {to}")
        return notification.id
    
    def send_emergency_alert(self, to: str, incident_type: str, location: str, severity: str) -> str:
        """Send emergency alert email"""
        subject = f"🚨 EMERGENCY ALERT: {incident_type.upper()} - {severity.upper()}"
        body = f"""
        <h2>Emergency Alert</h2>
        <p><strong>Type:</strong> {incident_type}</p>
        <p><strong>Severity:</strong> {severity}</p>
        <p><strong>Location:</strong> {location}</p>
        <p><strong>Time:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
        <p>Please check the control room dashboard for more details.</p>
        """
        return self.send_email(to, subject, body, priority=1)
    
    def send_corridor_alert(self, to: str, vehicle_reg: str, corridor_id: int, status: str) -> str:
        """Send corridor status alert email"""
        subject = f"🚦 Green Corridor {status.upper()} - Vehicle {vehicle_reg}"
        body = f"""
        <h2>Green Corridor Update</h2>
        <p><strong>Vehicle:</strong> {vehicle_reg}</p>
        <p><strong>Corridor ID:</strong> {corridor_id}</p>
        <p><strong>Status:</strong> {status}</p>
        <p><strong>Time:</strong> {datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
        """
        return self.send_email(to, subject, body, priority=1 if status == 'active' else 2)
    
    def get_stats(self) -> Dict:
        """Get email notifier statistics"""
        return {
            'configured': self.is_configured,
            'queue_size': len(self.queue),
            'is_running': self._is_running
        }


# ============================================
# SMS NOTIFIER (using Twilio)
# ============================================

class SMSNotifier:
    """
    Handles SMS notifications using Twilio API
    """
    
    def __init__(self, app=None):
        self.app = app
        self.account_sid = None
        self.auth_token = None
        self.from_number = None
        self.is_configured = False
        self.queue = deque(maxlen=500)
        self._processing_thread = None
        self._is_running = False
        
        if app:
            self.init_sms(app)
    
    def init_sms(self, app):
        """Initialize SMS configuration"""
        self.account_sid = app.config.get('TWILIO_ACCOUNT_SID')
        self.auth_token = app.config.get('TWILIO_AUTH_TOKEN')
        self.from_number = app.config.get('TWILIO_PHONE_NUMBER')
        
        if self.account_sid and self.auth_token and self.from_number:
            self.is_configured = True
            self.start_processor()
            logger.info("SMS notifier configured")
        else:
            logger.warning("SMS not configured. SMS notifications disabled.")
    
    def start_processor(self):
        """Start background SMS processor"""
        if self._processing_thread is None:
            self._is_running = True
            self._processing_thread = threading.Thread(target=self._process_sms)
            self._processing_thread.daemon = True
            self._processing_thread.start()
            logger.info("SMS processor started")
    
    def _process_sms(self):
        """Process queued SMS in background"""
        while self._is_running:
            try:
                if self.queue:
                    notification = self.queue.popleft()
                    self._send_sms(notification)
                else:
                    import time
                    time.sleep(0.5)
            except Exception as e:
                logger.error(f"SMS processor error: {e}")
    
    def _send_sms(self, notification: Notification):
        """Send an SMS"""
        if not self.is_configured:
            notification.status = "failed"
            notification.error_message = "SMS not configured"
            return
        
        try:
            from twilio.rest import Client
            
            client = Client(self.account_sid, self.auth_token)
            message = client.messages.create(
                body=notification.body[:160],  # SMS limit
                from_=self.from_number,
                to=notification.recipient
            )
            
            notification.status = "sent"
            notification.sent_at = datetime.utcnow()
            notification.data['message_sid'] = message.sid
            logger.info(f"SMS sent to {notification.recipient}")
            
        except ImportError:
            notification.status = "failed"
            notification.error_message = "Twilio library not installed"
            logger.error("Twilio not installed. SMS disabled.")
        except Exception as e:
            notification.status = "failed"
            notification.error_message = str(e)
            logger.error(f"SMS send failed: {e}")
    
    def send_sms(self, to: str, message: str, priority: int = 2) -> str:
        """Queue an SMS for sending"""
        notification = Notification(
            id=str(uuid.uuid4()),
            type="sms",
            recipient=to,
            title="SMS Alert",
            body=message[:160],  # Truncate to 160 chars
            priority=priority
        )
        self.queue.append(notification)
        return notification.id
    
    def send_emergency_sms(self, to: str, incident_type: str, location: str) -> str:
        """Send emergency SMS alert"""
        message = f"🚨 EMERGENCY: {incident_type} at {location}. Immediate response required."
        return self.send_sms(to, message, priority=1)
    
    def get_stats(self) -> Dict:
        """Get SMS notifier statistics"""
        return {
            'configured': self.is_configured,
            'queue_size': len(self.queue),
            'is_running': self._is_running
        }


# ============================================
# PUSH NOTIFIER
# ============================================

class PushNotifier:
    """
    Handles push notifications to mobile apps and web clients
    Uses WebSocket for real-time delivery
    """
    
    def __init__(self):
        self.active_connections = {}  # user_id -> session_id
        self.message_queue = deque(maxlen=2000)
    
    def register_connection(self, user_id: int, session_id: str):
        """Register a user's WebSocket connection"""
        if user_id not in self.active_connections:
            self.active_connections[user_id] = []
        self.active_connections[user_id].append(session_id)
        logger.debug(f"Push connection registered for user {user_id}")
    
    def unregister_connection(self, user_id: int, session_id: str):
        """Unregister a user's WebSocket connection"""
        if user_id in self.active_connections:
            if session_id in self.active_connections[user_id]:
                self.active_connections[user_id].remove(session_id)
            if not self.active_connections[user_id]:
                del self.active_connections[user_id]
    
    def send_push(self, user_id: int, title: str, body: str, data: Dict = None) -> bool:
        """Send push notification to a specific user"""
        if user_id not in self.active_connections:
            logger.debug(f"No active connection for user {user_id}")
            return False
        
        notification = {
            'id': str(uuid.uuid4()),
            'title': title,
            'body': body,
            'data': data or {},
            'timestamp': datetime.utcnow().isoformat()
        }
        
        # Send via WebSocket to user's room
        socketio.emit('push_notification', notification, room=f"user_{user_id}")
        logger.debug(f"Push notification sent to user {user_id}: {title}")
        return True
    
    def broadcast_to_role(self, role: str, title: str, body: str, data: Dict = None):
        """Broadcast push notification to all users with a specific role"""
        socketio.emit('push_notification', {
            'id': str(uuid.uuid4()),
            'title': title,
            'body': body,
            'role': role,
            'data': data or {},
            'timestamp': datetime.utcnow().isoformat()
        }, room=f"role_{role}")
        logger.debug(f"Push broadcast to role {role}: {title}")


# ============================================
# ALERT MANAGER
# ============================================

class AlertManager:
    """
    Manages real-time alerts and broadcasts to control room
    """
    
    def __init__(self):
        self.alerts = deque(maxlen=500)  # Store last 500 alerts
        self.alert_handlers = {}
        self._processing_thread = None
        self._is_running = False
    
    def start_processor(self):
        """Start background alert processor"""
        if self._processing_thread is None:
            self._is_running = True
            self._processing_thread = threading.Thread(target=self._process_alerts)
            self._processing_thread.daemon = True
            self._processing_thread.start()
            logger.info("Alert processor started")
    
    def _process_alerts(self):
        """Process and broadcast alerts"""
        # Alerts are processed in real-time, so this is mostly for cleanup
        while self._is_running:
            import time
            time.sleep(60)
            self._cleanup_old_alerts()
    
    def _cleanup_old_alerts(self):
        """Remove alerts older than 24 hours"""
        cutoff = datetime.utcnow().timestamp() - (24 * 3600)
        # Deque automatically handles cleanup with maxlen
        pass
    
    def create_alert(self, alert_type: str, severity: str, title: str, message: str,
                     source: str = 'system', entity_id: int = None,
                     entity_type: str = None, data: Dict = None) -> Alert:
        """Create and broadcast a new alert"""
        alert = Alert(
            id=str(uuid.uuid4()),
            type=alert_type,
            severity=severity,
            title=title,
            message=message,
            source=source,
            entity_id=entity_id,
            entity_type=entity_type,
            data=data or {}
        )
        
        self.alerts.appendleft(alert)
        
        # Broadcast via WebSocket
        socketio.emit('new_alert', alert.to_dict(), broadcast=True)
        
        # Also send to specific rooms based on severity
        if severity == 'critical':
            socketio.emit('critical_alert', alert.to_dict(), room='control_room')
        
        logger.info(f"Alert created: {severity.upper()} - {title}")
        
        # Store in database if needed
        self._store_alert(alert)
        
        return alert
    
    def _store_alert(self, alert: Alert):
        """Store alert in database for persistence"""
        try:
            from app.models.incident import IncidentAlert
            
            # Create database record
            db_alert = IncidentAlert(
                incident_id=alert.entity_id if alert.entity_type == 'incident' else None,
                alert_type=alert.type,
                recipient='control_room',
                message=alert.message,
                status='sent',
                sent_at=datetime.utcnow()
            )
            db.session.add(db_alert)
            db.session.commit()
        except Exception as e:
            logger.error(f"Failed to store alert: {e}")
    
    def get_active_alerts(self, limit: int = 50) -> List[Dict]:
        """Get recent active alerts"""
        return [alert.to_dict() for alert in list(self.alerts)[:limit]]
    
    def get_alerts_by_severity(self, severity: str) -> List[Dict]:
        """Get alerts by severity"""
        return [alert.to_dict() for alert in self.alerts if alert.severity == severity]
    
    def clear_alerts(self):
        """Clear all alerts"""
        self.alerts.clear()
        logger.info("All alerts cleared")


# ============================================
# NOTIFICATION SERVICE (Main Service)
# ============================================

class NotificationService:
    """
    Main Notification Service orchestrating all notification methods
    """
    
    def __init__(self, app=None):
        self.app = app
        self.email_notifier = None
        self.sms_notifier = None
        self.push_notifier = None
        self.alert_manager = None
        self._is_initialized = False
        
        if app:
            self.init_service(app)
    
    def init_service(self, app):
        """Initialize notification service"""
        self.app = app
        
        # Initialize components
        self.email_notifier = EmailNotifier(app)
        self.sms_notifier = SMSNotifier(app)
        self.push_notifier = PushNotifier()
        self.alert_manager = AlertManager()
        self.alert_manager.start_processor()
        
        self._is_initialized = True
        logger.info("Notification Service initialized successfully")
    
    # ============================================
    # CONVENIENCE METHODS
    # ============================================
    
    def send_emergency_notification(self, recipients: List[str], incident_type: str,
                                     location: str, severity: str, send_sms: bool = True,
                                     send_email: bool = True):
        """Send emergency notifications via multiple channels"""
        
        # Create alert first
        alert = self.alert_manager.create_alert(
            alert_type='emergency',
            severity=severity,
            title=f"Emergency: {incident_type}",
            message=f"{incident_type.upper()} reported at {location}",
            source='system'
        )
        
        # Send emails
        if send_email and self.email_notifier:
            for recipient in recipients:
                self.email_notifier.send_emergency_alert(recipient, incident_type, location, severity)
        
        # Send SMS (only for critical emergencies)
        if send_sms and severity == 'critical' and self.sms_notifier:
            for recipient in recipients:
                if recipient.startswith('+'):
                    self.sms_notifier.send_emergency_sms(recipient, incident_type, location)
        
        # Broadcast push notifications
        if self.push_notifier:
            self.push_notifier.broadcast_to_role(
                'control_room',
                f"🚨 {incident_type.upper()}",
                f"Location: {location} | Severity: {severity}",
                {'incident_type': incident_type, 'location': location, 'severity': severity}
            )
        
        return alert
    
    def send_corridor_notification(self, vehicle_reg: str, corridor_id: int,
                                    status: str, control_room_email: str = None):
        """Send corridor status notifications"""
        
        # Create alert
        alert = self.alert_manager.create_alert(
            alert_type='corridor',
            severity='high' if status == 'active' else 'medium',
            title=f"Green Corridor {status.upper()}",
            message=f"Corridor {corridor_id} for vehicle {vehicle_reg} is {status}",
            source='system',
            entity_id=corridor_id,
            entity_type='corridor'
        )
        
        # Send email to control room
        if control_room_email and self.email_notifier:
            self.email_notifier.send_corridor_alert(control_room_email, vehicle_reg, corridor_id, status)
        
        # Broadcast to control room
        if self.push_notifier:
            self.push_notifier.broadcast_to_role(
                'control_room',
                f"🚦 Corridor {status.upper()}",
                f"Vehicle {vehicle_reg} | Corridor {corridor_id}",
                {'corridor_id': corridor_id, 'vehicle_reg': vehicle_reg, 'status': status}
            )
        
        return alert
    
    def send_incident_update(self, incident_id: int, incident_type: str,
                              status: str, control_room_recipients: List[str] = None):
        """Send incident status updates"""
        
        alert = self.alert_manager.create_alert(
            alert_type='incident',
            severity='medium',
            title=f"Incident Update: {incident_type}",
            message=f"Incident status changed to {status}",
            source='system',
            entity_id=incident_id,
            entity_type='incident'
        )
        
        if control_room_recipients and self.email_notifier:
            for recipient in control_room_recipients:
                self.email_notifier.send_email(
                    recipient,
                    f"Incident {incident_id} Status Update",
                    f"<p>Incident {incident_id} status is now: <strong>{status}</strong></p>",
                    priority=2
                )
        
        return alert
    
    def send_system_alert(self, title: str, message: str, severity: str = 'info',
                           recipients: List[str] = None):
        """Send system alert"""
        
        alert = self.alert_manager.create_alert(
            alert_type='system',
            severity=severity,
            title=title,
            message=message,
            source='system'
        )
        
        if recipients and self.email_notifier:
            for recipient in recipients:
                self.email_notifier.send_email(recipient, f"System Alert: {title}", message, priority=2)
        
        return alert
    
    def send_vehicle_alert(self, vehicle_id: int, vehicle_reg: str,
                            alert_type: str, message: str, severity: str = 'medium'):
        """Send vehicle-specific alert"""
        
        alert = self.alert_manager.create_alert(
            alert_type='vehicle',
            severity=severity,
            title=f"Vehicle Alert: {vehicle_reg}",
            message=message,
            source='system',
            entity_id=vehicle_id,
            entity_type='vehicle'
        )
        
        # Send to vehicle driver's push notification
        if self.push_notifier:
            self.push_notifier.broadcast_to_role(
                'emergency_driver',
                f"🚑 {alert_type.upper()}",
                message,
                {'vehicle_id': vehicle_id, 'alert_type': alert_type}
            )
        
        return alert
    
    def get_stats(self) -> Dict:
        """Get service statistics"""
        return {
            'initialized': self._is_initialized,
            'email': self.email_notifier.get_stats() if self.email_notifier else None,
            'sms': self.sms_notifier.get_stats() if self.sms_notifier else None,
            'active_alerts': len(self.alert_manager.alerts) if self.alert_manager else 0
        }
    
    def health_check(self) -> bool:
        """Check if service is healthy"""
        return self._is_initialized
    
    def shutdown(self):
        """Shutdown notification service"""
        if self.email_notifier:
            self.email_notifier._is_running = False
        if self.sms_notifier:
            self.sms_notifier._is_running = False
        if self.alert_manager:
            self.alert_manager._is_running = False
        logger.info("Notification Service shut down")


# ============================================
# SERVICE FACTORY FUNCTIONS
# ============================================

_notification_service = None


def get_notification_service(app=None) -> NotificationService:
    """Get or create notification service instance"""
    global _notification_service
    
    if _notification_service is None:
        _notification_service = NotificationService(app)
    
    return _notification_service


def shutdown_notification_service():
    """Shutdown notification service"""
    global _notification_service
    if _notification_service:
        _notification_service.shutdown()
        _notification_service = None
        logger.info("Notification service shut down")


# ============================================
# EXPORTS
# ============================================

__all__ = [
    'NotificationService',
    'EmailNotifier',
    'SMSNotifier',
    'PushNotifier',
    'AlertManager',
    'Notification',
    'Alert',
    'get_notification_service',
    'shutdown_notification_service'
]