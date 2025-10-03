"""
MongoDB Models for GMX Safe Trading System
Tracks Safe transactions, trading positions, and execution history
"""

import os
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from enum import Enum
from dataclasses import dataclass, field
from pymongo import MongoClient, IndexModel, ASCENDING, DESCENDING
import logging

logger = logging.getLogger(__name__)

class TransactionStatus(Enum):
    PROPOSED = "proposed"
    CONFIRMED = "confirmed"
    EXECUTED = "executed"
    FAILED = "failed"
    CANCELLED = "cancelled"

class PositionStatus(Enum):
    PENDING = "pending"
    OPEN = "open"
    CLOSED = "closed"
    PARTIALLY_CLOSED = "partially_closed"
    LIQUIDATED = "liquidated"
    FAILED = "failed"

class OrderType(Enum):
    MARKET_INCREASE = "market_increase"
    MARKET_DECREASE = "market_decrease"
    LIMIT_INCREASE = "limit_increase"
    LIMIT_DECREASE = "limit_decrease"
    STOP_LOSS = "stop_loss"
    TAKE_PROFIT = "take_profit"
    POSITION_WITH_TP_SL = "position_with_tp_sl"

@dataclass
class SafeTransactionDocument:
    """Document for tracking Safe multisig transactions"""
    safe_tx_hash: str
    safe_address: str
    chain_id: int
    transaction_type: str  # "gmx_order", "approval", "other"
    status: TransactionStatus
    
    # Transaction details
    to: Optional[str] = None
    value: str = "0"
    data: Optional[str] = None
    operation: int = 0
    gas_price: str = "0"
    gas_limit: Optional[str] = None
    nonce: Optional[int] = None
    
    # Execution details
    execution_tx_hash: Optional[str] = None
    execution_block_number: Optional[int] = None
    gas_used: Optional[str] = None
    execution_timestamp: Optional[datetime] = None
    
    # GMX-specific data
    gmx_order_key: Optional[str] = None
    order_type: Optional[OrderType] = None
    market_key: Optional[str] = None
    token: Optional[str] = None
    
    # Confirmations tracking
    confirmations_required: int = 1
    confirmations_count: int = 0
    signers: List[str] = field(default_factory=list)
    
    # Metadata
    created_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    updated_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str = "gmx_python_sdk"
    
    # Source info
    api_endpoint: Optional[str] = None
    signal_id: Optional[str] = None
    username: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to MongoDB document"""
        doc = {
            'safe_tx_hash': self.safe_tx_hash,
            'safe_address': self.safe_address,
            'chain_id': self.chain_id,
            'transaction_type': self.transaction_type,
            'status': self.status.value,
            'to': self.to,
            'value': self.value,
            'data': self.data,
            'operation': self.operation,
            'gas_price': self.gas_price,
            'gas_limit': self.gas_limit,
            'nonce': self.nonce,
            'execution_tx_hash': self.execution_tx_hash,
            'execution_block_number': self.execution_block_number,
            'gas_used': self.gas_used,
            'execution_timestamp': self.execution_timestamp,
            'gmx_order_key': self.gmx_order_key,
            'order_type': self.order_type.value if self.order_type else None,
            'market_key': self.market_key,
            'token': self.token,
            'confirmations_required': self.confirmations_required,
            'confirmations_count': self.confirmations_count,
            'signers': self.signers,
            'created_timestamp': self.created_timestamp,
            'updated_timestamp': self.updated_timestamp,
            'created_by': self.created_by,
            'api_endpoint': self.api_endpoint,
            'signal_id': self.signal_id,
            'username': self.username
        }
        return {k: v for k, v in doc.items() if v is not None}

@dataclass 
class TradingPositionDocument:
    """Document for tracking GMX trading positions"""
    position_id: str  # Unique identifier
    safe_address: str
    token: str
    market_key: str
    is_long: bool
    status: PositionStatus
    
    # Position details
    collateral_token: str
    index_token: str
    leverage: float
    size_delta_usd: float
    collateral_delta_usd: float
    
    # Price tracking
    entry_price: Optional[float] = None
    current_price: Optional[float] = None
    mark_price: Optional[float] = None
    liquidation_price: Optional[float] = None
    
    # PnL tracking
    unrealized_pnl_usd: Optional[float] = None
    realized_pnl_usd: Optional[float] = None
    total_pnl_usd: Optional[float] = None
    
    # TP/SL settings
    take_profit_price: Optional[float] = None
    stop_loss_price: Optional[float] = None
    max_exit_time: Optional[str] = None
    
    # Related transactions
    opening_tx_hash: Optional[str] = None
    closing_tx_hashes: List[str] = field(default_factory=list)
    tp_order_tx_hash: Optional[str] = None
    sl_order_tx_hash: Optional[str] = None
    
    # Timestamps
    created_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    opened_timestamp: Optional[datetime] = None
    closed_timestamp: Optional[datetime] = None
    updated_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    
    # Source info
    signal_id: Optional[str] = None
    username: Optional[str] = None
    api_endpoint: Optional[str] = None
    original_signal: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to MongoDB document"""
        doc = {
            'position_id': self.position_id,
            'safe_address': self.safe_address,
            'token': self.token,
            'market_key': self.market_key,
            'is_long': self.is_long,
            'status': self.status.value,
            'collateral_token': self.collateral_token,
            'index_token': self.index_token,
            'leverage': self.leverage,
            'size_delta_usd': self.size_delta_usd,
            'collateral_delta_usd': self.collateral_delta_usd,
            'entry_price': self.entry_price,
            'current_price': self.current_price,
            'mark_price': self.mark_price,
            'liquidation_price': self.liquidation_price,
            'unrealized_pnl_usd': self.unrealized_pnl_usd,
            'realized_pnl_usd': self.realized_pnl_usd,
            'total_pnl_usd': self.total_pnl_usd,
            'take_profit_price': self.take_profit_price,
            'stop_loss_price': self.stop_loss_price,
            'max_exit_time': self.max_exit_time,
            'opening_tx_hash': self.opening_tx_hash,
            'closing_tx_hashes': self.closing_tx_hashes,
            'tp_order_tx_hash': self.tp_order_tx_hash,
            'sl_order_tx_hash': self.sl_order_tx_hash,
            'created_timestamp': self.created_timestamp,
            'opened_timestamp': self.opened_timestamp,
            'closed_timestamp': self.closed_timestamp,
            'updated_timestamp': self.updated_timestamp,
            'signal_id': self.signal_id,
            'username': self.username,
            'api_endpoint': self.api_endpoint,
            'original_signal': self.original_signal
        }
        return {k: v for k, v in doc.items() if v is not None}

@dataclass
class TradingSignalDocument:
    """Document for tracking incoming trading signals"""
    signal_id: str
    username: str
    signal_type: str  # buy, sell, long, short
    token: str
    
    # Signal data
    original_signal: Dict[str, Any]
    current_price: Optional[float] = None
    take_profit_tp1: Optional[float] = None
    take_profit_tp2: Optional[float] = None
    stop_loss: Optional[float] = None
    max_exit_time: Optional[str] = None
    
    # Processing status
    processed: bool = False
    processed_timestamp: Optional[datetime] = None
    processing_error: Optional[str] = None
    
    # Related records
    safe_tx_hashes: List[str] = field(default_factory=list)
    position_id: Optional[str] = None
    
    # Metadata
    received_timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    api_endpoint: Optional[str] = None
    safe_address: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to MongoDB document"""
        return {
            'signal_id': self.signal_id,
            'username': self.username,
            'signal_type': self.signal_type,
            'token': self.token,
            'original_signal': self.original_signal,
            'current_price': self.current_price,
            'take_profit_tp1': self.take_profit_tp1,
            'take_profit_tp2': self.take_profit_tp2,
            'stop_loss': self.stop_loss,
            'max_exit_time': self.max_exit_time,
            'processed': self.processed,
            'processed_timestamp': self.processed_timestamp,
            'processing_error': self.processing_error,
            'safe_tx_hashes': self.safe_tx_hashes,
            'position_id': self.position_id,
            'received_timestamp': self.received_timestamp,
            'api_endpoint': self.api_endpoint,
            'safe_address': self.safe_address
        }

class MongoDBManager:
    """MongoDB connection and collection management"""
    
    def __init__(self, connection_string: Optional[str] = None, database_name: str = "gmx_safe_trading"):
        self.connection_string = connection_string or os.getenv('MONGODB_CONNECTION_STRING', 'mongodb://localhost:27017/')
        self.database_name = database_name
        self.client = None
        self.db = None
        
    def connect(self) -> bool:
        """Connect to MongoDB"""
        try:
            self.client = MongoClient(self.connection_string)
            self.db = self.client[self.database_name]
            
            # Test the connection
            self.client.admin.command('ping')
            logger.info(f"✅ Connected to MongoDB: {self.database_name}")
            
            # Create collections and indexes
            self._create_indexes()
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to connect to MongoDB: {e}")
            return False
    
    def _create_indexes(self):
        """Create indexes for optimal query performance"""
        try:
            # Safe Transactions collection indexes
            safe_tx_collection = self.db.safe_transactions
            safe_tx_collection.create_indexes([
                IndexModel([("safe_tx_hash", ASCENDING)], unique=True),
                IndexModel([("safe_address", ASCENDING)]),
                IndexModel([("status", ASCENDING)]),
                IndexModel([("transaction_type", ASCENDING)]),
                IndexModel([("created_timestamp", DESCENDING)]),
                IndexModel([("execution_timestamp", DESCENDING)]),
                IndexModel([("signal_id", ASCENDING)]),
                IndexModel([("token", ASCENDING)]),
                IndexModel([("safe_address", ASCENDING), ("status", ASCENDING)])
            ])
            
            # Trading Positions collection indexes
            positions_collection = self.db.trading_positions
            positions_collection.create_indexes([
                IndexModel([("position_id", ASCENDING)], unique=True),
                IndexModel([("safe_address", ASCENDING)]),
                IndexModel([("token", ASCENDING)]),
                IndexModel([("status", ASCENDING)]),
                IndexModel([("created_timestamp", DESCENDING)]),
                IndexModel([("signal_id", ASCENDING)]),
                IndexModel([("safe_address", ASCENDING), ("status", ASCENDING)]),
                IndexModel([("safe_address", ASCENDING), ("token", ASCENDING)])
            ])
            
            # Trading Signals collection indexes  
            signals_collection = self.db.trading_signals
            signals_collection.create_indexes([
                IndexModel([("signal_id", ASCENDING)], unique=True),
                IndexModel([("username", ASCENDING)]),
                IndexModel([("token", ASCENDING)]),
                IndexModel([("processed", ASCENDING)]),
                IndexModel([("received_timestamp", DESCENDING)]),
                IndexModel([("safe_address", ASCENDING)])
            ])
            
            logger.info("✅ MongoDB indexes created successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to create MongoDB indexes: {e}")
    
    def get_collection(self, collection_name: str):
        """Get a MongoDB collection"""
        if self.db is None:
            raise Exception("Not connected to MongoDB")
        return self.db[collection_name]
    
    def close(self):
        """Close MongoDB connection"""
        if self.client:
            self.client.close()
            logger.info("📴 MongoDB connection closed")

# Global MongoDB manager instance
mongo_manager = MongoDBManager()