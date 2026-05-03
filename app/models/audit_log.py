"""
Smart Emergency Vehicle Priority System - Blockchain Audit Log Model
This file defines the AuditLog model for creating immutable records of
all critical operations using blockchain technology for transparency and security
"""

from datetime import datetime, timedelta
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Enum, Float, JSON, ForeignKey, Text, BigInteger
from sqlalchemy.orm import relationship
import enum
import uuid
import json
import hashlib
from loguru import logger

from app.extensions import db

# ============================================
# ENUMS (Choices for audit fields)
# ============================================

class AuditAction(enum.Enum):
    """Types of actions that get logged"""
    # User Actions
    USER_LOGIN = "user_login"
    USER_LOGOUT = "user_logout"
    USER_REGISTER = "user_register"
    USER_UPDATE = "user_update"
    USER_DELETE = "user_delete"
    
    # Vehicle Actions
    VEHICLE_REGISTER = "vehicle_register"
    VEHICLE_UPDATE = "vehicle_update"
    VEHICLE_DELETE = "vehicle_delete"
    VEHICLE_LOCATION_UPDATE = "vehicle_location_update"
    VEHICLE_STATUS_CHANGE = "vehicle_status_change"
    VEHICLE_DISPATCH = "vehicle_dispatch"
    
    # Corridor Actions
    CORRIDOR_REQUEST = "corridor_request"
    CORRIDOR_APPROVE = "corridor_approve"
    CORRIDOR_ACTIVATE = "corridor_activate"
    CORRIDOR_COMPLETE = "corridor_complete"
    CORRIDOR_CANCEL = "corridor_cancel"
    CORRIDOR_EXPIRE = "corridor_expire"
    
    # Signal Actions
    SIGNAL_CONTROL = "signal_control"
    SIGNAL_GREEN_CORRIDOR = "signal_green_corridor"
    SIGNAL_MANUAL_OVERRIDE = "signal_manual_override"
    SIGNAL_MAINTENANCE = "signal_maintenance"
    
    # Incident Actions
    INCIDENT_REPORT = "incident_report"
    INCIDENT_UPDATE = "incident_update"
    INCIDENT_RESOLVE = "incident_resolve"
    INCIDENT_CANCEL = "incident_cancel"
    
    # Admin Actions
    ADMIN_ACTION = "admin_action"
    SYSTEM_CONFIG_CHANGE = "system_config_change"
    DATABASE_BACKUP = "database_backup"
    
    # Blockchain Actions
    BLOCKCHAIN_SYNC = "blockchain_sync"
    BLOCKCHAIN_VERIFY = "blockchain_verify"

class AuditSeverity(enum.Enum):
    """Severity level of the audit event"""
    INFO = "info"           # Informational only
    WARNING = "warning"     # Warning - unusual but not critical
    CRITICAL = "critical"   # Critical security event
    ERROR = "error"         # Error occurred

class AuditStatus(enum.Enum):
    """Status of blockchain verification"""
    PENDING = "pending"         # Not yet sent to blockchain
    CONFIRMING = "confirming"   # Sent, waiting for confirmation
    CONFIRMED = "confirmed"     # Confirmed on blockchain
    FAILED = "failed"           # Failed to record on blockchain
    VERIFIED = "verified"       # Verified on blockchain
    TAMPERED = "tampered"       # Data tampering detected

# ============================================
# AUDIT LOG MODEL (Main audit trail)
# ============================================

class AuditLog(db.Model):
    """
    Audit Log model for recording all critical operations
    Each record gets a blockchain hash for immutability
    """
    __tablename__ = 'audit_logs'
    __table_args__ = (
        db.Index('idx_audit_timestamp', 'timestamp'),
        db.Index('idx_audit_action', 'action'),
        db.Index('idx_audit_user', 'user_id'),
        db.Index('idx_audit_entity', 'entity_type', 'entity_id'),
        db.Index('idx_audit_blockchain', 'blockchain_tx_hash'),
        db.Index('idx_audit_status', 'blockchain_status'),
        {'schema': 'public'}
    )

    # ============================================
    # BASIC IDENTIFICATION
    # ============================================
    id = Column(Integer, primary_key=True)
    audit_uuid = Column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    action = Column(Enum(AuditAction), nullable=False)
    severity = Column(Enum(AuditSeverity), default=AuditSeverity.INFO)
    
    # ============================================
    # USER INFORMATION
    # ============================================
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)
    user_email = Column(String(255), nullable=True)
    user_role = Column(String(50), nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    
    # ============================================
    # ENTITY INFORMATION (What was affected)
    # ============================================
    entity_type = Column(String(100), nullable=True)  # 'user', 'vehicle', 'signal', 'corridor', 'incident'
    entity_id = Column(Integer, nullable=True)
    entity_name = Column(String(255), nullable=True)
    
    # ============================================
    # ACTION DETAILS
    # ============================================
    action_details = Column(JSON, nullable=True)  # Detailed JSON of what changed
    old_value = Column(Text, nullable=True)      # Previous state (for updates)
    new_value = Column(Text, nullable=True)      # New state (for updates)
    
    # ============================================
    # REQUEST INFORMATION
    # ============================================
    request_method = Column(String(10), nullable=True)  # GET, POST, PUT, DELETE
    request_path = Column(String(500), nullable=True)
    request_params = Column(JSON, nullable=True)
    response_status = Column(Integer, nullable=True)
    response_time_ms = Column(Integer, nullable=True)
    
    # ============================================
    # BLOCKCHAIN INTEGRATION (IMMUTABILITY)
    # ============================================
    # SHA-256 hash of the record (for verification)
    record_hash = Column(String(64), unique=True, nullable=False)
    
    # Previous record hash (for chain linking)
    previous_hash = Column(String(64), nullable=True)
    
    # Blockchain transaction details
    blockchain_tx_hash = Column(String(66), nullable=True)  # Ethereum transaction hash (0x...)
    blockchain_block_number = Column(BigInteger, nullable=True)
    blockchain_block_hash = Column(String(66), nullable=True)
    blockchain_contract_address = Column(String(42), nullable=True)
    blockchain_status = Column(Enum(AuditStatus), default=AuditStatus.PENDING)
    blockchain_timestamp = Column(DateTime, nullable=True)
    blockchain_confirmations = Column(Integer, default=0)
    
    # ============================================
    # VERIFICATION
    # ============================================
    verified_at = Column(DateTime, nullable=True)
    verified_by = Column(String(255), nullable=True)  # 'system' or 'admin'
    verification_result = Column(Boolean, default=False)
    tamper_evidence = Column(JSON, nullable=True)
    
    # ============================================
    # METADATA
    # ============================================
    timestamp = Column(DateTime, default=datetime.utcnow, nullable=False)
    notes = Column(Text, nullable=True)
    metadata = Column(JSON, default={})
    
    # ============================================
    # RELATIONSHIPS
    # ============================================
    user = relationship("User", foreign_keys=[user_id])
    
    # ============================================
    # INITIALIZER AND HASH GENERATION
    # ============================================
    
    def __init__(self, action, **kwargs):
        self.action = action
        self.audit_uuid = str(uuid.uuid4())
        
        for key, value in kwargs.items():
            setattr(self, key, value)
        
        # Generate hash after setting all attributes
        self.record_hash = self._generate_hash()
    
    def _generate_hash(self):
        """
        Generate SHA-256 hash of the record data
        This hash ensures immutability - any change will change the hash
        """
        # Create a dictionary of all relevant fields
        hash_data = {
            'audit_uuid': self.audit_uuid,
            'action': self.action.value if self.action else None,
            'user_id': self.user_id,
            'user_email': self.user_email,
            'entity_type': self.entity_type,
            'entity_id': self.entity_id,
            'action_details': self.action_details,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'ip_address': self.ip_address,
            'previous_hash': self.previous_hash
        }
        
        # Convert to JSON string and hash
        json_string = json.dumps(hash_data, sort_keys=True, default=str)
        return hashlib.sha256(json_string.encode()).hexdigest()
    
    def _get_chain_link_data(self):
        """Get data for linking with previous record"""
        return {
            'id': self.id,
            'hash': self.record_hash,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'action': self.action.value if self.action else None,
            'user_id': self.user_id,
            'entity_type': self.entity_type,
            'entity_id': self.entity_id
        }
    
    # ============================================
    # BLOCKCHAIN INTEGRATION METHODS
    # ============================================
    
    def record_on_blockchain(self, web3_client=None, contract=None):
        """
        Record this audit log on the blockchain
        This makes the record truly immutable
        """
        try:
            from app.extensions import get_redis
            
            # Prepare data for blockchain
            blockchain_data = {
                'audit_uuid': self.audit_uuid,
                'record_hash': self.record_hash,
                'action': self.action.value if self.action else None,
                'user_id': self.user_id,
                'user_email': self.user_email,
                'entity_type': self.entity_type,
                'entity_id': self.entity_id,
                'timestamp': self.timestamp.isoformat(),
                'previous_hash': self.previous_hash
            }
            
            # In production, this would call a smart contract
            # For now, we simulate blockchain recording
            if web3_client and contract:
                # Actual blockchain transaction
                tx_hash = contract.functions.recordAuditLog(
                    self.audit_uuid,
                    self.record_hash,
                    json.dumps(blockchain_data)
                ).transact({'from': web3_client.eth.default_account})
                
                self.blockchain_tx_hash = tx_hash.hex()
                self.blockchain_status = AuditStatus.CONFIRMING
            else:
                # Simulated blockchain (for development)
                simulated_hash = hashlib.sha256(
                    json.dumps(blockchain_data, sort_keys=True).encode()
                ).hexdigest()
                self.blockchain_tx_hash = f"0x{simulated_hash}"
                self.blockchain_status = AuditStatus.CONFIRMED
                self.blockchain_timestamp = datetime.utcnow()
            
            db.session.commit()
            logger.info(f"Audit log {self.id} recorded on blockchain: {self.blockchain_tx_hash}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to record audit log on blockchain: {e}")
            self.blockchain_status = AuditStatus.FAILED
            db.session.commit()
            return False
    
    def verify_blockchain_record(self, web3_client=None, contract=None):
        """
        Verify that this record exists on blockchain and hasn't been tampered
        """
        if not self.blockchain_tx_hash:
            return {'verified': False, 'reason': 'No blockchain transaction hash'}
        
        try:
            if web3_client and contract:
                # Verify with actual blockchain
                # This would call the smart contract to verify
                is_verified = True  # Placeholder
                pass
            else:
                # Simulated verification
                # Recalculate hash and compare
                current_hash = self._generate_hash()
                is_verified = (current_hash == self.record_hash)
            
            self.verified_at = datetime.utcnow()
            self.verification_result = is_verified
            self.blockchain_status = AuditStatus.VERIFIED if is_verified else AuditStatus.TAMPERED
            
            if not is_verified:
                self.tamper_evidence = {
                    'expected_hash': self.record_hash,
                    'calculated_hash': current_hash,
                    'detected_at': datetime.utcnow().isoformat()
                }
            
            db.session.commit()
            
            return {
                'verified': is_verified,
                'record_hash': self.record_hash,
                'current_hash': current_hash,
                'blockchain_tx': self.blockchain_tx_hash
            }
            
        except Exception as e:
            logger.error(f"Blockchain verification failed: {e}")
            return {'verified': False, 'reason': str(e)}
    
    # ============================================
    # VERIFICATION METHODS
    # ============================================
    
    def verify_integrity(self):
        """
        Verify that the record hasn't been tampered with
        (Local verification without blockchain)
        """
        current_hash = self._generate_hash()
        is_valid = (current_hash == self.record_hash)
        
        if not is_valid:
            logger.warning(f"Audit log {self.id} has been tampered!")
            self.blockchain_status = AuditStatus.TAMPERED
            self.tamper_evidence = {
                'expected_hash': self.record_hash,
                'calculated_hash': current_hash,
                'detected_at': datetime.utcnow().isoformat()
            }
            db.session.commit()
        
        return is_valid
    
    @staticmethod
    def verify_chain(start_id=None, end_id=None):
        """
        Verify the entire chain of audit logs for tampering
        Returns list of tampered records
        """
        query = AuditLog.query.order_by(AuditLog.id.asc())
        
        if start_id:
            query = query.filter(AuditLog.id >= start_id)
        if end_id:
            query = query.filter(AuditLog.id <= end_id)
        
        logs = query.all()
        tampered = []
        
        for i, log in enumerate(logs):
            if not log.verify_integrity():
                tampered.append({
                    'id': log.id,
                    'audit_uuid': log.audit_uuid,
                    'timestamp': log.timestamp.isoformat(),
                    'action': log.action.value if log.action else None
                })
            
            # Verify chain link (previous hash should match previous record)
            if i > 0:
                prev_log = logs[i-1]
                expected_prev_hash = prev_log.record_hash
                if log.previous_hash != expected_prev_hash:
                    tampered.append({
                        'id': log.id,
                        'issue': 'broken_chain_link',
                        'expected_previous_hash': expected_prev_hash,
                        'actual_previous_hash': log.previous_hash
                    })
        
        return tampered
    
    # ============================================
    # SERIALIZATION
    # ============================================
    
    def to_dict(self, include_blockchain=False):
        """Convert audit log to dictionary"""
        log_dict = {
            'id': self.id,
            'audit_uuid': self.audit_uuid,
            'action': self.action.value if self.action else None,
            'severity': self.severity.value if self.severity else None,
            
            'user': {
                'user_id': self.user_id,
                'user_email': self.user_email,
                'user_role': self.user_role,
                'ip_address': self.ip_address
            },
            
            'entity': {
                'type': self.entity_type,
                'id': self.entity_id,
                'name': self.entity_name
            },
            
            'details': self.action_details,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            
            'integrity': {
                'record_hash': self.record_hash,
                'previous_hash': self.previous_hash,
                'is_verified': self.verification_result
            }
        }
        
        if include_blockchain:
            log_dict['blockchain'] = {
                'tx_hash': self.blockchain_tx_hash,
                'block_number': self.blockchain_block_number,
                'block_hash': self.blockchain_block_hash,
                'status': self.blockchain_status.value if self.blockchain_status else None,
                'confirmations': self.blockchain_confirmations,
                'timestamp': self.blockchain_timestamp.isoformat() if self.blockchain_timestamp else None
            }
        
        return log_dict
    
    def __repr__(self):
        return f"<AuditLog {self.id}: {self.action.value if self.action else 'Unknown'} by {self.user_email}>"


# ============================================
# BLOCKCHAIN VERIFICATION LOG
# ============================================

class BlockchainVerification(db.Model):
    """
    Track periodic blockchain verification runs
    """
    __tablename__ = 'blockchain_verifications'
    
    id = Column(Integer, primary_key=True)
    verification_uuid = Column(String(36), unique=True, nullable=False, default=lambda: str(uuid.uuid4()))
    start_time = Column(DateTime, default=datetime.utcnow)
    end_time = Column(DateTime, nullable=True)
    
    total_records_checked = Column(Integer, default=0)
    tampered_records_found = Column(Integer, default=0)
    broken_chains_found = Column(Integer, default=0)
    
    tampered_record_ids = Column(JSON, default=[])
    status = Column(String(50), default='in_progress')  # in_progress, completed, failed
    
    initiated_by = Column(Integer, ForeignKey('users.id'), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    
    initiated_by_user = relationship("User", foreign_keys=[initiated_by])
    
    def complete(self, tampered_records, broken_chains):
        """Mark verification as complete"""
        self.end_time = datetime.utcnow()
        self.tampered_records_found = len(tampered_records)
        self.broken_chains_found = len(broken_chains)
        self.tampered_record_ids = tampered_records
        self.status = 'completed'
        db.session.commit()
        logger.info(f"Blockchain verification completed: {self.tampered_records_found} tampered records found")
    
    def to_dict(self):
        return {
            'id': self.id,
            'verification_uuid': self.verification_uuid,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'end_time': self.end_time.isoformat() if self.end_time else None,
            'total_records_checked': self.total_records_checked,
            'tampered_records_found': self.tampered_records_found,
            'broken_chains_found': self.broken_chains_found,
            'status': self.status,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }


# ============================================
# HELPER FUNCTIONS
# ============================================

def create_audit_log(action, user_id=None, user_email=None, **kwargs):
    """
    Helper function to create an audit log entry
    Automatically links with previous log for chain
    """
    # Get the latest audit log for previous hash
    latest_log = AuditLog.query.order_by(AuditLog.id.desc()).first()
    previous_hash = latest_log.record_hash if latest_log else None
    
    audit_log = AuditLog(
        action=action,
        user_id=user_id,
        user_email=user_email,
        previous_hash=previous_hash,
        **kwargs
    )
    
    db.session.add(audit_log)
    db.session.commit()
    
    # Try to record on blockchain asynchronously
    # In production, use Celery for this
    # audit_log.record_on_blockchain()
    
    logger.info(f"Audit log created: {action.value if hasattr(action, 'value') else action}")
    return audit_log


def get_audit_logs(filters=None, limit=100, offset=0):
    """
    Get audit logs with filters
    """
    query = AuditLog.query
    
    if filters:
        if filters.get('action'):
            if isinstance(filters['action'], list):
                query = query.filter(AuditLog.action.in_(filters['action']))
            else:
                query = query.filter_by(action=filters['action'])
        
        if filters.get('user_id'):
            query = query.filter_by(user_id=filters['user_id'])
        
        if filters.get('entity_type'):
            query = query.filter_by(entity_type=filters['entity_type'])
        
        if filters.get('entity_id'):
            query = query.filter_by(entity_id=filters['entity_id'])
        
        if filters.get('severity'):
            query = query.filter_by(severity=filters['severity'])
        
        if filters.get('start_date'):
            query = query.filter(AuditLog.timestamp >= filters['start_date'])
        
        if filters.get('end_date'):
            query = query.filter(AuditLog.timestamp <= filters['end_date'])
    
    return query.order_by(AuditLog.timestamp.desc()).limit(limit).offset(offset).all()


def get_audit_statistics(days=30):
    """
    Get audit statistics for dashboard
    """
    from datetime import timedelta
    
    cutoff_date = datetime.utcnow() - timedelta(days=days)
    
    logs = AuditLog.query.filter(AuditLog.timestamp >= cutoff_date).all()
    
    stats = {
        'total_logs': len(logs),
        'by_action': {},
        'by_severity': {},
        'blockchain_stats': {
            'confirmed': 0,
            'pending': 0,
            'failed': 0,
            'verified': 0,
            'tampered': 0
        },
        'unique_users': len(set(log.user_id for log in logs if log.user_id)),
        'unique_entities': len(set((log.entity_type, log.entity_id) for log in logs if log.entity_type)),
        'most_active_user': None,
        'most_common_action': None
    }
    
    user_activity = {}
    action_count = {}
    
    for log in logs:
        # Count by action
        action_name = log.action.value if log.action else 'unknown'
        action_count[action_name] = action_count.get(action_name, 0) + 1
        
        # Count by severity
        severity_name = log.severity.value if log.severity else 'unknown'
        stats['by_severity'][severity_name] = stats['by_severity'].get(severity_name, 0) + 1
        
        # Count blockchain status
        if log.blockchain_status:
            status_name = log.blockchain_status.value
            stats['blockchain_stats'][status_name] = stats['blockchain_stats'].get(status_name, 0) + 1
        
        # User activity
        if log.user_id:
            user_activity[log.user_id] = user_activity.get(log.user_id, 0) + 1
    
    stats['by_action'] = action_count
    
    if action_count:
        stats['most_common_action'] = max(action_count, key=action_count.get)
    
    if user_activity:
        most_active_user_id = max(user_activity, key=user_activity.get)
        most_active_user = AuditLog.query.filter_by(user_id=most_active_user_id).first()
        if most_active_user:
            stats['most_active_user'] = {
                'user_id': most_active_user_id,
                'user_email': most_active_user.user_email,
                'action_count': user_activity[most_active_user_id]
            }
    
    return stats


def run_blockchain_verification():
    """
    Run full blockchain verification for all audit logs
    """
    verification = BlockchainVerification(
        total_records_checked=AuditLog.query.count()
    )
    db.session.add(verification)
    db.session.commit()
    
    tampered = AuditLog.verify_chain()
    broken_chains = [t for t in tampered if 'broken_chain_link' in t]
    tampered_records = [t for t in tampered if 'broken_chain_link' not in t]
    
    verification.complete(
        tampered_records=[t['id'] for t in tampered_records],
        broken_chains=broken_chains
    )
    
    if tampered:
        logger.warning(f"Found {len(tampered)} integrity issues during blockchain verification")
    
    return verification


# ============================================
# EXPORTS
# ============================================

__all__ = [
    'AuditLog',
    'AuditAction',
    'AuditSeverity',
    'AuditStatus',
    'BlockchainVerification',
    'create_audit_log',
    'get_audit_logs',
    'get_audit_statistics',
    'run_blockchain_verification'
]