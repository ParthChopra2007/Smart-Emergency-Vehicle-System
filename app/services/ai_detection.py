"""
Smart Emergency Vehicle Priority System - AI Detection Service
Handles vehicle detection, emergency vehicle identification, traffic flow analysis,
and license plate recognition using YOLOv8 and computer vision
"""

import cv2
import numpy as np
from datetime import datetime
from loguru import logger
import threading
import queue
from typing import List, Dict, Tuple, Optional
import asyncio
from collections import deque
import json

from app.extensions import db, socketio

# ============================================
# YOLO IMPORTS (Loaded lazily to avoid startup issues)
# ============================================

class YOLOLoader:
    """Lazy loader for YOLO model to improve startup time"""
    _model = None
    _lock = threading.Lock()
    
    @classmethod
    def get_model(cls, model_path='yolov8n.pt'):
        """Get YOLO model instance (singleton)"""
        if cls._model is None:
            with cls._lock:
                if cls._model is None:
                    try:
                        from ultralytics import YOLO
                        cls._model = YOLO(model_path)
                        logger.info(f"✅ YOLO model loaded from {model_path}")
                    except Exception as e:
                        logger.error(f"Failed to load YOLO model: {e}")
                        cls._model = None
        return cls._model


# ============================================
# VEHICLE DETECTION SERVICE
# ============================================

class VehicleDetectionService:
    """
    Main service for vehicle detection and classification
    Uses YOLOv8 for real-time object detection
    """
    
    # COCO class mapping for vehicle types
    VEHICLE_CLASSES = {
        2: 'car',
        3: 'motorcycle',
        5: 'bus',
        7: 'truck',
        1: 'bicycle'
    }
    
    # Emergency vehicle detection (custom training or siren detection)
    EMERGENCY_CLASSES = {
        'ambulance': 0,
        'fire_truck': 1,
        'police_car': 2
    }
    
    def __init__(self, app=None, confidence_threshold=0.5):
        self.app = app
        self.confidence_threshold = confidence_threshold
        self.model = None
        self.frame_queue = queue.Queue(maxsize=100)
        self.result_queue = queue.Queue()
        self.is_running = False
        self.processing_thread = None
        self.stats = {
            'total_detections': 0,
            'emergency_detections': 0,
            'avg_inference_time_ms': 0,
            'fps': 0
        }
        self.inference_times = deque(maxlen=100)
        
    def init_model(self):
        """Initialize YOLO model"""
        if self.model is None:
            self.model = YOLOLoader.get_model()
            return self.model is not None
        return True
    
    def detect_vehicles(self, image: np.ndarray) -> List[Dict]:
        """
        Detect vehicles in an image
        Returns list of detections with bounding boxes, class, confidence
        """
        if not self.init_model():
            return []
        
        try:
            start_time = datetime.utcnow()
            
            # Run inference
            results = self.model(image, conf=self.confidence_threshold)
            
            # Calculate inference time
            inference_time = (datetime.utcnow() - start_time).total_seconds() * 1000
            self.inference_times.append(inference_time)
            self.stats['avg_inference_time_ms'] = sum(self.inference_times) / len(self.inference_times)
            
            detections = []
            for result in results:
                boxes = result.boxes
                if boxes is not None:
                    for box in boxes:
                        class_id = int(box.cls[0])
                        confidence = float(box.conf[0])
                        
                        # Filter for vehicle classes
                        if class_id in self.VEHICLE_CLASSES:
                            x1, y1, x2, y2 = box.xyxy[0].tolist()
                            detections.append({
                                'class': self.VEHICLE_CLASSES[class_id],
                                'class_id': class_id,
                                'confidence': confidence,
                                'bbox': [int(x1), int(y1), int(x2), int(y2)],
                                'center': [int((x1 + x2) / 2), int((y1 + y2) / 2)],
                                'width': int(x2 - x1),
                                'height': int(y2 - y1),
                                'timestamp': datetime.utcnow().isoformat()
                            })
            
            self.stats['total_detections'] += len(detections)
            return detections
            
        except Exception as e:
            logger.error(f"Vehicle detection error: {e}")
            return []
    
    def detect_emergency_vehicles(self, image: np.ndarray, siren_detected: bool = False) -> List[Dict]:
        """
        Detect emergency vehicles specifically
        Combines visual detection with siren detection
        """
        detections = self.detect_vehicles(image)
        
        emergency_detections = []
        
        for detection in detections:
            # Check if it might be an emergency vehicle based on appearance
            # In production, you'd have a custom-trained model for this
            if detection['class'] in ['car', 'truck', 'bus']:
                # Analyze region for emergency markings/colors
                bbox = detection['bbox']
                roi = image[bbox[1]:bbox[3], bbox[0]:bbox[2]]
                
                # Simple color-based emergency detection (red/white/blue patterns)
                is_emergency = self._check_emergency_colors(roi)
                
                if is_emergency or siren_detected:
                    detection['is_emergency'] = True
                    detection['emergency_type'] = self._classify_emergency_type(roi)
                    emergency_detections.append(detection)
                    self.stats['emergency_detections'] += 1
        
        return emergency_detections
    
    def _check_emergency_colors(self, roi: np.ndarray) -> bool:
        """Check if region contains emergency vehicle colors (red/white/blue patterns)"""
        if roi.size == 0:
            return False
        
        # Convert to HSV for better color detection
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        
        # Red color range (ambulance/fire)
        red_lower = np.array([0, 50, 50])
        red_upper = np.array([10, 255, 255])
        red_mask = cv2.inRange(hsv, red_lower, red_upper)
        
        # Blue color range (police)
        blue_lower = np.array([100, 50, 50])
        blue_upper = np.array([130, 255, 255])
        blue_mask = cv2.inRange(hsv, blue_lower, blue_upper)
        
        # Calculate color percentages
        red_percentage = np.sum(red_mask > 0) / (roi.shape[0] * roi.shape[1])
        blue_percentage = np.sum(blue_mask > 0) / (roi.shape[0] * roi.shape[1])
        
        return red_percentage > 0.1 or blue_percentage > 0.1
    
    def _classify_emergency_type(self, roi: np.ndarray) -> str:
        """Classify the type of emergency vehicle"""
        hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
        
        red_lower = np.array([0, 50, 50])
        red_upper = np.array([10, 255, 255])
        red_mask = cv2.inRange(hsv, red_lower, red_upper)
        red_percentage = np.sum(red_mask > 0) / (roi.shape[0] * roi.shape[1])
        
        blue_lower = np.array([100, 50, 50])
        blue_upper = np.array([130, 255, 255])
        blue_mask = cv2.inRange(hsv, blue_lower, blue_upper)
        blue_percentage = np.sum(blue_mask > 0) / (roi.shape[0] * roi.shape[1])
        
        if red_percentage > blue_percentage:
            return 'ambulance_fire'
        else:
            return 'police'
    
    def detect_from_frame(self, frame: bytes, frame_id: str = None) -> Dict:
        """
        Process a camera frame (bytes) and return detections
        """
        try:
            # Convert bytes to numpy array
            nparr = np.frombuffer(frame, np.uint8)
            image = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if image is None:
                return {'error': 'Invalid image data'}
            
            # Run detection
            detections = self.detect_vehicles(image)
            emergency_detections = self.detect_emergency_vehicles(image)
            
            return {
                'frame_id': frame_id,
                'timestamp': datetime.utcnow().isoformat(),
                'total_vehicles': len(detections),
                'emergency_vehicles': len(emergency_detections),
                'detections': detections,
                'emergency_detections': emergency_detections,
                'performance': {
                    'inference_time_ms': round(self.stats['avg_inference_time_ms'], 2)
                }
            }
            
        except Exception as e:
            logger.error(f"Frame detection error: {e}")
            return {'error': str(e)}
    
    def get_stats(self) -> Dict:
        """Get service statistics"""
        return {
            'total_detections': self.stats['total_detections'],
            'emergency_detections': self.stats['emergency_detections'],
            'avg_inference_time_ms': round(self.stats['avg_inference_time_ms'], 2),
            'fps': round(1000 / self.stats['avg_inference_time_ms']) if self.stats['avg_inference_time_ms'] > 0 else 0
        }
    
    def health_check(self) -> bool:
        """Check if service is healthy"""
        return self.init_model()


# ============================================
# EMERGENCY VEHICLE DETECTOR
# ============================================

class EmergencyVehicleDetector:
    """
    Specialized detector for emergency vehicles
    Combines visual, audio (siren), and GPS data
    """
    
    def __init__(self):
        self.detection_history: Dict[int, List[Dict]] = {}  # vehicle_id -> detection history
        self.siren_patterns = self._init_siren_patterns()
        
    def _init_siren_patterns(self):
        """Initialize siren frequency patterns"""
        return {
            'ambulance': {'low_freq': 600, 'high_freq': 800, 'pulse_rate': 2},
            'police': {'low_freq': 800, 'high_freq': 1000, 'pulse_rate': 3},
            'fire': {'low_freq': 500, 'high_freq': 700, 'pulse_rate': 1.5}
        }
    
    def detect_siren(self, audio_data: np.ndarray) -> Optional[str]:
        """
        Detect siren type from audio data
        Returns vehicle type if detected, None otherwise
        """
        # Simplified implementation - in production, use audio processing libraries
        # This would use FFT to analyze frequency patterns
        
        # Placeholder logic
        return None
    
    def track_vehicle(self, vehicle_id: int, detection: Dict):
        """Track a vehicle across multiple frames"""
        if vehicle_id not in self.detection_history:
            self.detection_history[vehicle_id] = []
        
        self.detection_history[vehicle_id].append({
            'timestamp': datetime.utcnow(),
            'location': detection.get('center'),
            'confidence': detection.get('confidence', 0)
        })
        
        # Keep only last 100 detections
        if len(self.detection_history[vehicle_id]) > 100:
            self.detection_history[vehicle_id].pop(0)
    
    def get_vehicle_path(self, vehicle_id: int) -> List[Dict]:
        """Get path history for a vehicle"""
        return self.detection_history.get(vehicle_id, [])
    
    def calculate_speed(self, vehicle_id: int, fps: float = 30) -> Optional[float]:
        """
        Calculate vehicle speed based on position change
        Returns speed in km/h
        """
        history = self.detection_history.get(vehicle_id, [])
        if len(history) < 10:
            return None
        
        # Get positions over time
        recent = history[-10:]
        first = recent[0]
        last = recent[-1]
        
        time_diff = (last['timestamp'] - first['timestamp']).total_seconds()
        if time_diff <= 0:
            return None
        
        # Calculate pixel distance (needs camera calibration for real speed)
        # This is simplified - would need camera calibration in production
        pixel_distance = np.linalg.norm(
            np.array(last['location']) - np.array(first['location'])
        )
        
        # Rough conversion (1 pixel ≈ 0.1 meters)
        distance_meters = pixel_distance * 0.1
        speed_kmh = (distance_meters / 1000) / (time_diff / 3600)
        
        return round(speed_kmh, 1)


# ============================================
# TRAFFIC FLOW ANALYZER
# ============================================

class TrafficFlowAnalyzer:
    """
    Analyzes traffic flow from camera feeds
    Calculates vehicle count, density, speed, and congestion levels
    """
    
    def __init__(self, camera_id: str, detection_service: VehicleDetectionService):
        self.camera_id = camera_id
        self.detection_service = detection_service
        self.vehicle_counts = deque(maxlen=3600)  # Last hour of counts
        self.speed_data = deque(maxlen=3600)
        self.line_counter_position = None
        self.vehicles_passed = 0
        
    def set_counting_line(self, y_position: int):
        """Set the line position for vehicle counting"""
        self.line_counter_position = y_position
    
    def process_frame(self, frame: np.ndarray) -> Dict:
        """
        Process a frame and analyze traffic flow
        """
        detections = self.detection_service.detect_vehicles(frame)
        
        # Count vehicles crossing the line
        new_vehicles = 0
        vehicle_speeds = []
        
        for detection in detections:
            center_y = detection['center'][1]
            if self.line_counter_position and abs(center_y - self.line_counter_position) < 20:
                new_vehicles += 1
            
            # Estimate speed
            # In production, track vehicles across frames
            pass
        
        self.vehicles_passed += new_vehicles
        
        # Calculate flow rate (vehicles per minute)
        flow_rate = (self.vehicles_passed / 60) if len(self.vehicle_counts) > 0 else 0
        
        # Determine congestion level
        if flow_rate < 20:
            congestion = 'low'
        elif flow_rate < 50:
            congestion = 'medium'
        elif flow_rate < 100:
            congestion = 'high'
        else:
            congestion = 'gridlock'
        
        return {
            'camera_id': self.camera_id,
            'timestamp': datetime.utcnow().isoformat(),
            'vehicles_detected': len(detections),
            'vehicles_passed': new_vehicles,
            'total_vehicles_today': self.vehicles_passed,
            'flow_rate_per_minute': round(flow_rate, 1),
            'congestion_level': congestion,
            'average_speed_kmh': round(np.mean(self.speed_data) if self.speed_data else 0, 1)
        }
    
    def get_density(self) -> str:
        """Get current traffic density level"""
        if not self.vehicle_counts:
            return 'unknown'
        
        avg_count = sum(self.vehicle_counts) / len(self.vehicle_counts)
        
        if avg_count < 10:
            return 'low'
        elif avg_count < 30:
            return 'medium'
        elif avg_count < 60:
            return 'high'
        else:
            return 'gridlock'
    
    def reset_daily_count(self):
        """Reset daily vehicle count"""
        self.vehicles_passed = 0


# ============================================
# LICENSE PLATE RECOGNIZER
# ============================================

class LicensePlateRecognizer:
    """
    Recognizes license plates from vehicle images
    Uses OCR for plate number extraction
    """
    
    def __init__(self):
        self.recognized_plates = {}
        
    def detect_plate_region(self, image: np.ndarray) -> Optional[Tuple[int, int, int, int]]:
        """
        Detect license plate region in image
        Returns bounding box coordinates
        """
        # Convert to grayscale
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        
        # Apply morphological operations
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (3, 3))
        morph = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
        
        # Edge detection
        edges = cv2.Canny(morph, 100, 200)
        
        # Find contours
        contours, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        
        for contour in contours:
            area = cv2.contourArea(contour)
            if 1000 < area < 20000:
                x, y, w, h = cv2.boundingRect(contour)
                aspect_ratio = w / h
                
                # License plate aspect ratio typically between 2:1 and 5:1
                if 2 < aspect_ratio < 5:
                    return (x, y, w, h)
        
        return None
    
    def extract_plate_text(self, plate_region: np.ndarray) -> Optional[str]:
        """
        Extract text from license plate using OCR
        """
        try:
            import easyocr
            reader = easyocr.Reader(['en'])

            # Convert to RGB (EasyOCR expects RGB)
            if len(plate_region.shape) == 2:
                plate_rgb = cv2.cvtColor(plate_region, cv2.COLOR_GRAY2RGB)
            else:
                plate_rgb = cv2.cvtColor(plate_region, cv2.COLOR_BGR2RGB)
            
            # Perform OCR
            result = reader.readtext(plate_rgb, detail=0)
            
            if result:
                plate_text = result[0].upper()
                # Clean up the text (remove spaces, special characters)
                plate_text = ''.join(c for c in plate_text if c.isalnum())
                return plate_text if len(plate_text) >= 4 else None
            
            return None
            
        except ImportError:
            # Fallback for development without easyocr
            logger.warning("EasyOCR not installed. Plate recognition disabled.")
            return None
        except Exception as e:
            logger.error(f"OCR error: {e}")
            return None
    
    def recognize_from_detection(self, image: np.ndarray, detection_bbox: List[int]) -> Optional[str]:
        """
        Extract license plate from a vehicle detection
        """
        x1, y1, x2, y2 = detection_bbox
        
        # Extract vehicle region
        vehicle_region = image[y1:y2, x1:x2]
        if vehicle_region.size == 0:
            return None
        
        # Detect plate region
        plate_bbox = self.detect_plate_region(vehicle_region)
        if not plate_bbox:
            return None
        
        px, py, pw, ph = plate_bbox
        
        # Extract plate region
        plate_region = vehicle_region[py:py+ph, px:px+pw]
        if plate_region.size == 0:
            return None
        
        # Resize for better OCR
        plate_region = cv2.resize(plate_region, (400, 100))
        
        # Enhance image
        plate_region = cv2.cvtColor(plate_region, cv2.COLOR_BGR2GRAY)
        plate_region = cv2.bilateralFilter(plate_region, 9, 75, 75)
        plate_region = cv2.threshold(plate_region, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
        
        # Extract text
        plate_text = self.extract_plate_text(plate_region)
        
        return plate_text


# ============================================
# SERVICE FACTORY FUNCTIONS
# ============================================

_detection_service = None
_emergency_detector = None
_traffic_analyzers = {}
_plate_recognizer = None


def get_ai_service(app=None):
    """Get or create AI detection service instance"""
    global _detection_service, _emergency_detector, _plate_recognizer
    
    if _detection_service is None:
        confidence_threshold = 0.5
        if app and hasattr(app, 'config'):
            confidence_threshold = app.config.get('VEHICLE_DETECTION_CONFIDENCE', 0.5)
        
        _detection_service = VehicleDetectionService(app, confidence_threshold)
        _detection_service.init_model()
        logger.info("AI Detection Service created")
    
    if _emergency_detector is None:
        _emergency_detector = EmergencyVehicleDetector()
    
    if _plate_recognizer is None:
        _plate_recognizer = LicensePlateRecognizer()
    
    return _detection_service


def get_emergency_detector():
    """Get emergency vehicle detector instance"""
    global _emergency_detector
    if _emergency_detector is None:
        _emergency_detector = EmergencyVehicleDetector()
    return _emergency_detector


def get_plate_recognizer():
    """Get license plate recognizer instance"""
    global _plate_recognizer
    if _plate_recognizer is None:
        _plate_recognizer = LicensePlateRecognizer()
    return _plate_recognizer


def get_traffic_analyzer(camera_id: str):
    """Get or create traffic analyzer for a camera"""
    global _traffic_analyzers
    
    if camera_id not in _traffic_analyzers:
        detection_service = get_ai_service()
        _traffic_analyzers[camera_id] = TrafficFlowAnalyzer(camera_id, detection_service)
    
    return _traffic_analyzers[camera_id]


# ============================================
# EXPORTS
# ============================================

__all__ = [
    'VehicleDetectionService',
    'EmergencyVehicleDetector',
    'TrafficFlowAnalyzer',
    'LicensePlateRecognizer',
    'get_ai_service',
    'get_emergency_detector',
    'get_plate_recognizer',
    'get_traffic_analyzer'
]