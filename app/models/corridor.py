"""
Smart Emergency Vehicle Priority System - Green Corridor Model
This file defines the GreenCorridor model for creating and managing
dynamic green corridors for emergency vehicles
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
# ENUMS (Choices for corridor fields)
# ============================================

class CorridorStatus(enum.Enum):
    """Status of the green corridor"""
    REQUESTED = "requested"           # Corridor requested, not yet approved
    APPROVED = "approved"             # Corridor approved, signals not yet activated
    ACTIVE = "active"                 # Corridor active, signals turning green
    IN_PROGRESS = "in_progress"       # Vehicle passing through corridor
    COMPLETED = "completed"           # Vehicle reached destination
    CANCELLED = "cancelled"           # Corridor cancelled
    EXPIRED = "expired"               # Corridor expired due to timeout
    FAILED = "failed"                 # Corridor creation failed

class CorridorType(enum.Enum):
    """Type of green corridor"""
    EMERGENCY = "emergency"           # For emergency vehicles (highest priority)
    VIP = "vip"                       # For VIP movement
    SPECIAL = "special"               # Special events
    TEST = "test"                     # Testing purposes

class PathCalculationMethod(enum.Enum):
    """Method used to calculate the corridor path"""
    AI_OPTIMIZED = "ai_optimized"     # AI-based shortest path
    SHORTEST_DISTANCE = "shortest_distance"  # Simple distance-based
    FASTEST_TIME = "fastest_time"     # Time-based with traffic data
    PREDEFINED = "predefined"         # Predefined route

# ============================================
# GREEN CORRIDOR MODEL
# ============================================

class GreenCorridor(db.Model):
    """
    Green Corridor model for creating dynamic green paths
    Coordinates multiple traffic signals to create an uninterrupted path
    """
    __tablename__ = 'green_corridors'
    __table_args__ = (
        db.Index('idx_corridor_status', 'status'),
        db.Index('idx_corridor_vehicle', 'vehicle_id'),
        db.Index('idx_corridor_incident', 'incident_id'),
        db.Index('idx_corridor_active', 'is_active', 'status'),
        {'schema': 'public'}
    )

    # ============================================
    # BASIC IDENTIFICATION
    # ============================================
    id = Column(Integer, primary_key=True)
    corridor_uuid = Column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    corridor_type = Column(Enum(CorridorType), default=CorridorType.EMERGENCY)
    status = Column(Enum(CorridorStatus), default=CorridorStatus.REQUESTED)
    
    # ============================================
    # VEHICLE & INCIDENT ASSOCIATION
    # ============================================
    vehicle_id = Column(Integer, ForeignKey('emergency_vehicles.id'), nullable=False)
    incident_id = Column(Integer, ForeignKey('incidents.id'), nullable=True)
    requested_by_id = Column(Integer, ForeignKey('users.id'), nullable=False)
    approved_by_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    
    # ============================================
    # ROUTE INFORMATION
    # ============================================
    # Start point (current vehicle location)
    start_latitude = Column(Float, nullable=False)
    start_longitude = Column(Float, nullable=False)
    start_address = Column(String(500), nullable=True)
    
    # Destination (incident location or hospital)
    destination_latitude = Column(Float, nullable=False)
    destination_longitude = Column(Float, nullable=False)
    destination_address = Column(String(500), nullable=True)
    destination_type = Column(String(50), nullable=True)  # 'incident', 'hospital', 'base'
    
    # Path details
    path_points = Column(JSON, default=[])  # List of {lat, lng, order} points
    path_distance_km = Column(Float, nullable=True)
    path_duration_seconds = Column(Integer, nullable=True)
    calculation_method = Column(Enum(PathCalculationMethod), default=PathCalculationMethod.AI_OPTIMIZED)
    
    # ============================================
    # SIGNAL COORDINATION
    # ============================================
    # List of signals on the route
    signal_ids = Column(JSON, default=[])  # List of signal IDs in order
    signal_sequence = Column(JSON, default=[])  # Detailed sequence with timing
    
    # Signal activation details
    signals_activated = Column(Integer, default=0)
    signals_total = Column(Integer, default=0)
    signals_passed = Column(Integer, default=0)
    
    # Green corridor timing per signal
    signal_timings = Column(JSON, default={})  # Signal ID -> activation time, green duration
    
    # ============================================
    # TIMING & COORDINATION
    # ============================================
    requested_at = Column(DateTime, default=datetime.utcnow)
    approved_at = Column(DateTime, nullable=True)
    activated_at = Column(DateTime, nullable=True)
    started_at = Column(DateTime, nullable=True)  # When vehicle started moving
    completed_at = Column(DateTime, nullable=True)
    cancelled_at = Column(DateTime, nullable=True)
    
    # Time metrics
    corridor_active_until = Column(DateTime, nullable=True)  # When corridor expires
    estimated_duration_seconds = Column(Integer, default=300)  # 5 minutes default
    actual_duration_seconds = Column(Integer, nullable=True)
    time_saved_seconds = Column(Integer, nullable=True)
    
    # ============================================
    # PRIORITY & CONFLICT MANAGEMENT
    # ============================================
    priority_level = Column(Integer, default=1)  # 1=Highest (ambulance), 2=Fire, 3=Police
    can_preempt = Column(Boolean, default=True)  # Can preempt other corridors
    preempted_by_id = Column(Integer, nullable=True)  # Corridor that preempted this
    conflicting_corridors = Column(JSON, default=[])  # List of conflicting corridor IDs
    
    # ============================================
    # REAL-TIME TRACKING
    # ============================================
    current_signal_index = Column(Integer, default=0)  # Index of current signal in sequence
    last_signal_passed_at = Column(DateTime, nullable=True)
    next_signal_id = Column(Integer, nullable=True)
    vehicle_last_latitude = Column(Float, nullable=True)
    vehicle_last_longitude = Column(Float, nullable=True)
    last_progress_update = Column(DateTime, nullable=True)
    
    # Progress tracking
    progress_percentage = Column(Float, default=0.0)
    remaining_distance_km = Column(Float, nullable=True)
    remaining_time_seconds = Column(Integer, nullable=True)
    
    # ============================================
    # COMMUNICATION & ALERTS
    # ============================================
    driver_notified = Column(Boolean, default=False)
    control_room_notified = Column(Boolean, default=False)
    public_broadcast_sent = Column(Boolean, default=False)  # Announce to public
    alert_messages = Column(JSON, default=[])
    
    # ============================================
    # STATISTICS & METRICS
    # ============================================
    traffic_impact_score = Column(Float, nullable=True)  # Impact on regular traffic (0-100)
    public_delay_minutes = Column(Integer, nullable=True)  # Estimated public delay
    fuel_saved_liters = Column(Float, nullable=True)  # Emergency vehicle fuel saved
    
    # ============================================
    # METADATA
    # ============================================
    is_active = Column(Boolean, default=True)
    notes = Column(Text, nullable=True)
    metadata = Column(JSON, default={})
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # ============================================
    # RELATIONSHIPS
    # ============================================
    vehicle = relationship("EmergencyVehicle", foreign_keys=[vehicle_id], back_populates="active_corridor")
    incident = relationship("Incident", foreign_keys=[incident_id], back_populates="green_corridor")
    requested_by = relationship("User", foreign_keys=[requested_by_id])
    approved_by = relationship("User", foreign_keys=[approved_by_id])
    
    # ============================================
    # INITIALIZER
    # ============================================
    def __init__(self, vehicle_id, start_lat, start_lng, dest_lat, dest_lng, requested_by_id, **kwargs):
        self.vehicle_id = vehicle_id
        self.start_latitude = start_lat
        self.start_longitude = start_lng
        self.destination_latitude = dest_lat
        self.destination_longitude = dest_lng
        self.requested_by_id = requested_by_id
        self.corridor_uuid = str(uuid.uuid4())
        
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    # ============================================
    # CORRIDOR LIFECYCLE MANAGEMENT
    # ============================================
    
    def approve(self, approved_by_id):
        """Approve the corridor request"""
        if self.status != CorridorStatus.REQUESTED:
            logger.warning(f"Cannot approve corridor {self.id}: Invalid status {self.status}")
            return False
        
        self.status = CorridorStatus.APPROVED
        self.approved_by_id = approved_by_id
        self.approved_at = datetime.utcnow()
        
        # Calculate route and signals
        self._calculate_route()
        self._get_signals_on_route()
        
        db.session.commit()
        
        logger.info(f"✅ Corridor {self.id} approved by user {approved_by_id}")
        self._add_alert(f"Corridor approved. Route distance: {self.path_distance_km:.2f} km")
        
        return True
    
    def activate(self):
        """Activate the green corridor (start turning signals green)"""
        if self.status not in [CorridorStatus.APPROVED, CorridorStatus.REQUESTED]:
            logger.warning(f"Cannot activate corridor {self.id}: Invalid status {self.status}")
            return False
        
        self.status = CorridorStatus.ACTIVE
        self.activated_at = datetime.utcnow()
        self.corridor_active_until = datetime.utcnow() + timedelta(seconds=self.estimated_duration_seconds)
        
        # Activate all signals on the route
        self._activate_signals()
        
        db.session.commit()
        
        logger.info(f"🚦 Corridor {self.id} ACTIVATED - {self.signals_total} signals will turn green")
        self._add_alert(f"Green corridor activated! {self.signals_total} signals on route.")
        
        return True
    
    def start_journey(self):
        """Mark that vehicle has started the journey"""
        if self.status != CorridorStatus.ACTIVE:
            self.activate()
        
        self.status = CorridorStatus.IN_PROGRESS
        self.started_at = datetime.utcnow()
        db.session.commit()
        
        logger.info(f"🚑 Vehicle started journey on corridor {self.id}")
        self._add_alert("Emergency vehicle has started its journey")
        
        return True
    
    def update_progress(self, current_lat, current_lng):
        """Update vehicle progress along the corridor"""
        self.vehicle_last_latitude = current_lat
        self.vehicle_last_longitude = current_lng
        self.last_progress_update = datetime.utcnow()
        
        # Calculate remaining distance
        remaining = geodesic(
            (current_lat, current_lng),
            (self.destination_latitude, self.destination_longitude)
        ).kilometers
        
        self.remaining_distance_km = round(remaining, 2)
        self.progress_percentage = round(
            ((self.path_distance_km - remaining) / self.path_distance_km) * 100, 2
        ) if self.path_distance_km else 0
        
        # Calculate remaining time (assuming avg speed 40 km/h)
        avg_speed = 40  # km/h
        self.remaining_time_seconds = int((remaining / avg_speed) * 3600) if remaining else 0
        
        # Check if next signal needs activation
        self._check_next_signal(current_lat, current_lng)
        
        db.session.commit()
        
        # Check if destination reached
        if remaining < 0.1:  # Within 100 meters
            self.complete()
        
        return {
            'progress_percentage': self.progress_percentage,
            'remaining_distance_km': self.remaining_distance_km,
            'remaining_time_seconds': self.remaining_time_seconds
        }
    
    def mark_signal_passed(self, signal_id):
        """Mark that vehicle has passed a signal"""
        if signal_id not in self.signal_ids:
            return False
        
        self.signals_passed += 1
        self.last_signal_passed_at = datetime.utcnow()
        
        # Update current signal index
        try:
            index = self.signal_ids.index(signal_id)
            self.current_signal_index = index + 1
            
            if self.current_signal_index < len(self.signal_ids):
                self.next_signal_id = self.signal_ids[self.current_signal_index]
        except ValueError:
            pass
        
        # Deactivate this signal's corridor
        self._deactivate_signal(signal_id)
        
        db.session.commit()
        
        logger.info(f"📍 Vehicle passed signal {signal_id} - {self.signals_passed}/{self.signals_total}")
        self._add_alert(f"Passed signal {self.signals_passed} of {self.signals_total}")
        
        return True
    
    def complete(self):
        """Complete the corridor journey"""
        self.status = CorridorStatus.COMPLETED
        self.completed_at = datetime.utcnow()
        
        # Calculate actual duration
        if self.started_at:
            self.actual_duration_seconds = int(
                (self.completed_at - self.started_at).total_seconds()
            )
        
        # Calculate time saved
        if self.path_duration_seconds and self.actual_duration_seconds:
            self.time_saved_seconds = self.path_duration_seconds - self.actual_duration_seconds
        
        # Deactivate all remaining signals
        self._deactivate_all_signals()
        
        db.session.commit()
        
        # Update vehicle stats
        from app.models.vehicle import find_vehicle_by_id
        vehicle = find_vehicle_by_id(self.vehicle_id)
        if vehicle:
            vehicle.total_emergencies_handled += 1
            vehicle.deactivate_corridor()
        
        logger.info(f"🏁 Corridor {self.id} COMPLETED - Time saved: {self.time_saved_seconds}s")
        self._add_alert(f"Journey completed! Time saved: {self.time_saved_seconds} seconds")
        
        return True
    
    def cancel(self, reason=None, cancelled_by_id=None):
        """Cancel the corridor"""
        self.status = CorridorStatus.CANCELLED
        self.cancelled_at = datetime.utcnow()
        
        if reason:
            self.notes = f"{self.notes}\nCancelled: {reason}" if self.notes else f"Cancelled: {reason}"
        
        # Deactivate all activated signals
        self._deactivate_all_signals()
        
        db.session.commit()
        
        logger.info(f"❌ Corridor {self.id} CANCELLED: {reason or 'No reason'}")
        self._add_alert(f"Corridor cancelled: {reason or 'No reason'}")
        
        return True
    
    def expire(self):
        """Expire the corridor (timeout)"""
        if self.status == CorridorStatus.ACTIVE:
            self.status = CorridorStatus.EXPIRED
            self._deactivate_all_signals()
            db.session.commit()
            
            logger.warning(f"⏰ Corridor {self.id} EXPIRED due to timeout")
            self._add_alert("Corridor expired due to timeout")
            
            return True
        
        return False
    
    # ============================================
    # ROUTE CALCULATION METHODS
    # ============================================
    
    def _calculate_route(self):
        """Calculate optimal route from start to destination"""
        # Simplified route calculation
        # In production, use Google Maps API or OSRM
        
        # Calculate straight-line distance
        distance = geodesic(
            (self.start_latitude, self.start_longitude),
            (self.destination_latitude, self.destination_longitude)
        ).kilometers
        
        self.path_distance_km = round(distance, 2)
        
        # Estimate duration (assume avg speed 40 km/h in city)
        avg_speed = 40  # km/h
        self.path_duration_seconds = int((distance / avg_speed) * 3600)
        self.estimated_duration_seconds = self.path_duration_seconds
        
        # Generate intermediate points (simplified - just start and end)
        self.path_points = [
            {'lat': self.start_latitude, 'lng': self.start_longitude, 'order': 0},
            {'lat': self.destination_latitude, 'lng': self.destination_longitude, 'order': 1}
        ]
        
        logger.info(f"Route calculated: {self.path_distance_km} km, ~{self.path_duration_seconds}s")
    
    def _get_signals_on_route(self):
        """Get all traffic signals along the calculated route"""
        from app.models.traffic_signal import get_all_signals, get_signals_on_route
        
        # Get signals near the route
        route_coords = [(self.start_latitude, self.start_longitude),
                       (self.destination_latitude, self.destination_longitude)]
        
        signals = get_signals_on_route(route_coords)
        
        self.signal_ids = [s.id for s in signals]
        self.signals_total = len(signals)
        
        logger.info(f"Found {self.signals_total} signals on corridor {self.id}")
    
    # ============================================
    # SIGNAL ACTIVATION METHODS
    # ============================================
    
    def _activate_signals(self):
        """Activate all signals on the corridor"""
        from app.models.traffic_signal import find_signal_by_id
        
        for idx, signal_id in enumerate(self.signal_ids):
            signal = find_signal_by_id(signal_id)
            if signal:
                # Calculate activation time based on distance from start
                activation_offset = idx * 30  # 30 seconds between signals
                
                signal.set_green_corridor(
                    corridor_id=self.id,
                    vehicle_id=self.vehicle_id,
                    duration_seconds=60  # 1 minute green
                )
                
                # Store timing in signal_timings
                self.signal_timings[str(signal_id)] = {
                    'activation_offset': activation_offset,
                    'green_duration': 60,
                    'activated': False,
                    'order': idx
                }
                
                self.signals_activated += 1
        
        db.session.commit()
        logger.info(f"Activated {self.signals_activated} signals for corridor {self.id}")
    
    def _check_next_signal(self, current_lat, current_lng):
        """Check if vehicle is approaching next signal and activate it"""
        if self.current_signal_index >= len(self.signal_ids):
            return
        
        next_signal_id = self.signal_ids[self.current_signal_index]
        from app.models.traffic_signal import find_signal_by_id
        
        signal = find_signal_by_id(next_signal_id)
        if signal:
            distance = signal.distance_to(current_lat, current_lng)
            
            # If within 500 meters, ensure signal is in green corridor mode
            if distance and distance <= 0.5:
                if signal.current_status.value != 'green_corridor':
                    signal.set_green_corridor(self.id, self.vehicle_id, 60)
                    logger.info(f"🚦 Activating signal {signal.intersection_name} - {distance:.2f}km away")
    
    def _deactivate_signal(self, signal_id):
        """Deactivate a specific signal"""
        from app.models.traffic_signal import find_signal_by_id
        
        signal = find_signal_by_id(signal_id)
        if signal:
            signal.deactivate_green_corridor()
            logger.debug(f"Deactivated signal {signal_id}")
    
    def _deactivate_all_signals(self):
        """Deactivate all signals on the corridor"""
        from app.models.traffic_signal import find_signal_by_id
        
        for signal_id in self.signal_ids:
            signal = find_signal_by_id(signal_id)
            if signal and signal.current_status.value == 'green_corridor':
                signal.deactivate_green_corridor()
        
        logger.info(f"Deactivated all {self.signals_total} signals for corridor {self.id}")
    
    # ============================================
    # HELPER METHODS
    # ============================================
    
    def _add_alert(self, message, alert_type='system'):
        """Add an alert message to the corridor timeline"""
        self.alert_messages = (self.alert_messages or []) + [{
            'timestamp': datetime.utcnow().isoformat(),
            'message': message,
            'type': alert_type
        }]
        db.session.commit()
    
    def is_active_corridor(self):
        """Check if corridor is currently active"""
        if self.status not in [CorridorStatus.ACTIVE, CorridorStatus.IN_PROGRESS]:
            return False
        
        if self.corridor_active_until and self.corridor_active_until < datetime.utcnow():
            self.expire()
            return False
        
        return True
    
    def get_eta(self):
        """Get ETA for emergency vehicle"""
        if self.remaining_time_seconds:
            eta = datetime.utcnow() + timedelta(seconds=self.remaining_time_seconds)
            return {
                'minutes': round(self.remaining_time_seconds / 60, 1),
                'seconds': self.remaining_time_seconds,
                'datetime': eta.isoformat()
            }
        return None
    
    def get_summary(self):
        """Get corridor summary statistics"""
        return {
            'id': self.id,
            'uuid': self.corridor_uuid,
            'status': self.status.value if self.status else None,
            'distance_km': self.path_distance_km,
            'estimated_duration_seconds': self.estimated_duration_seconds,
            'actual_duration_seconds': self.actual_duration_seconds,
            'time_saved_seconds': self.time_saved_seconds,
            'signals_total': self.signals_total,
            'signals_passed': self.signals_passed,
            'progress_percentage': self.progress_percentage,
            'remaining_distance_km': self.remaining_distance_km,
            'eta': self.get_eta()
        }
    
    # ============================================
    # SERIALIZATION
    # ============================================
    
    def to_dict(self, include_sensitive=False):
        """Convert corridor object to dictionary"""
        corridor_dict = {
            'id': self.id,
            'corridor_uuid': self.corridor_uuid,
            'corridor_type': self.corridor_type.value if self.corridor_type else None,
            'status': self.status.value if self.status else None,
            
            'vehicle_id': self.vehicle_id,
            'incident_id': self.incident_id,
            
            'start_location': {
                'latitude': self.start_latitude,
                'longitude': self.start_longitude,
                'address': self.start_address
            },
            
            'destination': {
                'latitude': self.destination_latitude,
                'longitude': self.destination_longitude,
                'address': self.destination_address,
                'type': self.destination_type
            },
            
            'route': {
                'distance_km': self.path_distance_km,
                'duration_seconds': self.path_duration_seconds,
                'signal_count': self.signals_total,
                'calculation_method': self.calculation_method.value if self.calculation_method else None,
                'path_points': self.path_points
            },
            
            'progress': {
                'signals_activated': self.signals_activated,
                'signals_passed': self.signals_passed,
                'current_signal_index': self.current_signal_index,
                'progress_percentage': self.progress_percentage,
                'remaining_distance_km': self.remaining_distance_km,
                'remaining_time_seconds': self.remaining_time_seconds
            },
            
            'timeline': {
                'requested_at': self.requested_at.isoformat() if self.requested_at else None,
                'approved_at': self.approved_at.isoformat() if self.approved_at else None,
                'activated_at': self.activated_at.isoformat() if self.activated_at else None,
                'started_at': self.started_at.isoformat() if self.started_at else None,
                'completed_at': self.completed_at.isoformat() if self.completed_at else None,
                'corridor_active_until': self.corridor_active_until.isoformat() if self.corridor_active_until else None
            },
            
            'metrics': {
                'estimated_duration_seconds': self.estimated_duration_seconds,
                'actual_duration_seconds': self.actual_duration_seconds,
                'time_saved_seconds': self.time_saved_seconds,
                'traffic_impact_score': self.traffic_impact_score,
                'public_delay_minutes': self.public_delay_minutes
            },
            
            'eta': self.get_eta(),
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
        
        # Add sensitive info if requested
        if include_sensitive:
            corridor_dict['sensitive'] = {
                'signal_ids': self.signal_ids,
                'signal_sequence': self.signal_sequence,
                'signal_timings': self.signal_timings,
                'alert_messages': self.alert_messages,
                'notes': self.notes,
                'metadata': self.metadata
            }
        
        return corridor_dict
    
    def __repr__(self):
        return f"<GreenCorridor {self.id}: Vehicle {self.vehicle_id} - {self.status.value if self.status else 'Unknown'}>"


# ============================================
# HELPER FUNCTIONS
# ============================================

def find_corridor_by_id(corridor_id):
    """Find corridor by ID"""
    return GreenCorridor.query.get(corridor_id)

def find_corridor_by_uuid(corridor_uuid):
    """Find corridor by UUID"""
    return GreenCorridor.query.filter_by(corridor_uuid=corridor_uuid).first()

def find_corridor_by_vehicle(vehicle_id):
    """Find active corridor for a vehicle"""
    return GreenCorridor.query.filter_by(
        vehicle_id=vehicle_id,
        is_active=True
    ).filter(
        GreenCorridor.status.in_([
            CorridorStatus.APPROVED,
            CorridorStatus.ACTIVE,
            CorridorStatus.IN_PROGRESS
        ])
    ).first()

def find_corridor_by_incident(incident_id):
    """Find corridor for an incident"""
    return GreenCorridor.query.filter_by(
        incident_id=incident_id,
        is_active=True
    ).first()

def get_active_corridors():
    """Get all currently active corridors"""
    return GreenCorridor.query.filter(
        GreenCorridor.status.in_([
            CorridorStatus.ACTIVE,
            CorridorStatus.IN_PROGRESS
        ]),
        GreenCorridor.is_active == True
    ).all()

def get_corridor_history(vehicle_id=None, days=7):
    """Get corridor history for last N days"""
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    query = GreenCorridor.query.filter(
        GreenCorridor.created_at >= cutoff_date,
        GreenCorridor.status.in_([
            CorridorStatus.COMPLETED,
            CorridorStatus.CANCELLED,
            CorridorStatus.EXPIRED
        ])
    )
    
    if vehicle_id:
        query = query.filter_by(vehicle_id=vehicle_id)
    
    return query.order_by(GreenCorridor.created_at.desc()).all()

def get_corridor_statistics(days=30):
    """Get corridor statistics"""
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    corridors = GreenCorridor.query.filter(
        GreenCorridor.created_at >= cutoff_date
    ).all()
    
    completed = [c for c in corridors if c.status == CorridorStatus.COMPLETED]
    active = [c for c in corridors if c.status in [CorridorStatus.ACTIVE, CorridorStatus.IN_PROGRESS]]
    
    stats = {
        'total_corridors': len(corridors),
        'completed_corridors': len(completed),
        'active_corridors': len(active),
        'cancelled_corridors': len([c for c in corridors if c.status == CorridorStatus.CANCELLED]),
        'expired_corridors': len([c for c in corridors if c.status == CorridorStatus.EXPIRED]),
        
        'total_time_saved_seconds': sum(c.time_saved_seconds or 0 for c in completed),
        'total_distance_km': sum(c.path_distance_km or 0 for c in completed),
        'total_signals_used': sum(c.signals_total or 0 for c in completed),
        
        'average_time_saved_seconds': 0,
        'average_distance_km': 0,
        'success_rate': 0
    }
    
    if completed:
        stats['average_time_saved_seconds'] = stats['total_time_saved_seconds'] // len(completed)
        stats['average_distance_km'] = round(stats['total_distance_km'] / len(completed), 2)
    
    if corridors:
        stats['success_rate'] = round((len(completed) / len(corridors)) * 100, 2)
    
    return stats

def create_sample_corridor():
    """Create a sample corridor for testing"""
    from app.models.vehicle import find_vehicle_by_registration
    from app.models.user import find_user_by_email
    
    vehicle = find_vehicle_by_registration('DL-01-AB-1234')
    user = find_user_by_email('admin@sevps.com')
    
    if vehicle and user:
        existing = find_corridor_by_vehicle(vehicle.id)
        if not existing:
            corridor = GreenCorridor(
                vehicle_id=vehicle.id,
                start_lat=28.6139,
                start_lng=77.2090,
                dest_lat=28.5675,
                dest_lng=77.2100,
                requested_by_id=user.id,
                destination_type='hospital',
                destination_address='AIIMS Hospital, Delhi',
                priority_level=1
            )
            db.session.add(corridor)
            db.session.commit()
            
            # Approve and activate
            corridor.approve(user.id)
            corridor.activate()
            
            logger.info(f"Sample corridor created: {corridor.id}")
            return corridor
    
    return None


# ============================================
# EXPORTS
# ============================================

__all__ = [
    'GreenCorridor',
    'CorridorStatus',
    'CorridorType',
    'PathCalculationMethod',
    'find_corridor_by_id',
    'find_corridor_by_uuid',
    'find_corridor_by_vehicle',
    'find_corridor_by_incident',
    'get_active_corridors',
    'get_corridor_history',
    'get_corridor_statistics',
    'create_sample_corridor'
]