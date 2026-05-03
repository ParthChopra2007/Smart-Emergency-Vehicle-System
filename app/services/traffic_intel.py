"""
Smart Emergency Vehicle Priority System - Traffic Intelligence Service
Handles real-time traffic analysis, congestion prediction, route optimization,
and AI-based traffic flow management for emergency vehicle corridors
"""

import numpy as np
import threading
import json
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Optional, Any
from dataclasses import dataclass, field
from collections import deque, defaultdict
from loguru import logger
import math
import random

from app.extensions import db, socketio, redis_client, cache

# ============================================
# DATA CLASSES
# ============================================

@dataclass
class TrafficData:
    """Represents real-time traffic data for a segment"""
    segment_id: str
    vehicle_count: int
    average_speed: float  # km/h
    density: str  # low, medium, high, gridlock
    timestamp: datetime
    occupancy: float = 0.0  # percentage
    travel_time_index: float = 1.0  # ratio to free-flow time
    
    def to_dict(self) -> Dict:
        return {
            'segment_id': self.segment_id,
            'vehicle_count': self.vehicle_count,
            'average_speed': self.average_speed,
            'density': self.density,
            'timestamp': self.timestamp.isoformat(),
            'occupancy': self.occupancy,
            'travel_time_index': self.travel_time_index
        }


@dataclass
class CongestionPrediction:
    """Represents a congestion prediction for a future time"""
    segment_id: str
    predicted_density: str
    predicted_speed: float
    confidence: float
    prediction_time: datetime
    valid_until: datetime


@dataclass
class RouteRecommendation:
    """Represents a recommended route for emergency vehicle"""
    route_id: str
    waypoints: List[Tuple[float, float]]
    total_distance_km: float
    estimated_duration_seconds: int
    congestion_level: str
    signal_count: int
    confidence: float


# ============================================
# TRAFFIC PREDICTOR (ML-based)
# ============================================

class TrafficPredictor:
    """
    Predicts traffic conditions using machine learning models
    Uses historical data and real-time inputs for forecasting
    """
    
    def __init__(self):
        self.model = None
        self.historical_data = defaultdict(list)
        self.predictions = {}  # segment_id -> list of predictions
        self._training_thread = None
        self._is_running = False
        self.feature_columns = ['hour', 'day_of_week', 'is_weekend', 'is_holiday', 
                                 'vehicle_count', 'average_speed', 'weather_score']
        
        # Initialize with sample distribution data
        self._init_traffic_distributions()
        self.start_training()
    
    def _init_traffic_distributions(self):
        """Initialize traffic patterns based on time of day"""
        # Typical traffic patterns for different times (speed in km/h)
        self.traffic_patterns = {
            'midnight': {'speed': 50, 'density': 'low', 'weight': 0.8},      # 00:00-06:00
            'morning': {'speed': 30, 'density': 'medium', 'weight': 1.2},     # 06:00-10:00
            'midday': {'speed': 40, 'density': 'medium', 'weight': 1.0},      # 10:00-16:00
            'evening': {'speed': 25, 'density': 'high', 'weight': 1.5},       # 16:00-20:00
            'night': {'speed': 45, 'density': 'low', 'weight': 0.9}           # 20:00-00:00
        }
        
        logger.info(f"Traffic patterns initialized with {len(self.traffic_patterns)} time segments")
    
    def start_training(self):
        """Start background training thread"""
        if self._training_thread is None:
            self._is_running = True
            self._training_thread = threading.Thread(target=self._train_background)
            self._training_thread.daemon = True
            self._training_thread.start()
            logger.info("Traffic predictor training started")
    
    def _train_background(self):
        """Background training process"""
        while self._is_running:
            try:
                # In production, this would train ML models
                # For now, just update patterns based on recent data
                self._update_patterns_from_historical()
                
                import time
                time.sleep(3600)  # Train every hour
                
            except Exception as e:
                logger.error(f"Training error: {e}")
                import time
                time.sleep(300)
    
    def _update_patterns_from_historical(self):
        """Update traffic patterns based on historical data"""
        # Placeholder for ML training
        # In production, would use scikit-learn or tensorflow
        pass
    
    def get_time_segment(self, hour: int) -> str:
        """Get time segment based on hour"""
        if 0 <= hour < 6:
            return 'midnight'
        elif 6 <= hour < 10:
            return 'morning'
        elif 10 <= hour < 16:
            return 'midday'
        elif 16 <= hour < 20:
            return 'evening'
        else:
            return 'night'
    
    def predict_traffic(self, segment_id: str, future_minutes: int = 15) -> Optional[CongestionPrediction]:
        """
        Predict traffic conditions for a segment in the future
        """
        try:
            now = datetime.utcnow()
            future_time = now + timedelta(minutes=future_minutes)
            hour = future_time.hour
            day_of_week = future_time.weekday()
            is_weekend = day_of_week >= 5
            
            # Get pattern for this time
            pattern = self.traffic_patterns.get(self.get_time_segment(hour), self.traffic_patterns['midday'])
            
            # Add random variation for realism
            variation = random.uniform(0.8, 1.2)
            predicted_speed = pattern['speed'] * variation
            
            # Determine density
            if predicted_speed > 45:
                density = 'low'
            elif predicted_speed > 30:
                density = 'medium'
            elif predicted_speed > 15:
                density = 'high'
            else:
                density = 'gridlock'
            
            # Calculate confidence (higher for predictable times)
            if is_weekend:
                confidence = 0.7  # Less predictable on weekends
            elif future_minutes <= 15:
                confidence = 0.9
            elif future_minutes <= 30:
                confidence = 0.8
            else:
                confidence = 0.6
            
            prediction = CongestionPrediction(
                segment_id=segment_id,
                predicted_density=density,
                predicted_speed=round(predicted_speed, 1),
                confidence=confidence,
                prediction_time=now,
                valid_until=future_time
            )
            
            # Cache prediction
            self.predictions[segment_id] = self.predictions.get(segment_id, [])[:10]
            self.predictions[segment_id].append(prediction)
            
            return prediction
            
        except Exception as e:
            logger.error(f"Prediction error for {segment_id}: {e}")
            return None
    
    def predict_route_congestion(self, waypoints: List[Tuple[float, float]], 
                                  future_minutes: int = 15) -> Dict:
        """
        Predict congestion level for an entire route
        """
        if not waypoints:
            return {'congestion_level': 'unknown', 'confidence': 0}
        
        # In production, would map waypoints to road segments
        # For demo, return based on time of day
        hour = datetime.utcnow().hour
        
        if 8 <= hour <= 10 or 17 <= hour <= 19:
            congestion_level = 'high'
            confidence = 0.8
        elif 11 <= hour <= 16:
            congestion_level = 'medium'
            confidence = 0.7
        else:
            congestion_level = 'low'
            confidence = 0.9
        
        return {
            'congestion_level': congestion_level,
            'confidence': confidence,
            'predicted_speed_kmh': self._get_speed_from_congestion(congestion_level),
            'impact_factor': self._get_congestion_impact(congestion_level)
        }
    
    def _get_speed_from_congestion(self, congestion_level: str) -> float:
        """Get estimated speed based on congestion level"""
        speeds = {
            'low': 45,
            'medium': 30,
            'high': 15,
            'gridlock': 5
        }
        return speeds.get(congestion_level, 30)
    
    def _get_congestion_impact(self, congestion_level: str) -> float:
        """Get travel time multiplier based on congestion"""
        multipliers = {
            'low': 1.0,
            'medium': 1.5,
            'high': 2.5,
            'gridlock': 4.0
        }
        return multipliers.get(congestion_level, 1.0)
    
    def add_historical_data(self, segment_id: str, traffic_data: TrafficData):
        """Add historical data for training"""
        self.historical_data[segment_id].append(traffic_data)
        
        # Keep only last 1000 records per segment
        if len(self.historical_data[segment_id]) > 1000:
            self.historical_data[segment_id] = self.historical_data[segment_id][-1000:]
    
    def get_stats(self) -> Dict:
        """Get predictor statistics"""
        return {
            'historical_segments': len(self.historical_data),
            'active_predictions': len(self.predictions),
            'is_training': self._is_running,
            'patterns_loaded': len(self.traffic_patterns)
        }
    
    def shutdown(self):
        """Shutdown predictor"""
        self._is_running = False
        if self._training_thread:
            self._training_thread.join(timeout=5)


# ============================================
# TRAFFIC OPTIMIZER
# ============================================

class TrafficOptimizer:
    """
    Optimizes traffic signal timings and routes
    Uses AI algorithms to minimize congestion and prioritize emergency vehicles
    """
    
    def __init__(self, predictor: TrafficPredictor):
        self.predictor = predictor
        self.signal_timings = {}  # signal_id -> current timing config
        self.optimization_results = {}
        
    def optimize_signal_timing(self, signal_id: int, traffic_data: TrafficData) -> Dict:
        """
        Optimize signal timing based on current traffic conditions
        """
        # Get current congestion level
        congestion = traffic_data.density
        
        # Base timing (seconds)
        base_timings = {
            'low': {'green': 30, 'yellow': 3, 'red': 30},
            'medium': {'green': 40, 'yellow': 3, 'red': 40},
            'high': {'green': 50, 'yellow': 3, 'red': 50},
            'gridlock': {'green': 60, 'yellow': 4, 'red': 60}
        }
        
        timing = base_timings.get(congestion, base_timings['medium'])
        
        # Add emergency override if needed
        emergency_active = self._check_emergency_nearby(signal_id)
        if emergency_active:
            timing['green'] = min(90, timing['green'] + 30)
        
        self.signal_timings[signal_id] = timing
        
        return {
            'signal_id': signal_id,
            'optimized_timing': timing,
            'congestion_level': congestion,
            'emergency_override': emergency_active,
            'timestamp': datetime.utcnow().isoformat()
        }
    
    def _check_emergency_nearby(self, signal_id: int) -> bool:
        """Check if emergency vehicle is approaching this signal"""
        # In production, would check active corridors
        # For demo, return based on recent corridor activity
        return False
    
    def optimize_route_for_emergency(self, start: Tuple[float, float],
                                      destination: Tuple[float, float],
                                      current_time: datetime = None) -> RouteRecommendation:
        """
        Find optimal route for emergency vehicle avoiding congestion
        """
        if current_time is None:
            current_time = datetime.utcnow()
        
        hour = current_time.hour
        
        # Determine congestion pattern
        if 8 <= hour <= 10 or 17 <= hour <= 19:
            congestion = 'high'
            multiplier = 2.5
        elif 11 <= hour <= 16:
            congestion = 'medium'
            multiplier = 1.5
        else:
            congestion = 'low'
            multiplier = 1.0
        
        # Calculate approximate distance (simplified)
        distance = self._calculate_distance(start, destination)
        
        base_speed = self.predictor._get_speed_from_congestion(congestion)
        duration_seconds = (distance / base_speed) * 3600
        
        # Generate waypoints (simplified - would use road network)
        waypoints = [start, destination]
        mid_lat = (start[0] + destination[0]) / 2
        mid_lng = (start[1] + destination[1]) / 2
        waypoints.insert(1, (mid_lat, mid_lng))
        
        route = RouteRecommendation(
            route_id=f"route_{datetime.utcnow().timestamp()}",
            waypoints=waypoints,
            total_distance_km=round(distance, 2),
            estimated_duration_seconds=int(duration_seconds),
            congestion_level=congestion,
            signal_count=int(distance * 2),  # Approx 1 signal per 500m
            confidence=0.85 if congestion != 'high' else 0.7
        )
        
        return route
    
    def _calculate_distance(self, start: Tuple[float, float], 
                            destination: Tuple[float, float]) -> float:
        """Calculate distance between two points in km"""
        from geopy.distance import geodesic
        return geodesic(start, destination).kilometers
    
    def get_alternative_routes(self, start: Tuple[float, float],
                                destination: Tuple[float, float],
                                count: int = 3) -> List[RouteRecommendation]:
        """
        Generate alternative routes for comparison
        """
        routes = []
        
        # Primary route (fastest)
        primary = self.optimize_route_for_emergency(start, destination)
        routes.append(primary)
        
        # Generate alternative routes with different waypoints
        for i in range(1, count):
            offset = 0.005 * i  # ~500m offset
            mid_lat = (start[0] + destination[0]) / 2 + offset * (1 if i % 2 == 0 else -1)
            mid_lng = (start[1] + destination[1]) / 2 + offset * (i % 2)
            
            distance = self._calculate_distance(start, destination) * (1 + i * 0.1)
            duration = primary.estimated_duration_seconds * (1 + i * 0.15)
            
            route = RouteRecommendation(
                route_id=f"alt_route_{i}_{datetime.utcnow().timestamp()}",
                waypoints=[start, (mid_lat, mid_lng), destination],
                total_distance_km=round(distance, 2),
                estimated_duration_seconds=int(duration),
                congestion_level='medium' if i == 1 else 'low',
                signal_count=int(distance * 2.5),
                confidence=0.7 - (i * 0.1)
            )
            routes.append(route)
        
        return routes


# ============================================
# CONGESTION ANALYZER
# ============================================

class CongestionAnalyzer:
    """
    Analyzes traffic congestion patterns and identifies hotspots
    """
    
    def __init__(self, predictor: TrafficPredictor):
        self.predictor = predictor
        self.congestion_hotspots = {}
        self.analysis_results = {}
    
    def analyze_congestion_level(self, traffic_data: List[TrafficData]) -> Dict:
        """
        Analyze overall congestion level for an area
        """
        if not traffic_data:
            return {'level': 'unknown', 'avg_speed': 0, 'affected_segments': 0}
        
        speeds = [data.average_speed for data in traffic_data]
        densities = [data.density for data in traffic_data]
        
        avg_speed = np.mean(speeds) if speeds else 0
        
        # Determine overall congestion
        if avg_speed > 40:
            overall_level = 'low'
        elif avg_speed > 25:
            overall_level = 'medium'
        elif avg_speed > 10:
            overall_level = 'high'
        else:
            overall_level = 'gridlock'
        
        # Count affected segments
        affected = sum(1 for d in densities if d in ['high', 'gridlock'])
        
        return {
            'overall_level': overall_level,
            'average_speed_kmh': round(avg_speed, 1),
            'affected_segments': affected,
            'total_segments': len(traffic_data),
            'congestion_ratio': round(affected / len(traffic_data) * 100, 1) if traffic_data else 0,
            'timestamp': datetime.utcnow().isoformat()
        }
    
    def identify_hotspots(self, traffic_data: Dict[str, TrafficData]) -> List[Dict]:
        """
        Identify current traffic hotspots
        """
        hotspots = []
        
        for segment_id, data in traffic_data.items():
            if data.density in ['high', 'gridlock']:
                hotspots.append({
                    'segment_id': segment_id,
                    'congestion_level': data.density,
                    'average_speed': data.average_speed,
                    'vehicle_count': data.vehicle_count,
                    'severity': 'critical' if data.density == 'gridlock' else 'high'
                })
        
        # Sort by severity
        hotspots.sort(key=lambda x: 0 if x['severity'] == 'critical' else 1)
        
        return hotspots
    
    def get_congestion_trend(self, segment_id: str, minutes: int = 30) -> Dict:
        """
        Get congestion trend for a segment over time
        """
        # In production, would query historical data
        # For demo, return simulated trend
        
        times = []
        speeds = []
        
        now = datetime.utcnow()
        for i in range(minutes // 5):
            time_point = now - timedelta(minutes=minutes - i*5)
            times.append(time_point.strftime('%H:%M'))
            
            # Simulate speed variation
            base_speed = 40
            variation = math.sin(i * 0.5) * 10
            speeds.append(max(5, base_speed + variation))
        
        # Determine trend
        if len(speeds) >= 2:
            if speeds[-1] < speeds[0]:
                trend = 'worsening'
            elif speeds[-1] > speeds[0]:
                trend = 'improving'
            else:
                trend = 'stable'
        else:
            trend = 'unknown'
        
        return {
            'segment_id': segment_id,
            'times': times,
            'speeds': speeds,
            'trend': trend,
            'current_speed': speeds[-1] if speeds else 0
        }


# ============================================
# ROUTE OPTIMIZER
# ============================================

class RouteOptimizer:
    """
    Optimizes routes for emergency vehicles considering real-time traffic
    """
    
    def __init__(self, optimizer: TrafficOptimizer, predictor: TrafficPredictor):
        self.optimizer = optimizer
        self.predictor = predictor
        self.cached_routes = {}
    
    def find_best_route(self, start: Tuple[float, float],
                        destination: Tuple[float, float],
                        priority: int = 1) -> RouteRecommendation:
        """
        Find the best route for emergency vehicle based on priority
        priority: 1=highest (ambulance), 2=fire, 3=police
        """
        # Get primary route
        primary_route = self.optimizer.optimize_route_for_emergency(start, destination)
        
        # If high priority, get alternatives and choose best
        if priority == 1:
            alternatives = self.optimizer.get_alternative_routes(start, destination, 3)
            
            # Choose route with least congestion
            best = min([primary_route] + alternatives, 
                      key=lambda x: 0 if x.congestion_level == 'low' 
                      else 1 if x.congestion_level == 'medium' 
                      else 2 if x.congestion_level == 'high' 
                      else 3)
            
            # Cache the route
            cache_key = f"route_{start[0]:.3f}_{start[1]:.3f}_{destination[0]:.3f}_{destination[1]:.3f}"
            self.cached_routes[cache_key] = best
            cache.set(cache_key, best.to_dict() if hasattr(best, 'to_dict') else best, timeout=300)
            
            return best
        
        return primary_route
    
    def get_cached_route(self, start: Tuple[float, float],
                          destination: Tuple[float, float]) -> Optional[RouteRecommendation]:
        """
        Get cached route if available and still valid
        """
        cache_key = f"route_{start[0]:.3f}_{start[1]:.3f}_{destination[0]:.3f}_{destination[1]:.3f}"
        
        # Check memory cache
        if cache_key in self.cached_routes:
            return self.cached_routes[cache_key]
        
        # Check Redis cache
        cached = cache.get(cache_key)
        if cached:
            # Convert dict back to RouteRecommendation
            route = RouteRecommendation(**cached)
            self.cached_routes[cache_key] = route
            return route
        
        return None
    
    def estimate_arrival_time(self, route: RouteRecommendation, 
                                current_speed_kmh: float = None) -> datetime:
        """
        Estimate arrival time based on route and current speed
        """
        if current_speed_kmh and current_speed_kmh > 0:
            # Use current speed if provided
            speed = current_speed_kmh
        else:
            # Use predicted speed based on congestion
            speed = self.predictor._get_speed_from_congestion(route.congestion_level)
        
        duration_seconds = (route.total_distance_km / speed) * 3600 if speed > 0 else route.estimated_duration_seconds
        
        return datetime.utcnow() + timedelta(seconds=duration_seconds)
    
    def get_eta_with_traffic(self, start: Tuple[float, float],
                              destination: Tuple[float, float],
                              current_speed: float = None) -> Dict:
        """
        Get ETA considering real-time traffic conditions
        """
        route = self.find_best_route(start, destination)
        eta = self.estimate_arrival_time(route, current_speed)
        
        return {
            'estimated_arrival': eta.isoformat(),
            'minutes': round((eta - datetime.utcnow()).total_seconds() / 60, 1),
            'seconds': int((eta - datetime.utcnow()).total_seconds()),
            'distance_km': route.total_distance_km,
            'congestion_level': route.congestion_level,
            'confidence': route.confidence
        }


# ============================================
# TRAFFIC INTELLIGENCE SERVICE (Main)
# ============================================

class TrafficIntelligenceService:
    """
    Main Traffic Intelligence Service orchestrating all components
    """
    
    def __init__(self, app=None):
        self.app = app
        self.predictor = None
        self.optimizer = None
        self.analyzer = None
        self.route_optimizer = None
        self._is_initialized = False
        self._monitoring_thread = None
        self._is_running = False
        
        if app:
            self.init_service(app)
    
    def init_service(self, app):
        """Initialize traffic intelligence service"""
        self.app = app
        
        # Initialize components
        self.predictor = TrafficPredictor()
        self.optimizer = TrafficOptimizer(self.predictor)
        self.analyzer = CongestionAnalyzer(self.predictor)
        self.route_optimizer = RouteOptimizer(self.optimizer, self.predictor)
        
        self._is_initialized = True
        self._is_running = True
        
        # Start monitoring
        self._monitoring_thread = threading.Thread(target=self._monitor_traffic)
        self._monitoring_thread.daemon = True
        self._monitoring_thread.start()
        
        logger.info("Traffic Intelligence Service initialized successfully")
    
    def _monitor_traffic(self):
        """Background thread to monitor traffic conditions"""
        while self._is_running:
            try:
                # Update traffic predictions periodically
                # In production, would process real-time sensor data
                
                # Broadcast current congestion levels
                self._broadcast_congestion_update()
                
                import time
                time.sleep(60)  # Update every minute
                
            except Exception as e:
                logger.error(f"Traffic monitoring error: {e}")
                import time
                time.sleep(60)
    
    def _broadcast_congestion_update(self):
        """Broadcast congestion update via WebSocket"""
        # Simulate some data for demo
        congestion_data = {
            'overall_level': 'medium',
            'hotspots': 3,
            'timestamp': datetime.utcnow().isoformat()
        }
        socketio.emit('traffic_congestion_update', congestion_data, broadcast=True)
    
    def update_traffic_data(self, segment_id: str, vehicle_count: int,
                            average_speed: float, density: str) -> TrafficData:
        """
        Update real-time traffic data for a segment
        """
        traffic_data = TrafficData(
            segment_id=segment_id,
            vehicle_count=vehicle_count,
            average_speed=average_speed,
            density=density,
            timestamp=datetime.utcnow()
        )
        
        # Add to historical data for ML training
        if self.predictor:
            self.predictor.add_historical_data(segment_id, traffic_data)
        
        # Store in Redis for quick access
        if redis_client:
            redis_client.setex(
                f"traffic:{segment_id}",
                120,
                json.dumps(traffic_data.to_dict())
            )
        
        return traffic_data
    
    def predict_congestion(self, segment_id: str, minutes: int = 15) -> Optional[CongestionPrediction]:
        """Predict congestion for a segment"""
        if self.predictor:
            return self.predictor.predict_traffic(segment_id, minutes)
        return None
    
    def get_route_recommendation(self, start: Tuple[float, float],
                                   destination: Tuple[float, float],
                                   priority: int = 1) -> RouteRecommendation:
        """Get optimal route recommendation for emergency vehicle"""
        if self.route_optimizer:
            return self.route_optimizer.find_best_route(start, destination, priority)
        
        # Fallback simple route
        from geopy.distance import geodesic
        distance = geodesic(start, destination).kilometers
        return RouteRecommendation(
            route_id=f"simple_{datetime.utcnow().timestamp()}",
            waypoints=[start, destination],
            total_distance_km=round(distance, 2),
            estimated_duration_seconds=int((distance / 40) * 3600),
            congestion_level='medium',
            signal_count=int(distance * 2),
            confidence=0.7
        )
    
    def get_eta(self, start: Tuple[float, float],
                destination: Tuple[float, float],
                current_speed: float = None) -> Dict:
        """Get ETA considering current traffic"""
        if self.route_optimizer:
            return self.route_optimizer.get_eta_with_traffic(start, destination, current_speed)
        
        # Fallback simple ETA
        from geopy.distance import geodesic
        distance = geodesic(start, destination).kilometers
        speed = current_speed or 40
        eta_seconds = (distance / speed) * 3600
        
        return {
            'estimated_arrival': (datetime.utcnow() + timedelta(seconds=eta_seconds)).isoformat(),
            'minutes': round(eta_seconds / 60, 1),
            'seconds': int(eta_seconds),
            'distance_km': round(distance, 2),
            'congestion_level': 'medium',
            'confidence': 0.7
        }
    
    def analyze_congestion(self, traffic_data_list: List[TrafficData]) -> Dict:
        """Analyze congestion for a set of segments"""
        if self.analyzer:
            return self.analyzer.analyze_congestion_level(traffic_data_list)
        return {'level': 'unknown', 'avg_speed': 0, 'affected_segments': 0}
    
    def get_hotspots(self, traffic_data: Dict[str, TrafficData]) -> List[Dict]:
        """Get current traffic hotspots"""
        if self.analyzer:
            return self.analyzer.identify_hotspots(traffic_data)
        return []
    
    def optimize_signal(self, signal_id: int, traffic_data: TrafficData) -> Dict:
        """Optimize traffic signal timing"""
        if self.optimizer:
            return self.optimizer.optimize_signal_timing(signal_id, traffic_data)
        return {'signal_id': signal_id, 'optimized_timing': {'green': 30, 'yellow': 3, 'red': 30}}
    
    def get_stats(self) -> Dict:
        """Get service statistics"""
        return {
            'initialized': self._is_initialized,
            'predictor': self.predictor.get_stats() if self.predictor else None,
            'is_monitoring': self._is_running
        }
    
    def health_check(self) -> bool:
        """Check if service is healthy"""
        return self._is_initialized and self._is_running
    
    def shutdown(self):
        """Shutdown traffic intelligence service"""
        self._is_running = False
        if self.predictor:
            self.predictor.shutdown()
        if self._monitoring_thread:
            self._monitoring_thread.join(timeout=5)
        logger.info("Traffic Intelligence Service shut down")


# ============================================
# SERVICE FACTORY FUNCTIONS
# ============================================

_traffic_intel_service = None


def get_traffic_intel_service(app=None) -> TrafficIntelligenceService:
    """Get or create traffic intelligence service instance"""
    global _traffic_intel_service
    
    if _traffic_intel_service is None:
        _traffic_intel_service = TrafficIntelligenceService(app)
    
    return _traffic_intel_service


def shutdown_traffic_intel_service():
    """Shutdown traffic intelligence service"""
    global _traffic_intel_service
    if _traffic_intel_service:
        _traffic_intel_service.shutdown()
        _traffic_intel_service = None
        logger.info("Traffic intelligence service shut down")


# ============================================
# EXPORTS
# ============================================

__all__ = [
    'TrafficIntelligenceService',
    'TrafficPredictor',
    'TrafficOptimizer',
    'CongestionAnalyzer',
    'RouteOptimizer',
    'TrafficData',
    'CongestionPrediction',
    'RouteRecommendation',
    'get_traffic_intel_service',
    'shutdown_traffic_intel_service'
]