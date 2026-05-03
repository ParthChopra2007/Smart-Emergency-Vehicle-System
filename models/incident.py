"""
Smart Emergency Vehicle Priority System - Incident Model
This file defines the Incident model for tracking all emergency incidents
including accidents, fires, medical emergencies, and crime scenes
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
# ENUMS (Choices for incident fields)
# ============================================

class IncidentType(enum.Enum):
    """Types of emergency incidents"""
    MEDICAL_EMERGENCY = "medical_emergency"           # Heart attack, stroke, etc.
    ACCIDENT = "accident"                             # Road traffic accident
    FIRE = "fire"                                     # Building/forest fire
    CRIME = "crime"                                   # Robbery, assault, etc.
    NATURAL_DISASTER = "natural_disaster"             # Earthquake, flood, etc.
    HAZMAT = "hazmat"                                 # Hazardous material spill
    RESCUE_OPERATION = "rescue_operation"             # Rescue from height/water
    BOMB_THREAT = "bomb_threat"                       # Bomb/explosive threat
    PUBLIC_DISTURBANCE = "public_disturbance"         # Riot, protest, etc.
    OTHER = "other"

class IncidentSeverity(enum.Enum):
    """Severity level of the incident"""
    CRITICAL = 1      # Life-threatening, immediate response needed
    HIGH = 2          # Serious, rapid response needed
    MEDIUM = 3        # Moderate, standard response
    LOW = 4           # Minor, routine response

class IncidentStatus(enum.Enum):
    """Current status of the incident"""
    REPORTED = "reported"           # Just reported, no response yet
    ASSIGNED = "assigned"           # Vehicle assigned
    EN_ROUTE = "en_route"           # Vehicle en route
    ARRIVED = "arrived"             # Vehicle arrived at scene
    IN_PROGRESS = "in_progress"     # Active response ongoing
    STABILIZED = "stabilized"       # Situation under control
    RESOLVED = "resolved"           # Incident closed
    CANCELLED = "cancelled"         # False alarm/cancelled

class PatientCondition(enum.Enum):
    """Patient condition for medical emergencies"""
    CRITICAL = "critical"
    SERIOUS = "serious"
    STABLE = "stable"
    DECEASED = "deceased"
    UNKNOWN = "unknown"

# ============================================
# INCIDENT MODEL
# ============================================

class Incident(db.Model):
    """
    Incident model for tracking all emergency incidents
    Tracks from reporting to resolution
    """
    __tablename__ = 'incidents'
    __table_args__ = (
        db.Index('idx_incident_location', 'latitude', 'longitude'),
        db.Index('idx_incident_status_time', 'status', 'reported_at'),
        db.Index('idx_incident_type_severity', 'incident_type', 'severity'),
        {'schema': 'public'}
    )

    # ============================================
    # BASIC IDENTIFICATION
    # ============================================
    id = Column(Integer, primary_key=True)
    incident_uuid = Column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    incident_type = Column(Enum(IncidentType), nullable=False)
    severity = Column(Enum(IncidentSeverity), nullable=False)
    status = Column(Enum(IncidentStatus), default=IncidentStatus.REPORTED, nullable=False)
    
    # ============================================
    # LOCATION INFORMATION
    # ============================================
    latitude = Column(Float, nullable=False)
    longitude = Column(Float, nullable=False)
    address = Column(String(500), nullable=True)
    landmark = Column(String(255), nullable=True)
    city = Column(String(100), nullable=True)
    state = Column(String(100), nullable=True)
    pincode = Column(String(10), nullable=True)
    
    # ============================================
    # INCIDENT DETAILS
    # ============================================
    title = Column(String(255), nullable=False)
    description = Column(Text, nullable=True)
    reported_by = Column(String(255), nullable=True)  # Name of reporter
    reporter_phone = Column(String(20), nullable=True)
    reporter_email = Column(String(255), nullable=True)
    
    # Caller information
    caller_name = Column(String(255), nullable=True)
    caller_phone = Column(String(20), nullable=True)
    call_recording_url = Column(String(500), nullable=True)  # Link to call recording
    
    # ============================================
    # VICTIM/PATIENT INFORMATION (for medical emergencies)
    # ============================================
    patient_count = Column(Integer, default=1)
    patient_condition = Column(Enum(PatientCondition), nullable=True)
    patient_ages = Column(JSON, default=[])  # List of ages
    patient_conditions_raw = Column(JSON, default=[])  # List of conditions
    casualties = Column(Integer, default=0)
    fatalities = Column(Integer, default=0)
    
    # ============================================
    # RESOURCES
    # ============================================
    responding_vehicle_id = Column(Integer, ForeignKey('emergency_vehicles.id'), nullable=True)
    assigned_vehicles = Column(JSON, default=[])  # List of vehicle IDs for multiple response
    required_vehicles = Column(JSON, default={})  # Types and counts needed
    
    # Personnel on scene
    personnel_on_scene = Column(Integer, default=0)
    personnel_needed = Column(Integer, default=0)
    
    # ============================================
    # TIMELINE
    # ============================================
    reported_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    assigned_at = Column(DateTime, nullable=True)
    en_route_at = Column(DateTime, nullable=True)
    arrived_at = Column(DateTime, nullable=True)
    stabilized_at = Column(DateTime, nullable=True)
    resolved_at = Column(DateTime, nullable=True)
    
    # Response time metrics (seconds)
    dispatch_time = Column(Float, nullable=True)      # Report to assignment
    response_time = Column(Float, nullable=True)      # Assignment to arrival
    resolution_time = Column(Float, nullable=True)    # Arrival to resolution
    total_time = Column(Float, nullable=True)         # Report to resolution
    
    # ============================================
    # GREEN CORRIDOR INFORMATION
    # ============================================
    green_corridor_id = Column(Integer, ForeignKey('green_corridors.id'), nullable=True)
    corridor_requested = Column(Boolean, default=False)
    corridor_approved = Column(Boolean, default=False)
    corridor_path = Column(JSON, nullable=True)  # List of intersection IDs
    
    # ============================================
    # ADDITIONAL DATA
    # ============================================
    media_urls = Column(JSON, default=[])  # Photos/videos from scene
    police_case_number = Column(String(100), nullable=True)
    hospital_destination = Column(String(255), nullable=True)
    hospital_latitude = Column(Float, nullable=True)
    hospital_longitude = Column(Float, nullable=True)
    
    # Weather at incident time
    weather_conditions = Column(JSON, nullable=True)  # Temperature, rain, visibility
    
    # Notes and updates
    notes = Column(Text, nullable=True)
    updates = Column(JSON, default=[])  # List of update objects
    
    # Metadata
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(Integer, ForeignKey('users.id'), nullable=True)  # Control room operator
    metadata = Column(JSON, default={})
    
    # ============================================
    # RELATIONSHIPS
    # ============================================
    responding_vehicle = relationship("EmergencyVehicle", foreign_keys=[responding_vehicle_id], back_populates="current_incident")
    green_corridor = relationship("GreenCorridor", foreign_keys=[green_corridor_id])
    created_by_user = relationship("User", foreign_keys=[created_by])
    
    # ============================================
    # INITIALIZER
    # ============================================
    def __init__(self, incident_type, severity, latitude, longitude, title, **kwargs):
        self.incident_type = incident_type
        self.severity = severity
        self.latitude = latitude
        self.longitude = longitude
        self.title = title
        self.incident_uuid = str(uuid.uuid4())
        
        for key, value in kwargs.items():
            setattr(self, key, value)
    
    # ============================================
    # STATUS MANAGEMENT METHODS
    # ============================================
    
    def assign_vehicle(self, vehicle_id):
        """Assign a vehicle to this incident"""
        self.responding_vehicle_id = vehicle_id
        self.status = IncidentStatus.ASSIGNED
        self.assigned_at = datetime.utcnow()
        self.dispatch_time = (self.assigned_at - self.reported_at).total_seconds()
        db.session.commit()
        
        # Add to assigned vehicles list
        if vehicle_id not in self.assigned_vehicles:
            assigned = self.assigned_vehicles or []
            assigned.append(vehicle_id)
            self.assigned_vehicles = assigned
        
        logger.info(f"Vehicle {vehicle_id} assigned to incident {self.id}")
        self._add_update(f"Vehicle assigned: {vehicle_id}")
        return True
    
    def mark_en_route(self):
        """Mark that vehicle is en route to incident"""
        self.status = IncidentStatus.EN_ROUTE
        self.en_route_at = datetime.utcnow()
        db.session.commit()
        
        logger.info(f"Vehicle en route to incident {self.id}")
        self._add_update("Vehicle is en route to location")
        return True
    
    def mark_arrived(self):
        """Mark that vehicle has arrived at incident"""
        self.status = IncidentStatus.ARRIVED
        self.arrived_at = datetime.utcnow()
        
        if self.en_route_at:
            self.response_time = (self.arrived_at - self.en_route_at).total_seconds()
        
        db.session.commit()
        
        logger.info(f"Vehicle arrived at incident {self.id} after {self.response_time}s")
        self._add_update(f"Arrived at scene. Response time: {self.response_time:.1f} seconds")
        return True
    
    def mark_in_progress(self):
        """Mark that response is in progress"""
        self.status = IncidentStatus.IN_PROGRESS
        db.session.commit()
        
        logger.info(f"Response in progress for incident {self.id}")
        self._add_update("Emergency response in progress")
        return True
    
    def mark_stabilized(self):
        """Mark that incident is stabilized"""
        self.status = IncidentStatus.STABILIZED
        self.stabilized_at = datetime.utcnow()
        db.session.commit()
        
        logger.info(f"Incident {self.id} stabilized")
        self._add_update("Situation stabilized")
        return True
    
    def mark_resolved(self):
        """Mark incident as resolved/closed"""
        self.status = IncidentStatus.RESOLVED
        self.resolved_at = datetime.utcnow()
        
        # Calculate total time
        self.total_time = (self.resolved_at - self.reported_at).total_seconds()
        
        # Calculate resolution time
        if self.arrived_at:
            self.resolution_time = (self.resolved_at - self.arrived_at).total_seconds()
        
        db.session.commit()
        
        logger.info(f"Incident {self.id} resolved. Total time: {self.total_time:.1f}s")
        self._add_update(f"Incident resolved. Total response time: {self.total_time:.1f} seconds")
        return True
    
    def cancel(self, reason=None):
        """Cancel the incident"""
        self.status = IncidentStatus.CANCELLED
        self.resolved_at = datetime.utcnow()
        
        if reason:
            self.notes = f"{self.notes}\nCancelled: {reason}" if self.notes else f"Cancelled: {reason}"
        
        db.session.commit()
        
        logger.info(f"Incident {self.id} cancelled: {reason}")
        self._add_update(f"Incident cancelled: {reason or 'No reason provided'}")
        return True
    
    # ============================================
    # HELPER METHODS
    # ============================================
    
    def _add_update(self, message, updated_by=None):
        """Add a status update to the incident timeline"""
        updates = self.updates or []
        updates.append({
            'timestamp': datetime.utcnow().isoformat(),
            'message': message,
            'updated_by': updated_by or 'System'
        })
        self.updates = updates
        db.session.commit()
    
    def get_location(self):
        """Get incident location as dictionary"""
        return {
            'latitude': self.latitude,
            'longitude': self.longitude,
            'address': self.address,
            'landmark': self.landmark,
            'city': self.city
        }
    
    def distance_to(self, latitude, longitude):
        """Calculate distance to a point in kilometers"""
        try:
            incident_point = (self.latitude, self.longitude)
            target_point = (latitude, longitude)
            return geodesic(incident_point, target_point).kilometers
        except:
            return None
    
    def get_response_summary(self):
        """Get response time summary"""
        return {
            'dispatch_time_seconds': round(self.dispatch_time, 2) if self.dispatch_time else None,
            'response_time_seconds': round(self.response_time, 2) if self.response_time else None,
            'resolution_time_seconds': round(self.resolution_time, 2) if self.resolution_time else None,
            'total_time_seconds': round(self.total_time, 2) if self.total_time else None,
            'dispatch_time_minutes': round(self.dispatch_time / 60, 2) if self.dispatch_time else None,
            'response_time_minutes': round(self.response_time / 60, 2) if self.response_time else None,
            'total_time_minutes': round(self.total_time / 60, 2) if self.total_time else None
        }
    
    def request_green_corridor(self, corridor_id):
        """Request green corridor for this incident"""
        self.green_corridor_id = corridor_id
        self.corridor_requested = True
        db.session.commit()
        logger.info(f"Green corridor {corridor_id} requested for incident {self.id}")
    
    def approve_green_corridor(self):
        """Approve green corridor for this incident"""
        self.corridor_approved = True
        db.session.commit()
        logger.info(f"Green corridor approved for incident {self.id}")
    
    def update_patient_info(self, patient_count, conditions=None, fatalities=0):
        """Update patient information"""
        self.patient_count = patient_count
        self.fatalities = fatalities
        
        if conditions:
            self.patient_conditions_raw = conditions
        
        db.session.commit()
        logger.info(f"Patient info updated for incident {self.id}: {patient_count} patients, {fatalities} fatalities")
    
    def set_destination_hospital(self, hospital_name, latitude, longitude):
        """Set destination hospital for medical incidents"""
        self.hospital_destination = hospital_name
        self.hospital_latitude = latitude
        self.hospital_longitude = longitude
        db.session.commit()
        logger.info(f"Hospital destination set for incident {self.id}: {hospital_name}")
    
    # ============================================
    # SERIALIZATION
    # ============================================
    
    def to_dict(self, include_sensitive=False):
        """Convert incident object to dictionary"""
        incident_dict = {
            'id': self.id,
            'incident_uuid': self.incident_uuid,
            'incident_type': self.incident_type.value if self.incident_type else None,
            'severity': self.severity.value if self.severity else None,
            'severity_level': self.severity.value if self.severity else None,
            'status': self.status.value if self.status else None,
            
            'location': self.get_location(),
            'title': self.title,
            'description': self.description,
            
            'reported_by': self.reported_by,
            'reporter_phone': self.reporter_phone,
            
            'patient_count': self.patient_count,
            'fatalities': self.fatalities,
            'casualties': self.casualties,
            
            'responding_vehicle_id': self.responding_vehicle_id,
            'assigned_vehicles': self.assigned_vehicles,
            
            'timeline': {
                'reported_at': self.reported_at.isoformat() if self.reported_at else None,
                'assigned_at': self.assigned_at.isoformat() if self.assigned_at else None,
                'en_route_at': self.en_route_at.isoformat() if self.en_route_at else None,
                'arrived_at': self.arrived_at.isoformat() if self.arrived_at else None,
                'stabilized_at': self.stabilized_at.isoformat() if self.stabilized_at else None,
                'resolved_at': self.resolved_at.isoformat() if self.resolved_at else None,
            },
            
            'response_times': self.get_response_summary(),
            
            'green_corridor': {
                'requested': self.corridor_requested,
                'approved': self.corridor_approved,
                'corridor_id': self.green_corridor_id,
                'path': self.corridor_path
            },
            
            'hospital_destination': self.hospital_destination,
            
            'notes': self.notes,
            'updates': self.updates,
            
            'created_at': self.created_at.isoformat() if self.created_at else None,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }
        
        # Add sensitive info if requested
        if include_sensitive:
            incident_dict['caller_name'] = self.caller_name
            incident_dict['caller_phone'] = self.caller_phone
            incident_dict['call_recording_url'] = self.call_recording_url
            incident_dict['media_urls'] = self.media_urls
            incident_dict['police_case_number'] = self.police_case_number
            incident_dict['weather_conditions'] = self.weather_conditions
            incident_dict['metadata'] = self.metadata
        
        return incident_dict
    
    def __repr__(self):
        return f"<Incident {self.id}: {self.incident_type.value if self.incident_type else 'Unknown'} - {self.status.value if self.status else 'Unknown'}>"


# ============================================
# INCIDENT ALERTS (For notifications)
# ============================================

class IncidentAlert(db.Model):
    """
    Store alerts sent for incidents (SMS, Email, Push notifications)
    """
    __tablename__ = 'incident_alerts'
    
    id = Column(Integer, primary_key=True)
    incident_id = Column(Integer, ForeignKey('incidents.id', ondelete='CASCADE'), nullable=False)
    alert_type = Column(String(50), nullable=False)  # sms, email, push, broadcast
    recipient = Column(String(255), nullable=False)
    message = Column(Text, nullable=False)
    status = Column(String(50), default='pending')  # pending, sent, failed
    sent_at = Column(DateTime, nullable=True)
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    incident = relationship("Incident", backref="alerts")
    
    def mark_sent(self):
        """Mark alert as sent"""
        self.status = 'sent'
        self.sent_at = datetime.utcnow()
        db.session.commit()
    
    def mark_failed(self, error):
        """Mark alert as failed"""
        self.status = 'failed'
        self.error_message = error
        db.session.commit()
    
    def to_dict(self):
        return {
            'id': self.id,
            'incident_id': self.incident_id,
            'alert_type': self.alert_type,
            'recipient': self.recipient,
            'message': self.message,
            'status': self.status,
            'sent_at': self.sent_at.isoformat() if self.sent_at else None,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# ============================================
# HELPER FUNCTIONS
# ============================================

def find_incident_by_id(incident_id):
    """Find incident by ID"""
    return Incident.query.get(incident_id)

def find_incident_by_uuid(incident_uuid):
    """Find incident by UUID"""
    return Incident.query.filter_by(incident_uuid=incident_uuid).first()

def get_active_incidents():
    """Get all active (not resolved/cancelled) incidents"""
    return Incident.query.filter(
        Incident.status.in_([
            IncidentStatus.REPORTED,
            IncidentStatus.ASSIGNED,
            IncidentStatus.EN_ROUTE,
            IncidentStatus.ARRIVED,
            IncidentStatus.IN_PROGRESS,
            IncidentStatus.STABILIZED
        ])
    ).order_by(Incident.severity, Incident.reported_at).all()

def get_incidents_by_status(status):
    """Get incidents by status"""
    return Incident.query.filter_by(status=status).order_by(Incident.reported_at.desc()).all()

def get_nearby_incidents(latitude, longitude, radius_km=5):
    """Get incidents within radius of a location"""
    # This is a simplified query - for production use PostGIS or similar
    incidents = Incident.query.filter(
        Incident.status != IncidentStatus.RESOLVED,
        Incident.status != IncidentStatus.CANCELLED
    ).all()
    
    nearby = []
    for incident in incidents:
        distance = incident.distance_to(latitude, longitude)
        if distance and distance <= radius_km:
            nearby.append({
                'incident': incident.to_dict(),
                'distance_km': round(distance, 2)
            })
    
    return sorted(nearby, key=lambda x: x['distance_km'])

def get_incident_statistics(days=7):
    """Get incident statistics for last N days"""
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    incidents = Incident.query.filter(Incident.reported_at >= cutoff_date).all()
    
    stats = {
        'total_incidents': len(incidents),
        'by_type': {},
        'by_severity': {},
        'by_status': {},
        'avg_response_time': 0,
        'total_patients': 0,
        'total_fatalities': 0,
        'resolved_count': 0,
        'active_count': 0
    }
    
    total_response_time = 0
    resolved_with_response = 0
    
    for incident in incidents:
        # Count by type
        type_name = incident.incident_type.value if incident.incident_type else 'unknown'
        stats['by_type'][type_name] = stats['by_type'].get(type_name, 0) + 1
        
        # Count by severity
        severity_val = incident.severity.value if incident.severity else 0
        severity_name = f"level_{severity_val}"
        stats['by_severity'][severity_name] = stats['by_severity'].get(severity_name, 0) + 1
        
        # Count by status
        status_name = incident.status.value if incident.status else 'unknown'
        stats['by_status'][status_name] = stats['by_status'].get(status_name, 0) + 1
        
        # Patient stats
        stats['total_patients'] += incident.patient_count
        stats['total_fatalities'] += incident.fatalities
        
        # Active vs resolved
        if incident.status in [IncidentStatus.RESOLVED, IncidentStatus.CANCELLED]:
            stats['resolved_count'] += 1
        else:
            stats['active_count'] += 1
        
        # Response time
        if incident.response_time and incident.response_time > 0:
            total_response_time += incident.response_time
            resolved_with_response += 1
    
    # Average response time
    if resolved_with_response > 0:
        stats['avg_response_time'] = round(total_response_time / resolved_with_response, 2)
    
    return stats


def create_sample_incident():
    """Create a sample incident for testing"""
    sample_incident = Incident(
        incident_type=IncidentType.ACCIDENT,
        severity=IncidentSeverity.HIGH,
        latitude=28.6139,
        longitude=77.2090,
        title="Major Road Accident on NH-24",
        description="Multiple vehicle collision with injuries reported",
        reported_by="Traffic Control",
        reporter_phone="100",
        patient_count=3,
        casualties=2,
        fatalities=1,
        address="NH-24, Near Ghaziabad Border",
        city="Delhi"
    )
    
    existing = Incident.query.filter_by(title="Major Road Accident on NH-24").first()
    if not existing:
        db.session.add(sample_incident)
        db.session.commit()
        logger.info("Sample incident created")
    
    return sample_incident


# ============================================
# EXPORTS
# ============================================

__all__ = [
    'Incident',
    'IncidentType',
    'IncidentSeverity',
    'IncidentStatus',
    'PatientCondition',
    'IncidentAlert',
    'find_incident_by_id',
    'find_incident_by_uuid',
    'get_active_incidents',
    'get_incidents_by_status',
    'get_nearby_incidents',
    'get_incident_statistics',
    'create_sample_incident'
]