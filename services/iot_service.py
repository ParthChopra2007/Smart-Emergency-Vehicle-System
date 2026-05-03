"""
Smart Emergency Vehicle Priority System - IoT Service
Handles MQTT communication with traffic signals, sensors, cameras,
and emergency vehicle IoT devices for real-time data exchange
"""

import json
import threading
import time
from datetime import datetime
from typing import Dict, List, Optional, Any, Callable
from dataclasses import dataclass, field
from collections import deque
from loguru import logger
import uuid

from app.extensions import db, socketio, redis_client

# ============================================
# MQTT IMPORTS (Lazy loading)
# ============================================

class MQTTManager:
    """
    MQTT Manager for IoT device communication
    Handles connection, subscription, and message publishing
    """
    
    def __init__(self, app=None):
        self.app = app
        self.client = None
        self.is_connected = False
        self.subscriptions = {}
        self.message_handlers = {}
        self.message_queue = deque(maxlen=10000)
        self._processing_thread = None
        self._is_running = False
        
        # Connection parameters
        self.broker_url = None
        self.broker_port = None
        self.username = None
        self.password = None
        self.client_id = f"sevps_mqtt_{uuid.uuid4().hex[:8]}"
        
        if app:
            self.init_mqtt(app)
    
    def init_mqtt(self, app):
        """Initialize MQTT connection"""
        self.broker_url = app.config.get('MQTT_BROKER_URL')
        self.broker_port = app.config.get('MQTT_BROKER_PORT', 1883)
        self.username = app.config.get('MQTT_USERNAME')
        self.password = app.config.get('MQTT_PASSWORD')
        
        if not self.broker_url:
            logger.warning("MQTT broker not configured. IoT service running in offline mode.")
            return False
        
        try:
            import paho.mqtt.client as mqtt
            self.client = mqtt.Client(client_id=self.client_id)
            
            # Set credentials if provided
            if self.username and self.password:
                self.client.username_pw_set(self.username, self.password)
            
            # Set callbacks
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_message = self._on_message
            self.client.on_publish = self._on_publish
            
            # Connect to broker
            self.client.connect_async(self.broker_url, self.broker_port, 60)
            
            # Start loop in background
            self.client.loop_start()
            
            # Start message processor
            self.start_processor()
            
            logger.info(f"MQTT manager initialized for broker: {self.broker_url}:{self.broker_port}")
            return True
            
        except ImportError:
            logger.warning("paho-mqtt not installed. IoT service disabled.")
            return False
        except Exception as e:
            logger.error(f"MQTT initialization failed: {e}")
            return False
    
    def _on_connect(self, client, userdata, flags, rc):
        """Callback when connected to MQTT broker"""
        if rc == 0:
            self.is_connected = True
            logger.info(f"✅ MQTT connected to {self.broker_url}:{self.broker_port}")
            
            # Resubscribe to all topics
            for topic, qos in self.subscriptions.items():
                self.client.subscribe(topic, qos)
                logger.debug(f"Resubscribed to: {topic}")
        else:
            self.is_connected = False
            logger.error(f"MQTT connection failed with code: {rc}")
    
    def _on_disconnect(self, client, userdata, rc):
        """Callback when disconnected from MQTT broker"""
        self.is_connected = False
        logger.warning(f"MQTT disconnected. Code: {rc}")
    
    def _on_message(self, client, userdata, msg):
        """Callback when message is received"""
        try:
            payload = msg.payload.decode('utf-8')
            data = json.loads(payload) if payload else {}
            
            self.message_queue.append({
                'topic': msg.topic,
                'payload': data,
                'timestamp': datetime.utcnow()
            })
            
            logger.debug(f"MQTT message received: {msg.topic}")
            
        except Exception as e:
            logger.error(f"Error processing MQTT message: {e}")
    
    def _on_publish(self, client, userdata, mid):
        """Callback when message is published"""
        logger.debug(f"MQTT message published. MID: {mid}")
    
    def start_processor(self):
        """Start background message processor"""
        if self._processing_thread is None:
            self._is_running = True
            self._processing_thread = threading.Thread(target=self._process_messages)
            self._processing_thread.daemon = True
            self._processing_thread.start()
            logger.info("MQTT message processor started")
    
    def stop_processor(self):
        """Stop background message processor"""
        self._is_running = False
        if self._processing_thread:
            self._processing_thread.join(timeout=5)
    
    def _process_messages(self):
        """Process queued MQTT messages"""
        while self._is_running:
            try:
                if self.message_queue:
                    msg = self.message_queue.popleft()
                    self._handle_message(msg)
                else:
                    time.sleep(0.1)
            except Exception as e:
                logger.error(f"Message processor error: {e}")
    
    def _handle_message(self, msg: Dict):
        """Route message to appropriate handler"""
        topic = msg['topic']
        payload = msg['payload']
        
        # Find handler for this topic
        for pattern, handler in self.message_handlers.items():
            if self._topic_matches(topic, pattern):
                try:
                    handler(topic, payload)
                except Exception as e:
                    logger.error(f"Handler error for {topic}: {e}")
                break
    
    def _topic_matches(self, topic: str, pattern: str) -> bool:
        """Check if topic matches pattern (supports wildcards)"""
        # Simplified matching - supports exact match and trailing #
        if pattern.endswith('#'):
            return topic.startswith(pattern[:-1])
        return topic == pattern
    
    def subscribe(self, topic: str, handler: Callable, qos: int = 1):
        """Subscribe to a topic"""
        self.subscriptions[topic] = qos
        self.message_handlers[topic] = handler
        
        if self.client and self.is_connected:
            self.client.subscribe(topic, qos)
            logger.info(f"Subscribed to topic: {topic}")
    
    def publish(self, topic: str, payload: Dict, qos: int = 1, retain: bool = False) -> bool:
        """Publish message to a topic"""
        if not self.client or not self.is_connected:
            logger.warning(f"Cannot publish to {topic}: MQTT not connected")
            return False
        
        try:
            message = json.dumps(payload, default=str)
            self.client.publish(topic, message, qos=qos, retain=retain)
            logger.debug(f"Published to {topic}: {payload}")
            return True
        except Exception as e:
            logger.error(f"Publish error: {e}")
            return False
    
    def get_status(self) -> Dict:
        """Get MQTT connection status"""
        return {
            'connected': self.is_connected,
            'broker_url': self.broker_url,
            'broker_port': self.broker_port,
            'client_id': self.client_id,
            'subscriptions': list(self.subscriptions.keys()),
            'queue_size': len(self.message_queue)
        }
    
    def shutdown(self):
        """Shutdown MQTT manager"""
        self.stop_processor()
        if self.client:
            self.client.loop_stop()
            self.client.disconnect()
        logger.info("MQTT manager shut down")


# ============================================
# SIGNAL CONTROLLER
# ============================================

class SignalController:
    """
    Controls traffic signals via MQTT commands
    Sends real-time instructions to physical signal controllers
    """
    
    # MQTT Topics
    TOPIC_COMMAND = "traffic/signal/{signal_id}/command"
    TOPIC_STATUS = "traffic/signal/{signal_id}/status"
    TOPIC_CONFIG = "traffic/signal/{signal_id}/config"
    TOPIC_HEARTBEAT = "traffic/signal/{signal_id}/heartbeat"
    TOPIC_ALERT = "traffic/signal/{signal_id}/alert"
    
    def __init__(self, mqtt_manager: MQTTManager):
        self.mqtt = mqtt_manager
        self.signal_status = {}  # signal_id -> last known status
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Setup MQTT message handlers for signals"""
        
        def handle_status(topic: str, payload: Dict):
            signal_id = self._extract_signal_id(topic)
            if signal_id:
                self.signal_status[signal_id] = {
                    'status': payload,
                    'last_update': datetime.utcnow()
                }
                # Forward to WebSocket for real-time dashboard
                socketio.emit('signal_status_update', {
                    'signal_id': signal_id,
                    'status': payload,
                    'timestamp': datetime.utcnow().isoformat()
                }, broadcast=True)
        
        def handle_heartbeat(topic: str, payload: Dict):
            signal_id = self._extract_signal_id(topic)
            if signal_id:
                from app.models.traffic_signal import find_signal_by_id
                signal = find_signal_by_id(signal_id)
                if signal:
                    signal.update_heartbeat()
        
        def handle_alert(topic: str, payload: Dict):
            signal_id = self._extract_signal_id(topic)
            if signal_id:
                socketio.emit('signal_alert', {
                    'signal_id': signal_id,
                    'alert': payload,
                    'timestamp': datetime.utcnow().isoformat()
                }, broadcast=True)
                logger.warning(f"Signal {signal_id} alert: {payload}")
        
        # Subscribe to topics for all signals (using wildcard)
        self.mqtt.subscribe("traffic/signal/+/status", handle_status)
        self.mqtt.subscribe("traffic/signal/+/heartbeat", handle_heartbeat)
        self.mqtt.subscribe("traffic/signal/+/alert", handle_alert)
    
    def _extract_signal_id(self, topic: str) -> Optional[int]:
        """Extract signal ID from topic"""
        parts = topic.split('/')
        if len(parts) >= 3:
            try:
                return int(parts[2])
            except ValueError:
                return None
        return None
    
    def send_command(self, signal_id: int, command: str, params: Dict = None) -> bool:
        """Send command to a traffic signal"""
        topic = self.TOPIC_COMMAND.format(signal_id=signal_id)
        payload = {
            'command': command,
            'params': params or {},
            'timestamp': datetime.utcnow().isoformat(),
            'command_id': str(uuid.uuid4())
        }
        return self.mqtt.publish(topic, payload, qos=2)
    
    def set_green_corridor(self, signal_id: int, corridor_id: int, vehicle_id: int, duration: int = 60) -> bool:
        """Set signal to green corridor mode"""
        return self.send_command(signal_id, 'GREEN_CORRIDOR', {
            'corridor_id': corridor_id,
            'vehicle_id': vehicle_id,
            'duration_seconds': duration
        })
    
    def set_manual_control(self, signal_id: int, direction: str, duration: int = 30) -> bool:
        """Set manual control on signal"""
        return self.send_command(signal_id, 'MANUAL_CONTROL', {
            'direction': direction,
            'duration_seconds': duration
        })
    
    def reset_signal(self, signal_id: int) -> bool:
        """Reset signal to normal operation"""
        return self.send_command(signal_id, 'RESET', {})
    
    def update_timing(self, signal_id: int, timings: Dict) -> bool:
        """Update signal timing configuration"""
        return self.send_command(signal_id, 'UPDATE_TIMING', timings)
    
    def get_signal_status(self, signal_id: int) -> Optional[Dict]:
        """Get last known status of a signal"""
        return self.signal_status.get(signal_id)


# ============================================
# VEHICLE TRACKER (IoT)
# ============================================

class VehicleIoTracker:
    """
    Tracks emergency vehicles via IoT devices
    Receives GPS data, status updates, and siren status from vehicles
    """
    
    # MQTT Topics
    TOPIC_LOCATION = "vehicle/{vehicle_id}/location"
    TOPIC_STATUS = "vehicle/{vehicle_id}/status"
    TOPIC_SIREN = "vehicle/{vehicle_id}/siren"
    TOPIC_ALERT = "vehicle/{vehicle_id}/alert"
    TOPIC_CORRIDOR = "vehicle/{vehicle_id}/corridor"
    
    def __init__(self, mqtt_manager: MQTTManager):
        self.mqtt = mqtt_manager
        self.vehicle_status = {}  # vehicle_id -> last known status
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Setup MQTT message handlers for vehicles"""
        
        def handle_location(topic: str, payload: Dict):
            vehicle_id = self._extract_vehicle_id(topic)
            if vehicle_id:
                self.vehicle_status[vehicle_id] = {
                    'location': payload,
                    'last_update': datetime.utcnow()
                }
                
                # Forward to GPS tracker
                from app.services.gps_tracker import get_gps_service
                gps_service = get_gps_service()
                
                # Update location (registration number would need to be looked up)
                gps_service.update_location(
                    vehicle_id=vehicle_id,
                    registration_number=f"VEH_{vehicle_id}",
                    latitude=payload.get('latitude', 0),
                    longitude=payload.get('longitude', 0),
                    speed=payload.get('speed', 0),
                    heading=payload.get('heading', 0)
                )
                
                # Emit WebSocket update
                socketio.emit('vehicle_iot_location', {
                    'vehicle_id': vehicle_id,
                    'location': payload,
                    'timestamp': datetime.utcnow().isoformat()
                }, broadcast=True)
        
        def handle_siren(topic: str, payload: Dict):
            vehicle_id = self._extract_vehicle_id(topic)
            if vehicle_id:
                is_active = payload.get('active', False)
                
                # Update vehicle siren status in database
                from app.models.vehicle import find_vehicle_by_id
                vehicle = find_vehicle_by_id(vehicle_id)
                if vehicle:
                    vehicle.is_siren_active = is_active
                    db.session.commit()
                
                socketio.emit('vehicle_siren_update', {
                    'vehicle_id': vehicle_id,
                    'is_active': is_active,
                    'timestamp': datetime.utcnow().isoformat()
                }, broadcast=True)
        
        def handle_corridor(topic: str, payload: Dict):
            vehicle_id = self._extract_vehicle_id(topic)
            if vehicle_id:
                socketio.emit('vehicle_corridor_update', {
                    'vehicle_id': vehicle_id,
                    'corridor_data': payload,
                    'timestamp': datetime.utcnow().isoformat()
                }, broadcast=True)
        
        # Subscribe to topics (using wildcards)
        self.mqtt.subscribe("vehicle/+/location", handle_location)
        self.mqtt.subscribe("vehicle/+/siren", handle_siren)
        self.mqtt.subscribe("vehicle/+/corridor", handle_corridor)
    
    def _extract_vehicle_id(self, topic: str) -> Optional[int]:
        """Extract vehicle ID from topic"""
        parts = topic.split('/')
        if len(parts) >= 2:
            try:
                return int(parts[1])
            except ValueError:
                return None
        return None
    
    def send_location_command(self, vehicle_id: int, command: str, params: Dict = None) -> bool:
        """Send command to vehicle GPS device"""
        topic = f"vehicle/{vehicle_id}/command"
        payload = {
            'command': command,
            'params': params or {},
            'timestamp': datetime.utcnow().isoformat()
        }
        return self.mqtt.publish(topic, payload)
    
    def request_location(self, vehicle_id: int) -> bool:
        """Request current location from vehicle"""
        return self.send_location_command(vehicle_id, 'GET_LOCATION')
    
    def get_vehicle_status(self, vehicle_id: int) -> Optional[Dict]:
        """Get last known status of a vehicle"""
        return self.vehicle_status.get(vehicle_id)


# ============================================
# SENSOR DATA PROCESSOR
# ============================================

class SensorDataProcessor:
    """
    Processes data from various IoT sensors (traffic cameras, road sensors, weather stations)
    """
    
    # MQTT Topics
    TOPIC_CAMERA = "sensor/camera/{camera_id}/detection"
    TOPIC_TRAFFIC = "sensor/traffic/{sensor_id}/data"
    TOPIC_WEATHER = "sensor/weather/{station_id}/data"
    TOPIC_ROAD = "sensor/road/{sensor_id}/condition"
    
    def __init__(self, mqtt_manager: MQTTManager):
        self.mqtt = mqtt_manager
        self.camera_data = {}
        self.traffic_data = {}
        self.weather_data = {}
        self._setup_handlers()
    
    def _setup_handlers(self):
        """Setup MQTT message handlers for sensors"""
        
        def handle_camera(topic: str, payload: Dict):
            camera_id = self._extract_id(topic, 'camera')
            if camera_id:
                self.camera_data[camera_id] = {
                    'data': payload,
                    'last_update': datetime.utcnow()
                }
                
                # Process vehicle detection from camera
                if payload.get('detections'):
                    self._process_camera_detections(camera_id, payload['detections'])
        
        def handle_traffic(topic: str, payload: Dict):
            sensor_id = self._extract_id(topic, 'traffic')
            if sensor_id:
                self.traffic_data[sensor_id] = {
                    'data': payload,
                    'last_update': datetime.utcnow()
                }
                
                # Update traffic density in database
                self._update_traffic_density(sensor_id, payload)
        
        def handle_weather(topic: str, payload: Dict):
            station_id = self._extract_id(topic, 'weather')
            if station_id:
                self.weather_data[station_id] = {
                    'data': payload,
                    'last_update': datetime.utcnow()
                }
        
        # Subscribe to sensor topics
        self.mqtt.subscribe("sensor/camera/+/detection", handle_camera)
        self.mqtt.subscribe("sensor/traffic/+/data", handle_traffic)
        self.mqtt.subscribe("sensor/weather/+/data", handle_weather)
    
    def _extract_id(self, topic: str, sensor_type: str) -> Optional[str]:
        """Extract sensor ID from topic"""
        parts = topic.split('/')
        if len(parts) >= 3:
            return parts[2]
        return None
    
    def _process_camera_detections(self, camera_id: str, detections: List):
        """Process vehicle detections from camera"""
        # Forward to AI detection service for processing
        from app.services.ai_detection import get_ai_service
        ai_service = get_ai_service()
        
        # Process each detection
        for detection in detections:
            if detection.get('is_emergency'):
                # Emergency vehicle detected - notify control room
                socketio.emit('emergency_vehicle_detected', {
                    'camera_id': camera_id,
                    'detection': detection,
                    'timestamp': datetime.utcnow().isoformat()
                }, broadcast=True)
                logger.info(f"Emergency vehicle detected by camera {camera_id}")
    
    def _update_traffic_density(self, sensor_id: str, data: Dict):
        """Update traffic density in database based on sensor data"""
        # In production, this would update the traffic_signal or road segment
        
        density = data.get('density', 'low')
        vehicle_count = data.get('vehicle_count', 0)
        
        # Emit traffic update
        socketio.emit('traffic_density_update', {
            'sensor_id': sensor_id,
            'density': density,
            'vehicle_count': vehicle_count,
            'timestamp': datetime.utcnow().isoformat()
        }, broadcast=True)
    
    def get_camera_data(self, camera_id: str) -> Optional[Dict]:
        """Get last known data from a camera"""
        return self.camera_data.get(camera_id)
    
    def get_traffic_data(self, sensor_id: str) -> Optional[Dict]:
        """Get last known data from a traffic sensor"""
        return self.traffic_data.get(sensor_id)
    
    def get_weather_data(self, station_id: str) -> Optional[Dict]:
        """Get last known weather data"""
        return self.weather_data.get(station_id)


# ============================================
# IOT SERVICE (Main Service)
# ============================================

class IoTService:
    """
    Main IoT Service orchestrating all IoT components
    """
    
    def __init__(self, app=None):
        self.app = app
        self.mqtt_manager = None
        self.signal_controller = None
        self.vehicle_tracker = None
        self.sensor_processor = None
        self._is_initialized = False
        
        if app:
            self.init_service(app)
    
    def init_service(self, app):
        """Initialize IoT service"""
        self.app = app
        
        # Initialize MQTT manager
        self.mqtt_manager = MQTTManager(app)
        
        # Initialize components
        self.signal_controller = SignalController(self.mqtt_manager)
        self.vehicle_tracker = VehicleIoTracker(self.mqtt_manager)
        self.sensor_processor = SensorDataProcessor(self.mqtt_manager)
        
        self._is_initialized = True
        logger.info("IoT Service initialized successfully")
    
    def get_signal_controller(self) -> SignalController:
        """Get signal controller instance"""
        return self.signal_controller
    
    def get_vehicle_tracker(self) -> VehicleIoTracker:
        """Get vehicle tracker instance"""
        return self.vehicle_tracker
    
    def get_sensor_processor(self) -> SensorDataProcessor:
        """Get sensor processor instance"""
        return self.sensor_processor
    
    def get_mqtt_status(self) -> Dict:
        """Get MQTT connection status"""
        if self.mqtt_manager:
            return self.mqtt_manager.get_status()
        return {'connected': False, 'error': 'MQTT not initialized'}
    
    def publish_emergency_broadcast(self, area: str, incident_type: str, severity: str) -> bool:
        """
        Broadcast emergency message to all IoT devices in an area
        """
        if not self.mqtt_manager:
            return False
        
        topic = f"broadcast/emergency/{area}"
        payload = {
            'incident_type': incident_type,
            'severity': severity,
            'timestamp': datetime.utcnow().isoformat(),
            'broadcast_id': str(uuid.uuid4())
        }
        return self.mqtt_manager.publish(topic, payload, qos=2, retain=False)
    
    def get_stats(self) -> Dict:
        """Get service statistics"""
        return {
            'initialized': self._is_initialized,
            'mqtt_status': self.get_mqtt_status() if self.mqtt_manager else None,
            'signal_controller_ready': self.signal_controller is not None,
            'vehicle_tracker_ready': self.vehicle_tracker is not None,
            'sensor_processor_ready': self.sensor_processor is not None
        }
    
    def health_check(self) -> bool:
        """Check if service is healthy"""
        if not self._is_initialized:
            return False
        if self.mqtt_manager:
            return self.mqtt_manager.is_connected
        return False
    
    def shutdown(self):
        """Shutdown IoT service"""
        if self.mqtt_manager:
            self.mqtt_manager.shutdown()
        logger.info("IoT Service shut down")


# ============================================
# SERVICE FACTORY FUNCTIONS
# ============================================

_iot_service = None


def get_iot_service(app=None) -> IoTService:
    """Get or create IoT service instance"""
    global _iot_service
    
    if _iot_service is None:
        _iot_service = IoTService(app)
    
    return _iot_service


def shutdown_iot_service():
    """Shutdown IoT service"""
    global _iot_service
    if _iot_service:
        _iot_service.shutdown()
        _iot_service = None
        logger.info("IoT service shut down")


# ============================================
# EXPORTS
# ============================================

__all__ = [
    'IoTService',
    'MQTTManager',
    'SignalController',
    'VehicleIoTracker',
    'SensorDataProcessor',
    'get_iot_service',
    'shutdown_iot_service'
]