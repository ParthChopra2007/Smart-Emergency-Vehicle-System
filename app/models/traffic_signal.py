"""
Smart Emergency Vehicle Priority System - Traffic Signal Model
This file defines the TrafficSignal model for managing traffic intersections
and controlling signals for green corridor creation
"""

from datetime import datetime, timedelta
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum, Float, JSON, ForeignKey, Text
from sqlalchemy.orm import relationship
import enum
import uuid
from geopy.distance import geodesic
from loguru import logger

from app.extensions import db

# ============================================
# ENUMS (Choices for signal fields)
# ============================================

class SignalStatus(enum.Enum):
    """Current status of the traffic signal"""
    NORMAL = "normal"           # Normal operation (automatic timing)
    GREEN_CORRIDOR = "green_corridor"  # Green corridor active
    MANUAL = "manual"           # Manually controlled
    FLASHING = "flashing"       # Flashing mode (emergency/yellow)
    RED_ALERT = "red_alert"     # All red (emergency situation)
    MAINTENANCE = "maintenance" # Under maintenance
    OFF = "off"                 # Signal off

class SignalDirection(enum.Enum):
    """Direction of traffic flow"""
    NORTHBOUND = "northbound"
    SOUTHBOUND = "southbound"
    EASTBOUND = "eastbound"
    WESTBOUND = "westbound"
    NORTHEAST = "northeast"
    NORTHWEST = "northwest"
    SOUTHEAST = "southeast"
    SOUTHWEST = "southwest"

class LaneType(enum.Enum):
    """Type of lane at intersection"""
    STRAIGHT = "straight"
    LEFT_TURN = "left_turn"
    RIGHT_TURN = "right_turn"
    U_TURN = "u_turn"
    EMERGENCY_LANE = "emergency_lane"

class TrafficDensity(enum.Enum):
    """Traffic density level"""
    LOW = "low"           # Light traffic (0-20 vehicles/minute)
    MEDIUM = "medium"     # Moderate traffic (20-50 vehicles/minute)
    HIGH = "high"         # Heavy traffic (50-100 vehicles/minute)
    GRIDLOCK = "gridlock" # Severe congestion (100+ vehicles/minute)

# ============================================
# TRAFFIC SIGNAL MODEL
# ============================================

class TrafficSignal(db.Model):
    """
    Traffic Signal model for managing traffic intersections
    Supports dynamic signal control and green corridor creation
    """
    __tablename__ = 'traffic_signals'
    __table_args__ = (
        db.Index('idx_signal_location', 'latitude', 'longitude'),
        db.Index('idx_signal_status', 'status'),
        db.Index('idx_signal_intersection', 'intersection_id', 'intersection_name'),
        db.Index('idx_signal_zone', 'zone_id'),
        {'schema': 'public'}
    )

    # ============================================
    # BASIC IDENTIFICATION
    # ============================================
    id = Column(Integer, primary_key=True)
    signal_uuid = Column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    intersection_id = Column(String(100), unique=True, nullable=False)  # e.g., "INT_001"
    intersection_name = Column(String(255), nullable=False)  # e.g., "Connaught Place Crossing"
    
    # ============================================
    # LOCATION INFORMATION
    # ============================================
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    address = Column(String(500), nullable=True)
    city = Column(String(100), nullable=True)
    zone_id = Column(String(100), nullable=True)  # Traffic zone identifier
    
    # ============================================
    # SIGNAL CONFIGURATION
    # ============================================
    # Timing configuration (in seconds)
    default_cycle_time = Column(Integer, default=120)  # Complete cycle time
    green_time_north = Column(Integer, default=30)
    green_time_south = Column(Integer, default=30)
    green_time_east = Column(Integer, default=30)
    green_time_west = Column(Integer, default=30)
    yellow_time = Column(Integer, default=5)
    all_red_time = Column(Integer, default=2)
    
    # Current active configuration
    current_status = Column(Enum(SignalStatus), default=SignalStatus.NORMAL)
    current_green_direction = Column(Enum(SignalDirection), nullable=True)
    current_cycle_remaining = Column(Integer, nullable=True)  # Seconds remaining in current cycle
    
    # ============================================
    # GREEN CORRIDOR SUPPORT
    # ============================================
    supports_green_corridor = Column(Boolean, default=True)
    is_iot_enabled = Column(Boolean, default=True)  # Can receive remote commands
    mqtt_topic = Column(String(255), nullable=True)  # MQTT topic for this signal
    controller_ip = Column(String(45), nullable=True)  # Signal controller IP
    controller_port = Column(Integer, nullable=True)   # Signal controller port
    
    # Active corridor information
    active_corridor_id = Column(Integer, ForeignKey('green_corridors.id'), nullable=True)
    corridor_active_until = Column(DateTime, nullable=True)
    corridor_vehicle_id = Column(Integer, nullable=True)  # Which vehicle requested
    
    # ============================================
    # TRAFFIC DENSITY & INTELLIGENCE
    # ============================================
    current_density = Column(Enum(TrafficDensity), default=TrafficDensity.LOW)
    density_north = Column(Integer, default=0)  # Vehicles per minute
    density_south = Column(Integer, default=0)
    density_east = Column(Integer, default=0)
    density_west = Column(Integer, default=0)
    last_density_update = Column(DateTime, nullable=True)
    
    # Adaptive timing (AI-adjusted)
    adaptive_mode_enabled = Column(Boolean, default=True)
    ai_optimized_green_times = Column(JSON, default={})  # Store optimized timings
    
    # ============================================
    # CAMERA & DETECTION
    # ============================================
    has_camera = Column(Boolean, default=False)
    camera_url = Column(String(500), nullable=True)
    camera_feed_active = Column(Boolean, default=False)
    vehicle_detection_enabled = Column(Boolean, default=True)
    
    # Detected emergency vehicles
    emergency_vehicle_detected = Column(Boolean, default=False)
    detected_vehicle_type = Column(String(50), nullable=True)
    detection_timestamp = Column(DateTime, nullable=True)
    
    # ============================================
    # NETWORK & CONNECTIVITY
    # ============================================
    is_online = Column(Boolean, default=True)
    last_heartbeat = Column(DateTime, nullable=True)
    firmware_version = Column(String(50), default="1.0.0")
    network_latency_ms = Column(Integer, default=0)
    
    # ============================================
    # STATISTICS & METRICS
    # ============================================
    total_corridors_served = Column(Integer, default=0)
    total_emergency_vehicles_served = Column(Integer, default=0)
    time_saved_for_emergencies = Column(Float, default=0.0)  # Total minutes saved
    avg_vehicles_per_hour = Column(Integer, default=0)
    
    # ============================================
    # ALERTS & MAINTENANCE
    # ============================================
    error_code = Column(Integer, default=0)
    error_message = Column(Text, nullable=True)
    last_maintenance_date = Column(DateTime, nullable=True)
    maintenance_notes = Column(Text, nullable=True)
    
    # ============================================
    # METADATA
    # ============================================
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    notes = Column(Text, nullable=True)
    metadata = Column(JSON, default={})
    
    # ============================================
    # RELATIONSHIPS
    # ============================================
    active_corridor = relationship("GreenCorridor", foreign_keys=[active_corridor_id])
    
    # ============================================
    # INITIALIZER
    # ============================================
    def __init__(self, intersection_id, intersection_name, latitude, longitude, **kwargs):
        self.intersection_id = intersection_id
        self.intersection_name = intersection_name
        self.latitude = latitude
        self.longitude = longitude
        self.signal_uuid = str(uuid.uuid4())
        self.mqtt_topic = f"traffic/signals/{intersection_id}"
        
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    # ============================================
    # SIGNAL CONTROL METHODS
    # ============================================
    
    def set_green_corridor(self, corridor_id, vehicle_id, duration_seconds=30):
        """
        Activate green corridor mode for this signal
        Forces green light for the direction of approaching emergency vehicle
        """
        if not self.supports_green_corridor:
            logger.warning(f"Signal {self.intersection_id} does not support green corridor")
            return False
        
        # Save previous status before changing
        previous_status = self.current_status
        previous_direction = self.current_green_direction
        
        # Activate corridor
        self.current_status = SignalStatus.GREEN_CORRIDOR
        self.active_corridor_id = corridor_id
        self.corridor_active_until = datetime.utcnow() + timedelta(seconds=duration_seconds)
        self.corridor_vehicle_id = vehicle_id
        self.total_corridors_served += 1
        
        db.session.commit()
        
        # Publish command to physical signal (MQTT)
        self._send_signal_command('GREEN_CORRIDOR_ACTIVATE', {
            'duration': duration_seconds,
            'corridor_id': corridor_id
        })
        
        logger.info(f"🚦 Green corridor activated on {self.intersection_name} for vehicle {vehicle_id}")
        
        # Schedule automatic deactivation
        # (In production, this would be a Celery task)
        
        return True
    
    def deactivate_green_corridor(self):
        """Deactivate green corridor mode and return to normal"""
        if self.current_status == SignalStatus.GREEN_CORRIDOR:
            # Calculate time saved
            if self.corridor_active_until:
                remaining = max(0, (self.corridor_active_until - datetime.utcnow()).total_seconds())
                time_used = 30 - remaining
                self.time_saved_for_emergencies += time_used / 60  # Convert to minutes
            
            self.total_emergency_vehicles_served += 1
            
            # Reset to normal
            self.current_status = SignalStatus.NORMAL
            self.active_corridor_id = None
            self.corridor_active_until = None
            self.corridor_vehicle_id = None
            db.session.commit()
            
            # Send command to physical signal
            self._send_signal_command('GREEN_CORRIDOR_DEACTIVATE', {})
            
            logger.info(f"🚦 Green corridor deactivated on {self.intersection_name}")
            return True
        
        return False
    
    def manual_control(self, direction, duration_seconds=30):
        """
        Manually control the signal
        direction: 'north', 'south', 'east', 'west', 'all_red', 'flashing'
        """
        self.current_status = SignalStatus.MANUAL
        
        # Map direction to enum
        direction_map = {
            'north': SignalDirection.NORTHBOUND,
            'south': SignalDirection.SOUTHBOUND,
            'east': SignalDirection.EASTBOUND,
            'west': SignalDirection.WESTBOUND
        }
        
        if direction in direction_map:
            self.current_green_direction = direction_map[direction]
            self.current_cycle_remaining = duration_seconds
        elif direction == 'all_red':
            self.current_green_direction = None
            self.current_status = SignalStatus.RED_ALERT
        elif direction == 'flashing':
            self.current_status = SignalStatus.FLASHING
        
        db.session.commit()
        
        # Send command to physical signal
        self._send_signal_command('MANUAL_CONTROL', {
            'direction': direction,
            'duration': duration_seconds
        })
        
        logger.info(f"🚦 Manual control on {self.intersection_name}: {direction}")
        return True
    
    def update_timing(self, direction, green_time_seconds):
        """Update green time for a specific direction"""
        if direction == 'north':
            self.green_time_north = green_time_seconds
        elif direction == 'south':
            self.green_time_south = green_time_seconds
        elif direction == 'east':
            self.green_time_east = green_time_seconds
        elif direction == 'west':
            self.green_time_west = green_time_seconds
        else:
            return False
        
        db.session.commit()
        
        # Send timing update to physical signal
        self._send_signal_command('UPDATE_TIMING', {
            'direction': direction,
            'green_time': green_time_seconds
        })
        
        logger.info(f"Timing updated for {self.intersection_name} - {direction}: {green_time_seconds}s")
        return True
    
    def reset_to_default(self):
        """Reset signal to default normal operation"""
        self.current_status = SignalStatus.NORMAL
        self.active_corridor_id = None
        self.corridor_active_until = None
        self.corridor_vehicle_id = None
        self.current_green_direction = None
        self.current_cycle_remaining = None
        
        db.session.commit()
        
        self._send_signal_command('RESET', {})
        
        logger.info(f"Signal {self.intersection_name} reset to default")
        return True
    
    # ============================================
    # TRAFFIC DENSITY METHODS
    # ============================================
    
    def update_traffic_density(self, north_count=0, south_count=0, east_count=0, west_count=0):
        """Update traffic density from sensors/cameras"""
        self.density_north = north_count
        self.density_south = south_count
        self.density_east = east_count
        self.density_west = west_count
        self.last_density_update = datetime.utcnow()
        
        # Calculate overall density level
        max_density = max(north_count, south_count, east_count, west_count)
        
        if max_density >= 100:
            self.current_density = TrafficDensity.GRIDLOCK
        elif max_density >= 50:
            self.current_density = TrafficDensity.HIGH
        elif max_density >= 20:
            self.current_density = TrafficDensity.MEDIUM
        else:
            self.current_density = TrafficDensity.LOW
        
        db.session.commit()
        
        # If adaptive mode is enabled, suggest timing adjustments
        if self.adaptive_mode_enabled:
            self._suggest_adaptive_timing()
        
        logger.debug(f"Traffic density updated for {self.intersection_name}: {self.current_density.value}")
        return self.current_density
    
    def _suggest_adaptive_timing(self):
        """Suggest adaptive timing based on traffic density"""
        suggestions = {}
        
        # Simple adaptive logic (can be enhanced with AI)
        if self.current_density == TrafficDensity.HIGH:
            # Increase green time for busy directions
            if self.density_north > 50:
                suggestions['north'] = min(60, self.green_time_north + 10)
            if self.density_south > 50:
                suggestions['south'] = min(60, self.green_time_south + 10)
            if self.density_east > 50:
                suggestions['east'] = min(60, self.green_time_east + 10)
            if self.density_west > 50:
                suggestions['west'] = min(60, self.green_time_west + 10)
        
        elif self.current_density == TrafficDensity.GRIDLOCK:
            # Special handling for gridlock
            suggestions['note'] = "Consider manual intervention"
        
        self.ai_optimized_green_times = suggestions
        return suggestions
    
    # ============================================
    # EMERGENCY VEHICLE DETECTION
    # ============================================
    
    def detect_emergency_vehicle(self, vehicle_type, direction):
        """Detect emergency vehicle approaching the intersection"""
        self.emergency_vehicle_detected = True
        self.detected_vehicle_type = vehicle_type
        self.detection_timestamp = datetime.utcnow()
        db.session.commit()
        
        logger.info(f"🚨 Emergency vehicle detected at {self.intersection_name}: {vehicle_type} from {direction}")
        
        # Return the appropriate direction to set green
        direction_map = {
            'north': SignalDirection.NORTHBOUND,
            'south': SignalDirection.SOUTHBOUND,
            'east': SignalDirection.EASTBOUND,
            'west': SignalDirection.WESTBOUND
        }
        
        return direction_map.get(direction.lower())
    
    def clear_detection(self):
        """Clear emergency vehicle detection flag"""
        self.emergency_vehicle_detected = False
        self.detected_vehicle_type = None
        db.session.commit()
    
    # ============================================
    # CONNECTIVITY METHODS
    # ============================================
    
    def update_heartbeat(self):
        """Update last heartbeat timestamp (signal is alive)"""
        self.last_heartbeat = datetime.utcnow()
        self.is_online = True
        db.session.commit()
    
    def mark_offline(self):
        """Mark signal as offline"""
        self.is_online = False
        db.session.commit()
        logger.warning(f"Signal {self.intersection_name} is OFFLINE")
    
    def report_error(self, error_code, error_message):
        """Report an error from the physical signal"""
        self.error_code = error_code
        self.error_message = error_message
        db.session.commit()
        logger.error(f"Signal {self.intersection_name} error: {error_code} - {error_message}")
    
    def _send_signal_command(self, command, params):
        """Send command to physical signal via MQTT (internal method)"""
        # This would be implemented with actual MQTT publishing
        from app.extensions import get_mqtt
        mqtt_client = get_mqtt()
        
        if mqtt_client and self.mqtt_topic:
            import json
            payload = {
                'command': command,
                'params': params,
                'timestamp': datetime.utcnow().isoformat(),
                'signal_id': self.intersection_id
            }
            mqtt_client.publish(self.mqtt_topic, json.dumps(payload))
            logger.debug(f"Command sent to {self.intersection_name}: {command}")
    
    # ============================================
    # CALCULATION METHODS
    # ============================================
    
    def distance_to(self, latitude, longitude):
        """Calculate distance to a point in kilometers"""
        try:
            signal_point = (self.latitude, self.longitude)
            target_point = (latitude, longitude)
            return geodesic(signal_point, target_point).kilometers
        except:
            return None
    
    def get_eta_for_vehicle(self, vehicle_lat, vehicle_lng, vehicle_speed_kmh=40):
        """Calculate ETA for vehicle to reach this signal"""
        distance = self.distance_to(vehicle_lat, vehicle_lng)
        if distance is None or vehicle_speed_kmh <= 0:
            return None
        
        eta_hours = distance / vehicle_speed_kmh
        eta_seconds = eta_hours * 3600
        
        return {
            'distance_km': round(distance, 2),
            'eta_seconds': round(eta_seconds),
            'eta_minutes': round(eta_seconds / 60, 1),
            'estimated_arrival': datetime.utcnow() + timedelta(seconds=eta_seconds)
        }
    
    def is_corridor_active(self):
        """Check if green corridor is currently active on this signal"""
        if self.current_status != SignalStatus.GREEN_CORRIDOR:
            return False
        
        if self.corridor_active_until and self.corridor_active_until < datetime.utcnow():
            # Corridor expired but not deactivated
            self.deactivate_green_corridor()
            return False
        
        return True
    
    # ============================================
    # SERIALIZATION
    # ============================================
    
    def to_dict(self, include_sensitive=False):
        """Convert signal object to dictionary"""
        signal_dict = {
            'id': self.id,
            'signal_uuid': self.signal_uuid,
            'intersection_id': self.intersection_id,
            'intersection_name': self.intersection_name,
            
            'location': {
                'latitude': self.latitude,
                'longitude': self.longitude,
                'address': self.address,
                'city': self.city
            },
            
            'status': {
                'current_status': self.current_status.value if self.current_status else None,
                'current_green_direction': self.current_green_direction.value if self.current_green_direction else None,
                'is_corridor_active': self.is_corridor_active(),
                'active_corridor_id': self.active_corridor_id,
                'corridor_active_until': self.corridor_active_until.isoformat() if self.corridor_active_until else None,
                'emergency_vehicle_detected': self.emergency_vehicle_detected
            },
            
            'timing_config': {
                'default_cycle_time': self.default_cycle_time,
                'green_time_north': self.green_time_north,
                'green_time_south': self.green_time_south,
                'green_time_east': self.green_time_east,
                'green_time_west': self.green_time_west,
                'yellow_time': self.yellow_time,
                'all_red_time': self.all_red_time
            },
            
            'traffic_density': {
                'level': self.current_density.value if self.current_density else None,
                'north': self.density_north,
                'south': self.density_south,
                'east': self.density_east,
                'west': self.density_west,
                'last_update': self.last_density_update.isoformat() if self.last_density_update else None
            },
            
            'connectivity': {
                'is_online': self.is_online,
                'last_heartbeat': self.last_heartbeat.isoformat() if self.last_heartbeat else None,
                'network_latency_ms': self.network_latency_ms,
                'firmware_version': self.firmware_version
            },
            
            'statistics': {
                'total_corridors_served': self.total_corridors_served,
                'total_emergency_vehicles_served': self.total_emergency_vehicles_served,
                'time_saved_minutes': round(self.time_saved_for_emergencies, 2)
            },
            
            'zone_id': self.zone_id,
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
        
        # Add sensitive info if requested
        if include_sensitive:
            signal_dict['sensitive'] = {
                'mqtt_topic': self.mqtt_topic,
                'controller_ip': self.controller_ip,
                'controller_port': self.controller_port,
                'camera_url': self.camera_url,
                'error_code': self.error_code,
                'error_message': self.error_message,
                'maintenance_notes': self.maintenance_notes,
                'metadata': self.metadata
            }
        
        return signal_dict
    
    def __repr__(self):
        return f"<TrafficSignal {self.intersection_id}: {self.intersection_name} - {self.current_status.value if self.current_status else 'Unknown'}>"


# ============================================
# SIGNAL LOGS (For audit and debugging)
# ============================================

class SignalLog(db.Model):
    """
    Log all signal state changes and commands
    For audit trail and debugging
    """
    __tablename__ = 'signal_logs'
    
    id = Column(Integer, primary_key=True)
    signal_id = Column(Integer, ForeignKey('traffic_signals.id', ondelete='CASCADE'), nullable=False)
    action = Column(String(100), nullable=False)  # e.g., 'GREEN_CORRIDOR_ACTIVATE', 'MANUAL_CONTROL', 'RESET'
    command_params = Column(JSON, nullable=True)
    previous_status = Column(String(50), nullable=True)
    new_status = Column(String(50), nullable=True)
    triggered_by = Column(String(100), nullable=True)  # 'system', 'manual', 'vehicle_id'
    success = Column(Boolean, default=True)
    response_time_ms = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    signal = relationship("TrafficSignal", backref="logs")
    
    @classmethod
    def log_action(cls, signal_id, action, triggered_by, success=True, **kwargs):
        """Create a log entry for signal action"""
        log = cls(
            signal_id=signal_id,
            action=action,
            command_params=kwargs.get('command_params'),
            previous_status=kwargs.get('previous_status'),
            new_status=kwargs.get('new_status'),
            triggered_by=triggered_by,
            success=success,
            response_time_ms=kwargs.get('response_time_ms')
        )
        db.session.add(log)
        db.session.commit()
        return log
    
    def to_dict(self):
        return {
            'id': self.id,
            'signal_id': self.signal_id,
            'action': self.action,
            'command_params': self.command_params,
            'previous_status': self.previous_status,
            'new_status': self.new_status,
            'triggered_by': self.triggered_by,
            'success': self.success,
            'response_time_ms': self.response_time_ms,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# ============================================
# HELPER FUNCTIONS
# ============================================

def find_signal_by_id(signal_id):
    """Find signal by ID"""
    return TrafficSignal.query.get(signal_id)

def find_signal_by_intersection_id(intersection_id):
    """Find signal by intersection ID"""
    return TrafficSignal.query.filter_by(intersection_id=intersection_id).first()

def find_signal_by_uuid(signal_uuid):
    """Find signal by UUID"""
    return TrafficSignal.query.filter_by(signal_uuid=signal_uuid).first()

def get_all_signals(zone_id=None, status=None):
    """Get all traffic signals with optional filters"""
    query = TrafficSignal.query.filter_by(is_active=True)
    
    if zone_id:
        query = query.filter_by(zone_id=zone_id)
    
    if status:
        query = query.filter_by(current_status=status)
    
    return query.order_by(TrafficSignal.intersection_name).all()

def get_signals_on_route(route_coordinates):
    """
    Get all signals along a route
    route_coordinates: List of (lat, lng) points
    """
    signals = get_all_signals()
    route_signals = []
    
    for signal in signals:
        # Simple proximity check to route
        # In production, use more sophisticated route matching
        for coord in route_coordinates:
            distance = signal.distance_to(coord[0], coord[1])
            if distance and distance <= 0.1:  # Within 100 meters
                route_signals.append(signal)
                break
    
    return route_signals

def get_next_signal_on_path(current_lat, current_lng, destination_lat, destination_lng):
    """Get the next traffic signal on the path to destination"""
    # This would require route calculation and map matching
    # Simplified version - find nearest signal in direction of travel
    signals = get_all_signals()
    
    # Calculate bearing from current to destination
    # For now, return nearest signal
    nearest = None
    nearest_distance = float('inf')
    
    for signal in signals:
        distance = signal.distance_to(current_lat, current_lng)
        if distance and distance < nearest_distance and distance < 0.5:  # Within 500m
            nearest_distance = distance
            nearest = signal
    
    return nearest

def create_sample_signals():
    """Create sample traffic signals for testing"""
    signals_data = [
        {
            'intersection_id': 'INT_DELHI_001',
            'intersection_name': 'Connaught Place Crossing',
            'latitude': 28.6304,
            'longitude': 77.2177,
            'zone_id': 'ZONE_CENTRAL',
            'address': 'Connaught Place, New Delhi'
        },
        {
            'intersection_id': 'INT_DELHI_002',
            'intersection_name': 'India Gate Circle',
            'latitude': 28.6129,
            'longitude': 77.2295,
            'zone_id': 'ZONE_CENTRAL',
            'address': 'India Gate, New Delhi'
        },
        {
            'intersection_id': 'INT_DELHI_003',
            'intersection_name': 'Rajiv Chowk',
            'latitude': 28.6328,
            'longitude': 77.2198,
            'zone_id': 'ZONE_CENTRAL',
            'address': 'Rajiv Chowk, New Delhi'
        },
        {
            'intersection_id': 'INT_DELHI_004',
            'intersection_name': 'AIIMS Crossing',
            'latitude': 28.5675,
            'longitude': 77.2100,
            'zone_id': 'ZONE_SOUTH',
            'address': 'AIIMS, New Delhi'
        },
        {
            'intersection_id': 'INT_DELHI_005',
            'intersection_name': 'ITO Intersection',
            'latitude': 28.6265,
            'longitude': 77.2355,
            'zone_id': 'ZONE_EAST',
            'address': 'ITO, New Delhi'
        }
    ]
    
    for data in signals_data:
        existing = find_signal_by_intersection_id(data['intersection_id'])
        if not existing:
            signal = TrafficSignal(**data)
            db.session.add(signal)
    
    db.session.commit()
    logger.info(f"✅ Created {len(signals_data)} sample traffic signals")


# ============================================
# EXPORTS
# ============================================

__all__ = [
    'TrafficSignal',
    'SignalStatus',
    'SignalDirection',
    'LaneType',
    'TrafficDensity',
    'SignalLog',
    'find_signal_by_id',
    'find_signal_by_intersection_id',
    'find_signal_by_uuid',
    'get_all_signals',
    'get_signals_on_route',
    'get_next_signal_on_path',
    'create_sample_signals'
]