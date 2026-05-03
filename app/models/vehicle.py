"""
Smart Emergency Vehicle Priority System - Emergency Vehicle Model
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
# ENUMS
# ============================================

class VehicleType(enum.Enum):
    AMBULANCE = "ambulance"
    FIRE_BRIGADE = "fire_brigade"
    POLICE = "police"
    DISASTER_MANAGEMENT = "disaster_management"
    RESCUE = "rescue"


class VehicleStatus(enum.Enum):
    AVAILABLE = "available"
    ON_DUTY = "on_duty"
    EN_ROUTE = "en_route"
    AT_SCENE = "at_scene"
    RETURNING = "returning"
    OFF_DUTY = "off_duty"
    MAINTENANCE = "maintenance"
    OUT_OF_SERVICE = "out_of_service"


class VehicleEmergencyLevel(enum.Enum):
    LEVEL_1 = 1
    LEVEL_2 = 2
    LEVEL_3 = 3
    LEVEL_4 = 4


class VehicleEquipmentStatus(enum.Enum):
    FULLY_EQUIPPED = "fully_equipped"
    PARTIALLY_EQUIPPED = "partially_equipped"
    NEEDS_RESTOCK = "needs_restock"
    MAINTENANCE_REQUIRED = "maintenance_required"


# ============================================
# EMERGENCY VEHICLE MODEL
# ============================================

class EmergencyVehicle(db.Model):
    __tablename__ = 'emergency_vehicles'
    __table_args__ = (
        db.Index('idx_vehicle_type_status', 'vehicle_type', 'status'),
        db.Index('idx_vehicle_location', 'current_latitude', 'current_longitude'),
        db.Index('idx_vehicle_registration', 'registration_number'),
    )

    # Basic Identification
    id = Column(Integer, primary_key=True)
    vehicle_uuid = Column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    registration_number = Column(String(50), unique=True, nullable=False, index=True)
    vehicle_type = Column(Enum(VehicleType), nullable=False)

    # Vehicle Details
    make = Column(String(100), nullable=False)
    model = Column(String(100), nullable=False)
    year = Column(Integer, nullable=False)
    color = Column(String(50), nullable=True)
    fuel_type = Column(String(50), default="diesel")

    # Organization
    department = Column(String(255), nullable=False)
    station_location = Column(String(500), nullable=True)
    station_latitude = Column(Float, nullable=True)
    station_longitude = Column(Float, nullable=True)

    # Crew Information
    driver_name = Column(String(255), nullable=True)
    driver_contact = Column(String(20), nullable=True)
    driver_license_number = Column(String(100), nullable=True)
    assigned_driver_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    crew_members = Column(JSON, default=[])
    crew_count = Column(Integer, default=2)

    # Capabilities & Equipment
    capacity_patients = Column(Integer, default=1)
    capacity_personnel = Column(Integer, default=4)
    equipment_status = Column(Enum(VehicleEquipmentStatus), default=VehicleEquipmentStatus.FULLY_EQUIPPED)
    equipment_list = Column(JSON, default={})
    has_life_support = Column(Boolean, default=False)
    has_oxygen = Column(Boolean, default=True)
    has_defibrillator = Column(Boolean, default=False)
    has_water_tank = Column(Boolean, default=False)
    has_ladder = Column(Boolean, default=False)

    # Real-time Location
    current_latitude = Column(Float, nullable=True)
    current_longitude = Column(Float, nullable=True)
    current_speed = Column(Float, default=0.0)
    current_heading = Column(Float, nullable=True)
    last_location_update = Column(DateTime, nullable=True)

    # Battery/Fuel
    fuel_level = Column(Float, default=100.0)
    battery_level = Column(Float, nullable=True)

    # Emergency Status
    status = Column(Enum(VehicleStatus), default=VehicleStatus.AVAILABLE)
    emergency_level = Column(Enum(VehicleEmergencyLevel), nullable=True)
    is_siren_active = Column(Boolean, default=False)
    is_lights_active = Column(Boolean, default=False)
    current_incident_id = Column(Integer, ForeignKey('incidents.id'), nullable=True)
    current_destination = Column(String(500), nullable=True)
    current_destination_latitude = Column(Float, nullable=True)
    current_destination_longitude = Column(Float, nullable=True)

    # Active Green Corridor
    active_corridor_id = Column(Integer, ForeignKey('green_corridors.id'), nullable=True)
    corridor_requested_at = Column(DateTime, nullable=True)
    corridor_active_until = Column(DateTime, nullable=True)

    # Statistics
    total_emergencies_handled = Column(Integer, default=0)
    total_distance_traveled = Column(Float, default=0.0)
    total_active_hours = Column(Float, default=0.0)
    average_response_time = Column(Float, default=0.0)
    average_onscene_time = Column(Float, default=0.0)

    # Communication
    communication_device_id = Column(String(100), nullable=True)
    mqtt_topic = Column(String(255), nullable=True)

    # Maintenance
    last_maintenance_date = Column(DateTime, nullable=True)
    next_maintenance_due = Column(DateTime, nullable=True)
    maintenance_notes = Column(Text, nullable=True)

    # Metadata
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    notes = Column(Text, nullable=True)
    metadata = Column(JSON, default={})

    # Relationships
    assigned_driver = relationship("User", back_populates="assigned_vehicle", foreign_keys=[assigned_driver_id])
    current_incident = relationship("Incident", foreign_keys=[current_incident_id])
    active_corridor = relationship("GreenCorridor", foreign_keys=[active_corridor_id])

    # ============================================
    # METHODS
    # ============================================

    def __init__(self, registration_number, vehicle_type, make, model, year, department, **kwargs):
        self.registration_number = registration_number
        self.vehicle_type = vehicle_type
        self.make = make
        self.model = model
        self.year = year
        self.department = department
        self.vehicle_uuid = str(uuid.uuid4())
        self.mqtt_topic = f"vehicles/emergency/{self.vehicle_uuid}"

        for key, value in kwargs.items():
            setattr(self, key, value)

    def update_location(self, latitude, longitude, speed=None, heading=None):
        old_location = (self.current_latitude, self.current_longitude)
        self.current_latitude = latitude
        self.current_longitude = longitude

        if speed is not None:
            self.current_speed = speed
        if heading is not None:
            self.current_heading = heading

        self.last_location_update = datetime.utcnow()

        if old_location[0] and old_location[1]:
            try:
                distance = geodesic(old_location, (latitude, longitude)).kilometers
                self.total_distance_traveled += distance
            except:
                pass

        db.session.commit()
        return distance if 'distance' in locals() else 0

    def get_current_location(self):
        return {
            'latitude': self.current_latitude,
            'longitude': self.current_longitude,
            'speed': self.current_speed,
            'heading': self.current_heading,
            'last_update': self.last_location_update.isoformat() if self.last_location_update else None
        }

    def distance_to(self, latitude, longitude):
        if not self.current_latitude or not self.current_longitude:
            return None
        try:
            return geodesic((self.current_latitude, self.current_longitude), (latitude, longitude)).kilometers
        except:
            return None

    def set_available(self):
        self.status = VehicleStatus.AVAILABLE
        self.emergency_level = None
        self.is_siren_active = False
        self.is_lights_active = False
        self.current_incident_id = None
        self.current_destination = None
        self.active_corridor_id = None
        self.corridor_active_until = None
        db.session.commit()

    def to_dict(self, include_sensitive=False):
        vehicle_dict = {
            'id': self.id,
            'vehicle_uuid': self.vehicle_uuid,
            'registration_number': self.registration_number,
            'vehicle_type': self.vehicle_type.value if self.vehicle_type else None,
            'make': self.make,
            'model': self.model,
            'year': self.year,
            'color': self.color,
            'department': self.department,
            'status': self.status.value if self.status else None,
            'emergency_level': self.emergency_level.value if self.emergency_level else None,
            'is_siren_active': self.is_siren_active,
            'is_lights_active': self.is_lights_active,
            'driver_name': self.driver_name,
            'driver_contact': self.driver_contact,
            'assigned_driver_id': self.assigned_driver_id,
            'crew_count': self.crew_count,
            'current_location': self.get_current_location(),
            'current_speed': self.current_speed,
            'capacity_patients': self.capacity_patients,
            'has_life_support': self.has_life_support,
            'active_corridor_id': self.active_corridor_id,
            'total_emergencies_handled': self.total_emergencies_handled,
            'total_distance_traveled': round(self.total_distance_traveled, 2),
            'average_response_time': round(self.average_response_time, 2),
            'is_active': self.is_active,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }
        return vehicle_dict

    def __repr__(self):
        return f"<EmergencyVehicle {self.registration_number}>"


# ============================================
# HELPER FUNCTIONS
# ============================================

def find_vehicle_by_id(vehicle_id):
    return EmergencyVehicle.query.get(vehicle_id)


def find_vehicle_by_registration(registration_number):
    return EmergencyVehicle.query.filter_by(registration_number=registration_number).first()


def get_all_emergency_vehicles(vehicle_type=None, status=None):
    query = EmergencyVehicle.query.filter_by(is_active=True)
    if vehicle_type:
        query = query.filter_by(vehicle_type=vehicle_type)
    if status:
        query = query.filter_by(status=status)
    return query.all()


def get_available_vehicles(vehicle_type=None):
    query = EmergencyVehicle.query.filter_by(status=VehicleStatus.AVAILABLE, is_active=True)
    if vehicle_type:
        query = query.filter_by(vehicle_type=vehicle_type)
    return query.all()


def create_sample_vehicles():
    vehicles_data = [
        {
            'registration_number': 'DL-01-AB-1234',
            'vehicle_type': VehicleType.AMBULANCE,
            'make': 'Mercedes',
            'model': 'Sprinter',
            'year': 2022,
            'department': 'City Ambulance Service',
            'driver_name': 'Rajesh Kumar',
            'capacity_patients': 2,
            'has_life_support': True
        },
        {
            'registration_number': 'DL-02-FG-5678',
            'vehicle_type': VehicleType.FIRE_BRIGADE,
            'make': 'Volvo',
            'model': 'Fire Truck',
            'year': 2021,
            'department': 'Delhi Fire Service',
            'driver_name': 'Suresh Singh',
            'has_water_tank': True,
            'has_ladder': True
        },
        {
            'registration_number': 'DL-03-PL-9012',
            'vehicle_type': VehicleType.POLICE,
            'make': 'Toyota',
            'model': 'Innova',
            'year': 2023,
            'department': 'Delhi Police',
            'driver_name': 'Vikram Rathore'
        }
    ]

    for data in vehicles_data:
        existing = find_vehicle_by_registration(data['registration_number'])
        if not existing:
            vehicle = EmergencyVehicle(**data)
            db.session.add(vehicle)

    db.session.commit()
    logger.info("Sample vehicles created successfully")


__all__ = [
    'EmergencyVehicle',
    'VehicleType',
    'VehicleStatus',
    'VehicleEmergencyLevel',
    'VehicleEquipmentStatus',
    'find_vehicle_by_id',
    'find_vehicle_by_registration',
    'get_all_emergency_vehicles',
    'get_available_vehicles',
    'create_sample_vehicles'
]