"""
Transaction Tracking Functions for GMX Safe Trading System
Handles logging and tracking of Safe transactions, positions, and signals
"""

import time
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from pymongo.errors import DuplicateKeyError
import logging

from .mongo_models import (
    SafeTransactionDocument, 
    TradingPositionDocument,
    TradingSignalDocument,
    TransactionStatus,
    PositionStatus,
    OrderType,
    mongo_manager
)

logger = logging.getLogger(__name__)

class TransactionTracker:
    """Tracks Safe transactions and trading activities"""
    
    def __init__(self):
        self.ensure_connected()
    
    def ensure_connected(self) -> bool:
        """Ensure MongoDB connection is active"""
        if mongo_manager.db is None:
            return mongo_manager.connect()
        return True
    
    def log_safe_transaction(
        self,
        safe_tx_hash: str,
        safe_address: str,
        chain_id: int = 42161,
        transaction_type: str = "gmx_order",
        status: TransactionStatus = TransactionStatus.PROPOSED,
        **kwargs
    ) -> bool:
        """Log a Safe multisig transaction"""
        try:
            if not self.ensure_connected():
                logger.error("Cannot connect to MongoDB")
                return False
            
            # Ensure transaction hash has 0x prefix for consistent storage
            normalized_hash = safe_tx_hash if safe_tx_hash.startswith('0x') else f"0x{safe_tx_hash}"
            
            # Create transaction document
            tx_doc = SafeTransactionDocument(
                safe_tx_hash=normalized_hash,
                safe_address=safe_address,
                chain_id=chain_id,
                transaction_type=transaction_type,
                status=status,
                **{k: v for k, v in kwargs.items() if hasattr(SafeTransactionDocument, k)}
            )
            
            # Insert into database
            collection = mongo_manager.get_collection('safe_transactions')
            collection.insert_one(tx_doc.to_dict())
            
            logger.info(f"📝 Logged Safe transaction: {safe_tx_hash[:10]}... ({status.value})")
            return True
            
        except DuplicateKeyError:
            logger.debug(f"Safe transaction already exists: {safe_tx_hash}")
            return self.update_safe_transaction(safe_tx_hash, status=status, **kwargs)
        except Exception as e:
            logger.error(f"❌ Failed to log Safe transaction: {e}")
            return False
    
    def update_safe_transaction(
        self,
        safe_tx_hash: str,
        status: Optional[TransactionStatus] = None,
        **kwargs
    ) -> bool:
        """Update an existing Safe transaction"""
        try:
            if not self.ensure_connected():
                return False
            
            # Ensure transaction hash has 0x prefix for consistent queries
            normalized_hash = safe_tx_hash if safe_tx_hash.startswith('0x') else f"0x{safe_tx_hash}"
            
            update_data = {
                'updated_timestamp': datetime.now(timezone.utc)
            }
            
            if status:
                update_data['status'] = status.value
            
            # Add any additional fields to update
            for key, value in kwargs.items():
                if hasattr(SafeTransactionDocument, key) and value is not None:
                    update_data[key] = value
            
            collection = mongo_manager.get_collection('safe_transactions')
            
            # Query with normalized hash (with 0x prefix)
            result = collection.update_one(
                {'safe_tx_hash': normalized_hash},
                {'$set': update_data}
            )
            
            if result.modified_count > 0:
                logger.info(f"✅ Updated Safe transaction: {normalized_hash[:10]}...")
                return True
            else:
                logger.warning(f"No Safe transaction found to update: {safe_tx_hash}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Failed to update Safe transaction: {e}")
            return False
    
    def log_trading_position(
        self,
        safe_address: str,
        token: str,
        market_key: str,
        is_long: bool,
        size_delta_usd: float,
        collateral_delta_usd: float,
        leverage: float,
        **kwargs
    ) -> Optional[str]:
        """Log a new trading position"""
        try:
            if not self.ensure_connected():
                return None
            
            # Generate unique position ID
            position_id = f"{safe_address[:8]}_{token}_{'LONG' if is_long else 'SHORT'}_{int(time.time())}"
            
            # Create position document
            position_doc = TradingPositionDocument(
                position_id=position_id,
                safe_address=safe_address,
                token=token,
                market_key=market_key,
                is_long=is_long,
                status=PositionStatus.PENDING,
                size_delta_usd=size_delta_usd,
                collateral_delta_usd=collateral_delta_usd,
                leverage=leverage,
                collateral_token=kwargs.get('collateral_token', 'USDC'),
                index_token=kwargs.get('index_token', token),
                **{k: v for k, v in kwargs.items() if hasattr(TradingPositionDocument, k)}
            )
            
            # Insert into database
            collection = mongo_manager.get_collection('trading_positions')
            collection.insert_one(position_doc.to_dict())
            
            logger.info(f"📊 Logged trading position: {position_id}")
            return position_id
            
        except Exception as e:
            logger.error(f"❌ Failed to log trading position: {e}")
            return None
    
    def update_position_status(
        self,
        position_id: str,
        status: PositionStatus,
        **kwargs
    ) -> bool:
        """Update position status and related data"""
        try:
            if not self.ensure_connected():
                return False
            
            update_data = {
                'status': status.value,
                'updated_timestamp': datetime.now(timezone.utc)
            }
            
            # Set timestamp based on status
            if status == PositionStatus.OPEN and 'opened_timestamp' not in kwargs:
                update_data['opened_timestamp'] = datetime.now(timezone.utc)
            elif status in [PositionStatus.CLOSED, PositionStatus.LIQUIDATED] and 'closed_timestamp' not in kwargs:
                update_data['closed_timestamp'] = datetime.now(timezone.utc)
            
            # Add additional update fields
            for key, value in kwargs.items():
                if hasattr(TradingPositionDocument, key) and value is not None:
                    update_data[key] = value
            
            collection = mongo_manager.get_collection('trading_positions')
            result = collection.update_one(
                {'position_id': position_id},
                {'$set': update_data}
            )
            
            if result.modified_count > 0:
                logger.info(f"✅ Updated position status: {position_id} -> {status.value}")
                return True
            else:
                logger.warning(f"No position found to update: {position_id}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Failed to update position status: {e}")
            return False
    
    def log_trading_signal(
        self,
        signal_id: str,
        username: str,
        signal_type: str,
        token: str,
        original_signal: Dict[str, Any],
        **kwargs
    ) -> bool:
        """Log an incoming trading signal"""
        try:
            if not self.ensure_connected():
                return False
            
            # Create signal document
            signal_doc = TradingSignalDocument(
                signal_id=signal_id,
                username=username,
                signal_type=signal_type,
                token=token,
                original_signal=original_signal,
                **{k: v for k, v in kwargs.items() if hasattr(TradingSignalDocument, k)}
            )
            
            # Insert into database
            collection = mongo_manager.get_collection('trading_signals')
            collection.insert_one(signal_doc.to_dict())
            
            logger.info(f"📡 Logged trading signal: {signal_id}")
            return True
            
        except DuplicateKeyError:
            logger.debug(f"Trading signal already exists: {signal_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to log trading signal: {e}")
            return False
    
    def update_signal_processing(
        self,
        signal_id: str,
        processed: bool = True,
        position_id: Optional[str] = None,
        safe_tx_hashes: Optional[List[str]] = None,
        processing_error: Optional[str] = None
    ) -> bool:
        """Update signal processing status"""
        try:
            if not self.ensure_connected():
                return False
            
            update_data = {
                'processed': processed,
                'processed_timestamp': datetime.now(timezone.utc)
            }
            
            if position_id:
                update_data['position_id'] = position_id
            if safe_tx_hashes:
                # Ensure all transaction hashes have 0x prefix
                normalized_hashes = [
                    tx_hash if tx_hash.startswith('0x') else f"0x{tx_hash}"
                    for tx_hash in safe_tx_hashes
                ]
                update_data['safe_tx_hashes'] = normalized_hashes
            if processing_error:
                update_data['processing_error'] = processing_error
            
            collection = mongo_manager.get_collection('trading_signals')
            result = collection.update_one(
                {'signal_id': signal_id},
                {'$set': update_data}
            )
            
            if result.modified_count > 0:
                logger.info(f"✅ Updated signal processing: {signal_id}")
                return True
            else:
                logger.warning(f"No signal found to update: {signal_id}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Failed to update signal processing: {e}")
            return False
    
    def get_safe_transaction(self, safe_tx_hash: str) -> Optional[Dict[str, Any]]:
        """Get Safe transaction by hash"""
        try:
            if not self.ensure_connected():
                return None
            
            # Ensure transaction hash has 0x prefix for consistent queries
            normalized_hash = safe_tx_hash if safe_tx_hash.startswith('0x') else f"0x{safe_tx_hash}"
            
            collection = mongo_manager.get_collection('safe_transactions')
            return collection.find_one({'safe_tx_hash': normalized_hash})
            
        except Exception as e:
            logger.error(f"❌ Failed to get Safe transaction: {e}")
            return None
    
    def get_trading_position(self, position_id: str) -> Optional[Dict[str, Any]]:
        """Get trading position by ID"""
        try:
            if not self.ensure_connected():
                return None
            
            collection = mongo_manager.get_collection('trading_positions')
            return collection.find_one({'position_id': position_id})
            
        except Exception as e:
            logger.error(f"❌ Failed to get trading position: {e}")
            return None
    
    def get_active_positions(self, safe_address: str) -> List[Dict[str, Any]]:
        """Get all active positions for a Safe address"""
        try:
            if not self.ensure_connected():
                return []
            
            collection = mongo_manager.get_collection('trading_positions')
            cursor = collection.find({
                'safe_address': safe_address,
                'status': {'$in': [PositionStatus.PENDING.value, PositionStatus.OPEN.value, PositionStatus.PARTIALLY_CLOSED.value]}
            }).sort('created_timestamp', -1)
            
            return list(cursor)
            
        except Exception as e:
            logger.error(f"❌ Failed to get active positions: {e}")
            return []
    
    def get_pending_transactions(self, safe_address: str) -> List[Dict[str, Any]]:
        """Get all pending Safe transactions for an address"""
        try:
            if not self.ensure_connected():
                return []
            
            collection = mongo_manager.get_collection('safe_transactions')
            cursor = collection.find({
                'safe_address': safe_address,
                'status': {'$in': [TransactionStatus.PROPOSED.value, TransactionStatus.CONFIRMED.value]}
            }).sort('created_timestamp', -1)
            
            return list(cursor)
            
        except Exception as e:
            logger.error(f"❌ Failed to get pending transactions: {e}")
            return []
    
    def get_trading_stats(self, safe_address: str, days: int = 30) -> Dict[str, Any]:
        """Get trading statistics for a Safe address"""
        try:
            if not self.ensure_connected():
                return {}
            
            from datetime import timedelta
            since_date = datetime.now(timezone.utc) - timedelta(days=days)
            
            # Aggregate statistics
            positions_collection = mongo_manager.get_collection('trading_positions')
            transactions_collection = mongo_manager.get_collection('safe_transactions')
            
            # Count positions by status
            position_stats = list(positions_collection.aggregate([
                {'$match': {
                    'safe_address': safe_address,
                    'created_timestamp': {'$gte': since_date}
                }},
                {'$group': {
                    '_id': '$status',
                    'count': {'$sum': 1},
                    'total_size': {'$sum': '$size_delta_usd'},
                    'avg_size': {'$avg': '$size_delta_usd'}
                }}
            ]))
            
            # Count transactions by type
            tx_stats = list(transactions_collection.aggregate([
                {'$match': {
                    'safe_address': safe_address,
                    'created_timestamp': {'$gte': since_date}
                }},
                {'$group': {
                    '_id': '$status',
                    'count': {'$sum': 1}
                }}
            ]))
            
            # Calculate PnL for closed positions
            pnl_stats = list(positions_collection.aggregate([
                {'$match': {
                    'safe_address': safe_address,
                    'status': PositionStatus.CLOSED.value,
                    'closed_timestamp': {'$gte': since_date},
                    'realized_pnl_usd': {'$exists': True, '$ne': None}
                }},
                {'$group': {
                    '_id': None,
                    'total_pnl': {'$sum': '$realized_pnl_usd'},
                    'avg_pnl': {'$avg': '$realized_pnl_usd'},
                    'winning_trades': {'$sum': {'$cond': [{'$gt': ['$realized_pnl_usd', 0]}, 1, 0]}},
                    'losing_trades': {'$sum': {'$cond': [{'$lt': ['$realized_pnl_usd', 0]}, 1, 0]}}
                }}
            ]))
            
            return {
                'period_days': days,
                'position_stats': {item['_id']: item for item in position_stats},
                'transaction_stats': {item['_id']: item for item in tx_stats},
                'pnl_stats': pnl_stats[0] if pnl_stats else {}
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to get trading stats: {e}")
            return {}

# Global transaction tracker instance
transaction_tracker = TransactionTracker()