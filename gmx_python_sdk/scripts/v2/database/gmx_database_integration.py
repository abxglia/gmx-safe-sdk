"""
GMX Database Integration
Enhances GMX Safe API with MongoDB transaction and position tracking
"""

import time
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from decimal import Decimal
import logging

from .transaction_tracker import transaction_tracker
from .mongo_models import (
    TransactionStatus, PositionStatus, OrderType,
    SafeTransactionDocument, TradingPositionDocument
)

logger = logging.getLogger(__name__)

class GMXDatabaseIntegration:
    """Database integration for GMX Safe trading operations"""
    
    @staticmethod
    def log_order_creation(
        safe_address: str,
        token: str,
        order_type: str,
        size_usd: float,
        leverage: int,
        is_long: bool = True,
        signal_id: Optional[str] = None,
        username: Optional[str] = None,
        take_profit_price: Optional[float] = None,
        stop_loss_price: Optional[float] = None,
        original_signal: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Optional[str]:
        """Log creation of a new GMX order/position"""
        try:
            # Generate position ID with microsecond precision to avoid duplicates
            position_id = f"{safe_address[:8]}_{token}_{'LONG' if is_long else 'SHORT'}_{int(time.time() * 1000000)}"
            
            # Extract market_key from kwargs to avoid duplicate parameter
            market_key = kwargs.pop('market_key', '')
            index_token = kwargs.pop('index_token', token)
            
            # Log trading position
            success = transaction_tracker.log_trading_position(
                safe_address=safe_address,
                token=token,
                market_key=market_key,
                is_long=is_long,
                size_delta_usd=size_usd,
                collateral_delta_usd=size_usd / leverage,
                leverage=leverage,
                take_profit_price=take_profit_price,
                stop_loss_price=stop_loss_price,
                signal_id=signal_id,
                username=username,
                original_signal=original_signal,
                index_token=index_token,
                **kwargs
            )
            
            if success:
                logger.info(f"📊 Position logged to database: {position_id}")
                return position_id
            return None
            
        except Exception as e:
            logger.error(f"❌ Failed to log order creation: {e}")
            return None
    
    @staticmethod
    def log_safe_transaction_from_order(
        safe_tx_hash: str,
        safe_address: str,
        order_type: Any,
        token: str,
        position_id: Optional[str] = None,
        signal_id: Optional[str] = None,
        username: Optional[str] = None,
        **kwargs
    ) -> bool:
        """Log Safe transaction created from GMX order"""
        try:
            # Normalize order_type to Enum if provided as string
            try:
                if isinstance(order_type, str):
                    order_type = OrderType(order_type)
            except Exception:
                logger.warning(f"Unknown order_type value: {order_type} - storing as None")
                order_type = None
            return transaction_tracker.log_safe_transaction(
                safe_tx_hash=safe_tx_hash,
                safe_address=safe_address,
                chain_id=42161,  # Arbitrum
                transaction_type="gmx_order",
                status=TransactionStatus.PROPOSED,
                order_type=order_type,
                token=token,
                signal_id=signal_id,
                username=username,
                **kwargs
            )
            
        except Exception as e:
            logger.error(f"❌ Failed to log Safe transaction from order: {e}")
            return False
    
    @staticmethod
    def log_signal_processing(
        signal_data: Dict[str, Any],
        username: str = "api_user",
        api_endpoint: Optional[str] = None
    ) -> str:
        """Log processing of a trading signal"""
        try:
            # Generate signal ID if not provided
            signal_id = signal_data.get('signal_id', f"gmx_{int(time.time())}_{username}")
            
            # Extract signal information
            signal_type = signal_data.get('Signal Message', '').lower()
            token = signal_data.get('Token Mentioned', '').upper()
            current_price = signal_data.get('Current Price')
            tp1 = signal_data.get('TP1')
            tp2 = signal_data.get('TP2')
            sl = signal_data.get('SL')
            max_exit_time = signal_data.get('Max Exit Time')
            safe_address = signal_data.get('safeAddress')
            
            success = transaction_tracker.log_trading_signal(
                signal_id=signal_id,
                username=username,
                signal_type=signal_type,
                token=token,
                original_signal=signal_data,
                current_price=float(current_price) if current_price else None,
                take_profit_tp1=float(tp1) if tp1 else None,
                take_profit_tp2=float(tp2) if tp2 else None,
                stop_loss=float(sl) if sl else None,
                max_exit_time=max_exit_time,
                api_endpoint=api_endpoint,
                safe_address=safe_address
            )
            
            if success:
                logger.info(f"📡 Signal logged to database: {signal_id}")
                return signal_id
            return ""
            
        except Exception as e:
            logger.error(f"❌ Failed to log signal processing: {e}")
            return ""
    
    @staticmethod
    def update_position_from_execution(
        position_id: str,
        execution_result: Dict[str, Any],
        safe_tx_hash: Optional[str] = None
    ) -> bool:
        """Update position status based on execution result"""
        try:
            if execution_result.get('status') == 'success':
                # Position opened successfully
                update_data = {
                    'opened_timestamp': datetime.now(timezone.utc)
                }
                
                if safe_tx_hash:
                    # Ensure transaction hash has 0x prefix
                    normalized_hash = safe_tx_hash if safe_tx_hash.startswith('0x') else f"0x{safe_tx_hash}"
                    update_data['opening_tx_hash'] = normalized_hash
                
                # Extract price information if available
                if 'entry_price' in execution_result:
                    update_data['entry_price'] = execution_result['entry_price']
                
                return transaction_tracker.update_position_status(
                    position_id=position_id,
                    status=PositionStatus.OPEN,
                    **update_data
                )
            else:
                # Position failed to open
                return transaction_tracker.update_position_status(
                    position_id=position_id,
                    status=PositionStatus.PENDING  # Keep as pending for retry
                )
                
        except Exception as e:
            logger.error(f"❌ Failed to update position from execution: {e}")
            return False
    
    @staticmethod
    def close_position(
        position_id: str,
        size_closed_usd: Optional[float] = None,
        realized_pnl_usd: Optional[float] = None,
        closing_price: Optional[float] = None,
        safe_tx_hash: Optional[str] = None
    ) -> bool:
        """Close or partially close a position"""
        try:
            # Get current position
            position = transaction_tracker.get_trading_position(position_id)
            if not position:
                logger.error(f"Position not found: {position_id}")
                return False
            
            current_size = position.get('size_delta_usd', 0)
            
            # Determine if full or partial close
            if not size_closed_usd or size_closed_usd >= current_size:
                # Full close
                status = PositionStatus.CLOSED
                update_data = {
                    'closed_timestamp': datetime.now(timezone.utc),
                    'realized_pnl_usd': realized_pnl_usd,
                    'current_price': closing_price
                }
            else:
                # Partial close
                status = PositionStatus.PARTIALLY_CLOSED
                update_data = {
                    'size_delta_usd': current_size - size_closed_usd,
                    'realized_pnl_usd': realized_pnl_usd,
                    'current_price': closing_price
                }
            
            if safe_tx_hash:
                # Ensure transaction hash has 0x prefix
                normalized_hash = safe_tx_hash if safe_tx_hash.startswith('0x') else f"0x{safe_tx_hash}"
                closing_tx_hashes = position.get('closing_tx_hashes', [])
                closing_tx_hashes.append(normalized_hash)
                update_data['closing_tx_hashes'] = closing_tx_hashes
            
            return transaction_tracker.update_position_status(
                position_id=position_id,
                status=status,
                **update_data
            )
            
        except Exception as e:
            logger.error(f"❌ Failed to close position: {e}")
            return False
    
    @staticmethod
    def get_portfolio_summary(safe_address: str) -> Dict[str, Any]:
        """Get portfolio summary for a Safe address"""
        try:
            # Get active positions
            active_positions = transaction_tracker.get_active_positions(safe_address)
            
            # Get pending transactions
            pending_transactions = transaction_tracker.get_pending_transactions(safe_address)
            
            # Get trading stats (last 30 days)
            trading_stats = transaction_tracker.get_trading_stats(safe_address, days=30)
            
            # Calculate portfolio metrics
            total_position_value = sum(pos.get('size_delta_usd', 0) for pos in active_positions)
            total_collateral = sum(pos.get('collateral_delta_usd', 0) for pos in active_positions)
            
            # Group positions by token
            positions_by_token = {}
            for pos in active_positions:
                token = pos.get('token', '')
                if token not in positions_by_token:
                    positions_by_token[token] = []
                positions_by_token[token].append(pos)
            
            return {
                'safe_address': safe_address,
                'active_positions': {
                    'count': len(active_positions),
                    'total_value_usd': total_position_value,
                    'total_collateral_usd': total_collateral,
                    'by_token': positions_by_token
                },
                'pending_transactions': {
                    'count': len(pending_transactions),
                    'transactions': pending_transactions
                },
                'trading_stats_30d': trading_stats,
                'timestamp': datetime.now(timezone.utc).isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Failed to get portfolio summary: {e}")
            return {'error': str(e)}
    
    @staticmethod
    def search_positions(
        safe_address: str,
        token: Optional[str] = None,
        status: Optional[PositionStatus] = None,
        signal_id: Optional[str] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Search positions with filters"""
        try:
            if not transaction_tracker.ensure_connected():
                return []
            
            # Build query
            query = {'safe_address': safe_address}
            
            if token:
                query['token'] = token.upper()
            if status:
                query['status'] = status.value
            if signal_id:
                query['signal_id'] = signal_id
            
            collection = transaction_tracker.mongo_manager.get_collection('trading_positions')
            cursor = collection.find(query).sort('created_timestamp', -1).limit(limit)
            
            return list(cursor)
            
        except Exception as e:
            logger.error(f"❌ Failed to search positions: {e}")
            return []
    
    @staticmethod
    def get_signal_history(
        username: Optional[str] = None,
        processed: Optional[bool] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """Get signal processing history"""
        try:
            if not transaction_tracker.ensure_connected():
                return []
            
            # Build query
            query = {}
            if username:
                query['username'] = username
            if processed is not None:
                query['processed'] = processed
            
            collection = transaction_tracker.mongo_manager.get_collection('trading_signals')
            cursor = collection.find(query).sort('received_timestamp', -1).limit(limit)
            
            return list(cursor)
            
        except Exception as e:
            logger.error(f"❌ Failed to get signal history: {e}")
            return []

# Global integration instance
gmx_db = GMXDatabaseIntegration()