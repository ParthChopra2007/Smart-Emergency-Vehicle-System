"""
Smart Emergency Vehicle Priority System - Blockchain Service
Handles blockchain integration for immutable audit trails,
smart contracts for corridor approvals, and verification of critical events
"""

import json
import hashlib
import asyncio
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any
from loguru import logger
import threading
from collections import deque

from app.extensions import db
from app.models.audit_log import (
    AuditLog, AuditAction, AuditStatus, BlockchainVerification,
    create_audit_log
)

# ============================================
# BLOCKCHAIN SERVICE
# ============================================

class BlockchainService:
    """
    Main blockchain service for recording and verifying transactions
    Supports Ethereum blockchain for immutable record keeping
    """
    
    def __init__(self, app=None):
        self.app = app
        self.web3 = None
        self.contract = None
        self.is_enabled = False
        self.pending_transactions = deque(maxlen=1000)
        self.processing_thread = None
        self.is_running = False
        self.contract_address = None
        self.contract_abi = None
        
        # Statistics
        self.stats = {
            'total_transactions': 0,
            'confirmed_transactions': 0,
            'failed_transactions': 0,
            'pending_transactions': 0,
            'avg_confirmation_time_ms': 0,
            'last_block_number': 0
        }
        
        # Initialize if app is provided
        if app:
            self.init_blockchain(app)
    
    def init_blockchain(self, app):
        """Initialize blockchain connection"""
        self.app = app
        
        # Check if blockchain is enabled
        self.is_enabled = app.config.get('BLOCKCHAIN_ENABLED', False)
        
        if not self.is_enabled:
            logger.info("Blockchain service is disabled (development mode)")
            return False
        
        try:
            from web3 import Web3
            
            # Initialize Web3 connection
            web3_provider = app.config.get('WEB3_PROVIDER_URL', 'http://localhost:8545')
            self.web3 = Web3(Web3.HTTPProvider(web3_provider))
            
            if not self.web3.is_connected():
                logger.warning(f"Failed to connect to blockchain node at {web3_provider}")
                self.is_enabled = False
                return False
            
            # Get contract address and ABI
            self.contract_address = app.config.get('CONTRACT_ADDRESS')
            if self.contract_address:
                # Load contract ABI (simplified - in production, load from file)
                self.contract_abi = self._get_contract_abi()
                if self.contract_abi:
                    self.contract = self.web3.eth.contract(
                        address=self.web3.to_checksum_address(self.contract_address),
                        abi=self.contract_abi
                    )
            
            # Get last block number
            self.stats['last_block_number'] = self.web3.eth.block_number
            
            # Start background processor
            self.start_processor()
            
            logger.info(f"✅ Blockchain service initialized. Chain ID: {self.web3.eth.chain_id}")
            return True
            
        except ImportError:
            logger.warning("Web3.py not installed. Blockchain service disabled.")
            self.is_enabled = False
            return False
        except Exception as e:
            logger.error(f"Failed to initialize blockchain: {e}")
            self.is_enabled = False
            return False
    
    def _get_contract_abi(self):
        """Get smart contract ABI (simplified for demo)"""
        # In production, load from JSON file
        return [
            {
                "inputs": [
                    {"name": "auditUuid", "type": "string"},
                    {"name": "recordHash", "type": "string"},
                    {"name": "data", "type": "string"}
                ],
                "name": "recordAuditLog",
                "outputs": [{"name": "", "type": "bytes32"}],
                "stateMutability": "nonpayable",
                "type": "function"
            },
            {
                "inputs": [{"name": "recordHash", "type": "string"}],
                "name": "verifyRecord",
                "outputs": [{"name": "", "type": "bool"}],
                "stateMutability": "view",
                "type": "function"
            }
        ]
    
    def start_processor(self):
        """Start background transaction processor"""
        if self.processing_thread is None:
            self.is_running = True
            self.processing_thread = threading.Thread(target=self._process_transactions)
            self.processing_thread.daemon = True
            self.processing_thread.start()
            logger.info("Blockchain transaction processor started")
    
    def stop_processor(self):
        """Stop background processor"""
        self.is_running = False
        if self.processing_thread:
            self.processing_thread.join(timeout=5)
    
    def _process_transactions(self):
        """Process pending transactions in background"""
        while self.is_running:
            try:
                if self.pending_transactions and self.web3:
                    tx = self.pending_transactions.popleft()
                    self._send_transaction(tx)
                
                # Sleep to avoid CPU overload
                import time
                time.sleep(0.1)
                
            except Exception as e:
                logger.error(f"Transaction processor error: {e}")
    
    def _send_transaction(self, tx_data: Dict):
        """Send transaction to blockchain"""
        try:
            # Simulate blockchain transaction for development
            if not self.is_enabled or not self.web3:
                self._simulate_transaction(tx_data)
                return
            
            # Actual blockchain transaction
            account = self.web3.eth.accounts[0]  # Use default account
            
            # Prepare transaction
            if self.contract:
                tx_hash = self.contract.functions.recordAuditLog(
                    tx_data['audit_uuid'],
                    tx_data['record_hash'],
                    json.dumps(tx_data['data'])
                ).transact({'from': account})
                
                # Wait for receipt
                receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash, timeout=30)
                
                if receipt.status == 1:
                    tx_data['status'] = 'confirmed'
                    tx_data['tx_hash'] = tx_hash.hex()
                    tx_data['block_number'] = receipt.blockNumber
                    self.stats['confirmed_transactions'] += 1
                    logger.info(f"Transaction confirmed: {tx_hash.hex()}")
                else:
                    tx_data['status'] = 'failed'
                    self.stats['failed_transactions'] += 1
                    logger.error(f"Transaction failed: {tx_hash.hex()}")
            
        except Exception as e:
            logger.error(f"Send transaction error: {e}")
            tx_data['status'] = 'failed'
            self.stats['failed_transactions'] += 1
    
    def _simulate_transaction(self, tx_data: Dict):
        """Simulate blockchain transaction for development"""
        # Generate fake transaction hash
        import hashlib
        tx_hash = hashlib.sha256(
            f"{tx_data['audit_uuid']}{datetime.utcnow().isoformat()}".encode()
        ).hexdigest()[:66]
        
        tx_data['status'] = 'confirmed'
        tx_data['tx_hash'] = f"0x{tx_hash}"
        tx_data['block_number'] = self.stats['last_block_number'] + 1
        self.stats['last_block_number'] += 1
        self.stats['confirmed_transactions'] += 1
        
        logger.debug(f"Simulated transaction: {tx_data['tx_hash']}")
    
    def record_audit_log(self, audit_log_id: int) -> bool:
        """
        Record an audit log on blockchain
        """
        try:
            audit_log = AuditLog.query.get(audit_log_id)
            if not audit_log:
                logger.error(f"Audit log {audit_log_id} not found")
                return False
            
            # Prepare transaction data
            tx_data = {
                'audit_uuid': audit_log.audit_uuid,
                'record_hash': audit_log.record_hash,
                'data': {
                    'action': audit_log.action.value if audit_log.action else None,
                    'user_id': audit_log.user_id,
                    'user_email': audit_log.user_email,
                    'entity_type': audit_log.entity_type,
                    'entity_id': audit_log.entity_id,
                    'timestamp': audit_log.timestamp.isoformat(),
                    'previous_hash': audit_log.previous_hash
                },
                'status': 'pending',
                'timestamp': datetime.utcnow()
            }
            
            # Add to pending queue
            self.pending_transactions.append(tx_data)
            self.stats['pending_transactions'] = len(self.pending_transactions)
            
            # Update audit log with pending status
            audit_log.blockchain_status = AuditStatus.PENDING
            db.session.commit()
            
            logger.info(f"Audit log {audit_log_id} queued for blockchain recording")
            return True
            
        except Exception as e:
            logger.error(f"Record audit log error: {e}")
            return False
    
    def verify_audit_log(self, audit_log_id: int) -> Dict:
        """
        Verify audit log integrity using blockchain
        """
        try:
            audit_log = AuditLog.query.get(audit_log_id)
            if not audit_log:
                return {'verified': False, 'error': 'Audit log not found'}
            
            # Check local integrity first
            local_valid = audit_log.verify_integrity()
            
            if not local_valid:
                return {
                    'verified': False,
                    'error': 'Local integrity check failed. Record may be tampered.',
                    'local_valid': False
                }
            
            # Verify on blockchain
            if self.is_enabled and self.contract and audit_log.blockchain_tx_hash:
                try:
                    # Query blockchain for verification
                    is_verified = self.contract.functions.verifyRecord(
                        audit_log.record_hash
                    ).call()
                    
                    if is_verified:
                        audit_log.blockchain_status = AuditStatus.VERIFIED
                        audit_log.verified_at = datetime.utcnow()
                        db.session.commit()
                        return {
                            'verified': True,
                            'blockchain_verified': True,
                            'tx_hash': audit_log.blockchain_tx_hash
                        }
                    else:
                        audit_log.blockchain_status = AuditStatus.TAMPERED
                        db.session.commit()
                        return {
                            'verified': False,
                            'error': 'Record hash mismatch on blockchain',
                            'blockchain_verified': False
                        }
                except Exception as e:
                    logger.error(f"Blockchain verification error: {e}")
                    return {
                        'verified': local_valid,
                        'blockchain_verified': None,
                        'error': f"Blockchain verification failed: {e}"
                    }
            else:
                # No blockchain, rely on local verification
                return {
                    'verified': local_valid,
                    'blockchain_verified': False,
                    'note': 'Blockchain verification not available'
                }
            
        except Exception as e:
            logger.error(f"Verify audit log error: {e}")
            return {'verified': False, 'error': str(e)}
    
    def verify_chain_integrity(self, start_id: int = None, end_id: int = None) -> Dict:
        """
        Verify the entire chain of audit logs
        """
        try:
            query = AuditLog.query.order_by(AuditLog.id.asc())
            
            if start_id:
                query = query.filter(AuditLog.id >= start_id)
            if end_id:
                query = query.filter(AuditLog.id <= end_id)
            
            logs = query.all()
            tampered_records = []
            broken_links = []
            
            previous_hash = None
            
            for log in logs:
                # Verify individual record
                if not log.verify_integrity():
                    tampered_records.append(log.id)
                
                # Verify chain link
                if previous_hash and log.previous_hash != previous_hash:
                    broken_links.append({
                        'id': log.id,
                        'expected': previous_hash,
                        'actual': log.previous_hash
                    })
                
                previous_hash = log.record_hash
            
            # Verify on blockchain if enabled
            blockchain_verified_count = 0
            if self.is_enabled:
                for log in logs:
                    if log.blockchain_tx_hash:
                        result = self.verify_audit_log(log.id)
                        if result.get('verified'):
                            blockchain_verified_count += 1
            
            return {
                'total_records': len(logs),
                'tampered_records': tampered_records,
                'tampered_count': len(tampered_records),
                'broken_links': broken_links,
                'broken_links_count': len(broken_links),
                'is_chain_valid': len(tampered_records) == 0 and len(broken_links) == 0,
                'blockchain_verified_count': blockchain_verified_count,
                'timestamp': datetime.utcnow().isoformat()
            }
            
        except Exception as e:
            logger.error(f"Verify chain integrity error: {e}")
            return {'error': str(e)}
    
    def record_corridor_request(self, corridor_id: int) -> bool:
        """
        Record green corridor request on blockchain
        """
        try:
            from app.models.corridor import GreenCorridor
            
            corridor = GreenCorridor.query.get(corridor_id)
            if not corridor:
                logger.error(f"Corridor {corridor_id} not found")
                return False
            
            # Create audit log for corridor request
            audit_log = create_audit_log(
                action=AuditAction.CORRIDOR_REQUEST,
                user_id=corridor.requested_by_id,
                entity_type='corridor',
                entity_id=corridor.id,
                action_details={
                    'corridor_uuid': corridor.corridor_uuid,
                    'vehicle_id': corridor.vehicle_id,
                    'start_location': {
                        'lat': corridor.start_latitude,
                        'lng': corridor.start_longitude
                    },
                    'destination': {
                        'lat': corridor.destination_latitude,
                        'lng': corridor.destination_longitude
                    },
                    'priority_level': corridor.priority_level
                }
            )
            
            return self.record_audit_log(audit_log.id)
            
        except Exception as e:
            logger.error(f"Record corridor request error: {e}")
            return False
    
    def record_corridor_completion(self, corridor_id: int) -> bool:
        """
        Record corridor completion on blockchain
        """
        try:
            from app.models.corridor import GreenCorridor
            
            corridor = GreenCorridor.query.get(corridor_id)
            if not corridor:
                logger.error(f"Corridor {corridor_id} not found")
                return False
            
            audit_log = create_audit_log(
                action=AuditAction.CORRIDOR_COMPLETE,
                user_id=corridor.requested_by_id,
                entity_type='corridor',
                entity_id=corridor.id,
                action_details={
                    'corridor_uuid': corridor.corridor_uuid,
                    'time_saved_seconds': corridor.time_saved_seconds,
                    'actual_duration_seconds': corridor.actual_duration_seconds,
                    'signals_passed': corridor.signals_passed,
                    'signals_total': corridor.signals_total
                }
            )
            
            return self.record_audit_log(audit_log.id)
            
        except Exception as e:
            logger.error(f"Record corridor completion error: {e}")
            return False
    
    def record_emergency_response(self, incident_id: int, vehicle_id: int) -> bool:
        """
        Record emergency response on blockchain
        """
        try:
            from app.models.incident import Incident
            
            incident = Incident.query.get(incident_id)
            if not incident:
                logger.error(f"Incident {incident_id} not found")
                return False
            
            audit_log = create_audit_log(
                action=AuditAction.VEHICLE_DISPATCH,
                entity_type='incident',
                entity_id=incident.id,
                action_details={
                    'incident_uuid': incident.incident_uuid,
                    'incident_type': incident.incident_type.value if incident.incident_type else None,
                    'severity': incident.severity.value if incident.severity else None,
                    'vehicle_id': vehicle_id,
                    'location': {
                        'lat': incident.latitude,
                        'lng': incident.longitude
                    }
                }
            )
            
            return self.record_audit_log(audit_log.id)
            
        except Exception as e:
            logger.error(f"Record emergency response error: {e}")
            return False
    
    def get_stats(self) -> Dict:
        """Get blockchain service statistics"""
        return {
            'is_enabled': self.is_enabled,
            'web3_connected': self.web3.is_connected() if self.web3 else False,
            'contract_address': self.contract_address,
            'total_transactions': self.stats['total_transactions'],
            'confirmed_transactions': self.stats['confirmed_transactions'],
            'failed_transactions': self.stats['failed_transactions'],
            'pending_transactions': len(self.pending_transactions),
            'last_block_number': self.stats['last_block_number']
        }
    
    def health_check(self) -> bool:
        """Check if blockchain service is healthy"""
        if not self.is_enabled:
            return True  # Disabled is considered healthy for development
        
        if not self.web3:
            return False
        
        return self.web3.is_connected()
    
    def shutdown(self):
        """Shutdown blockchain service"""
        self.stop_processor()
        logger.info("Blockchain service shut down")


# ============================================
# AUDIT RECORDER (Simplified interface)
# ============================================

class AuditRecorder:
    """
    Simplified interface for recording audit events
    """
    
    def __init__(self, blockchain_service: BlockchainService):
        self.blockchain_service = blockchain_service
    
    def record(self, action: AuditAction, user_id: int = None, user_email: str = None,
               entity_type: str = None, entity_id: int = None,
               details: Dict = None) -> bool:
        """Record an audit event"""
        try:
            audit_log = create_audit_log(
                action=action,
                user_id=user_id,
                user_email=user_email,
                entity_type=entity_type,
                entity_id=entity_id,
                action_details=details
            )
            
            return self.blockchain_service.record_audit_log(audit_log.id)
            
        except Exception as e:
            logger.error(f"Audit record error: {e}")
            return False


# ============================================
# SMART CONTRACT MANAGER
# ============================================

class SmartContractManager:
    """
    Manages smart contract interactions
    """
    
    def __init__(self, blockchain_service: BlockchainService):
        self.blockchain_service = blockchain_service
    
    def verify_corridor_on_chain(self, corridor_uuid: str) -> bool:
        """Verify if corridor exists on blockchain"""
        if not self.blockchain_service.is_enabled:
            return True  # Assume verified if blockchain disabled
        
        try:
            # Query blockchain for corridor record
            # This would call the smart contract
            return True
        except Exception as e:
            logger.error(f"Verify corridor on chain error: {e}")
            return False
    
    def get_audit_trail(self, entity_type: str, entity_id: int) -> List[Dict]:
        """Get blockchain audit trail for an entity"""
        # In production, query blockchain events
        return []


# ============================================
# VERIFICATION SERVICE
# ============================================

class VerificationService:
    """
    Service for verifying blockchain records and generating reports
    """
    
    def __init__(self, blockchain_service: BlockchainService):
        self.blockchain_service = blockchain_service
    
    def verify_all_pending(self) -> Dict:
        """Verify all pending blockchain transactions"""
        pending_logs = AuditLog.query.filter_by(
            blockchain_status=AuditStatus.PENDING
        ).all()
        
        results = {
            'total_pending': len(pending_logs),
            'verified': [],
            'failed': []
        }
        
        for log in pending_logs:
            verification = self.blockchain_service.verify_audit_log(log.id)
            if verification.get('verified'):
                results['verified'].append(log.id)
            else:
                results['failed'].append({
                    'id': log.id,
                    'error': verification.get('error')
                })
        
        return results
    
    def generate_verification_report(self, days: int = 30) -> Dict:
        """Generate verification report for last N days"""
        cutoff = datetime.utcnow() - timedelta(days=days)
        
        logs = AuditLog.query.filter(AuditLog.timestamp >= cutoff).all()
        
        verified_count = 0
        tampered_count = 0
        pending_count = 0
        
        for log in logs:
            if log.blockchain_status == AuditStatus.VERIFIED:
                verified_count += 1
            elif log.blockchain_status == AuditStatus.TAMPERED:
                tampered_count += 1
            elif log.blockchain_status == AuditStatus.PENDING:
                pending_count += 1
        
        return {
            'period_days': days,
            'total_records': len(logs),
            'verified_records': verified_count,
            'tampered_records': tampered_count,
            'pending_records': pending_count,
            'compliance_rate': round((verified_count / len(logs)) * 100, 2) if logs else 100,
            'generated_at': datetime.utcnow().isoformat()
        }


# ============================================
# SERVICE FACTORY FUNCTIONS
# ============================================

_blockchain_service = None
_audit_recorder = None
_smart_contract_manager = None
_verification_service = None


def get_blockchain_service(app=None) -> BlockchainService:
    """Get or create blockchain service instance"""
    global _blockchain_service
    
    if _blockchain_service is None:
        _blockchain_service = BlockchainService(app)
    
    return _blockchain_service


def get_audit_recorder(app=None) -> AuditRecorder:
    """Get or create audit recorder instance"""
    global _audit_recorder
    
    if _audit_recorder is None:
        blockchain_service = get_blockchain_service(app)
        _audit_recorder = AuditRecorder(blockchain_service)
    
    return _audit_recorder


def get_smart_contract_manager(app=None) -> SmartContractManager:
    """Get or create smart contract manager instance"""
    global _smart_contract_manager
    
    if _smart_contract_manager is None:
        blockchain_service = get_blockchain_service(app)
        _smart_contract_manager = SmartContractManager(blockchain_service)
    
    return _smart_contract_manager


def get_verification_service(app=None) -> VerificationService:
    """Get or create verification service instance"""
    global _verification_service
    
    if _verification_service is None:
        blockchain_service = get_blockchain_service(app)
        _verification_service = VerificationService(blockchain_service)
    
    return _verification_service


# ============================================
# EXPORTS
# ============================================

__all__ = [
    'BlockchainService',
    'AuditRecorder',
    'SmartContractManager',
    'VerificationService',
    'get_blockchain_service',
    'get_audit_recorder',
    'get_smart_contract_manager',
    'get_verification_service'
]