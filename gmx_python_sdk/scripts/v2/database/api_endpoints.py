"""
Database API Endpoints for GMX Safe Trading System
Provides REST endpoints for querying trading data and transaction history
"""

from flask import Flask, request, jsonify
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
import logging

from .transaction_tracker import transaction_tracker
from .gmx_database_integration import gmx_db
from .mongo_models import TransactionStatus, PositionStatus, OrderType

logger = logging.getLogger(__name__)

def add_database_routes(app: Flask):
    """Add database-related routes to Flask app"""
    
    @app.route('/db/health', methods=['GET'])
    def database_health():
        """Check database connection health"""
        try:
            connected = transaction_tracker.ensure_connected()
            
            # Get some basic stats
            if connected:
                collections_info = {}
                try:
                    db = transaction_tracker.mongo_manager.db
                    for collection_name in ['safe_transactions', 'trading_positions', 'trading_signals']:
                        count = db[collection_name].count_documents({})
                        collections_info[collection_name] = {'document_count': count}
                except Exception as e:
                    collections_info = {'error': str(e)}
            else:
                collections_info = {}
            
            return jsonify({
                'status': 'healthy' if connected else 'unhealthy',
                'database_connected': connected,
                'collections': collections_info,
                'timestamp': datetime.now(timezone.utc).isoformat()
            })
            
        except Exception as e:
            logger.error(f"Database health check failed: {e}")
            return jsonify({
                'status': 'unhealthy',
                'database_connected': False,
                'error': str(e),
                'timestamp': datetime.now(timezone.utc).isoformat()
            }), 500
    
    @app.route('/db/portfolio/<safe_address>', methods=['GET'])
    def get_portfolio(safe_address: str):
        """Get portfolio summary for a Safe address"""
        try:
            portfolio = gmx_db.get_portfolio_summary(safe_address)
            
            if 'error' in portfolio:
                return jsonify({
                    'status': 'error',
                    'error': portfolio['error']
                }), 500
            
            return jsonify({
                'status': 'success',
                'portfolio': portfolio
            })
            
        except Exception as e:
            logger.error(f"Failed to get portfolio: {e}")
            return jsonify({
                'status': 'error',
                'error': str(e)
            }), 500
    
    @app.route('/db/positions/<safe_address>', methods=['GET'])
    def get_positions_history(safe_address: str):
        """Get positions for a Safe address with optional filters"""
        try:
            # Get query parameters
            token = request.args.get('token')
            status = request.args.get('status')
            signal_id = request.args.get('signal_id') 
            limit = int(request.args.get('limit', 50))
            
            # Convert status string to enum
            status_enum = None
            if status:
                try:
                    status_enum = PositionStatus(status.lower())
                except ValueError:
                    return jsonify({
                        'status': 'error',
                        'error': f'Invalid status: {status}. Valid options: {[s.value for s in PositionStatus]}'
                    }), 400
            
            positions = gmx_db.search_positions(
                safe_address=safe_address,
                token=token,
                status=status_enum,
                signal_id=signal_id,
                limit=limit
            )
            
            return jsonify({
                'status': 'success',
                'positions': positions,
                'count': len(positions),
                'filters_applied': {
                    'safe_address': safe_address,
                    'token': token,
                    'status': status,
                    'signal_id': signal_id,
                    'limit': limit
                }
            })
            
        except Exception as e:
            logger.error(f"Failed to get positions: {e}")
            return jsonify({
                'status': 'error',
                'error': str(e)
            }), 500
    
    @app.route('/db/transactions/<safe_address>', methods=['GET'])
    def get_transaction_history(safe_address: str):
        """Get Safe transaction history for an address"""
        try:
            # Get query parameters
            status = request.args.get('status')
            transaction_type = request.args.get('type')
            token = request.args.get('token')
            limit = int(request.args.get('limit', 100))
            days = int(request.args.get('days', 30))
            
            if not transaction_tracker.ensure_connected():
                return jsonify({
                    'status': 'error',
                    'error': 'Database not connected'
                }), 500
            
            # Build query
            query = {'safe_address': safe_address}
            
            # Add date filter
            since_date = datetime.now(timezone.utc) - timedelta(days=days)
            query['created_timestamp'] = {'$gte': since_date}
            
            # Add optional filters
            if status:
                query['status'] = status.lower()
            if transaction_type:
                query['transaction_type'] = transaction_type
            if token:
                query['token'] = token.upper()
            
            collection = transaction_tracker.mongo_manager.get_collection('safe_transactions')
            cursor = collection.find(query).sort('created_timestamp', -1).limit(limit)
            transactions = list(cursor)
            
            return jsonify({
                'status': 'success',
                'transactions': transactions,
                'count': len(transactions),
                'filters_applied': {
                    'safe_address': safe_address,
                    'status': status,
                    'transaction_type': transaction_type,
                    'token': token,
                    'days': days,
                    'limit': limit
                }
            })
            
        except Exception as e:
            logger.error(f"Failed to get transaction history: {e}")
            return jsonify({
                'status': 'error',
                'error': str(e)
            }), 500
    
    @app.route('/db/signals', methods=['GET'])
    def get_signal_history():
        """Get trading signal history"""
        try:
            # Get query parameters
            username = request.args.get('username')
            processed = request.args.get('processed')
            limit = int(request.args.get('limit', 50))
            
            # Convert processed to boolean
            processed_bool = None
            if processed is not None:
                processed_bool = processed.lower() in ['true', '1', 'yes']
            
            signals = gmx_db.get_signal_history(
                username=username,
                processed=processed_bool,
                limit=limit
            )
            
            return jsonify({
                'status': 'success',
                'signals': signals,
                'count': len(signals),
                'filters_applied': {
                    'username': username,
                    'processed': processed,
                    'limit': limit
                }
            })
            
        except Exception as e:
            logger.error(f"Failed to get signal history: {e}")
            return jsonify({
                'status': 'error',
                'error': str(e)
            }), 500
    
    @app.route('/db/stats/<safe_address>', methods=['GET'])
    def get_trading_stats(safe_address: str):
        """Get detailed trading statistics for a Safe address"""
        try:
            days = int(request.args.get('days', 30))
            
            stats = transaction_tracker.get_trading_stats(safe_address, days=days)
            
            # Add additional metrics
            if not transaction_tracker.ensure_connected():
                return jsonify({
                    'status': 'error',
                    'error': 'Database not connected'
                }), 500
            
            # Get token distribution
            positions_collection = transaction_tracker.mongo_manager.get_collection('trading_positions')
            token_stats = list(positions_collection.aggregate([
                {'$match': {
                    'safe_address': safe_address,
                    'created_timestamp': {'$gte': datetime.now(timezone.utc) - timedelta(days=days)}
                }},
                {'$group': {
                    '_id': '$token',
                    'position_count': {'$sum': 1},
                    'total_size': {'$sum': '$size_delta_usd'},
                    'avg_leverage': {'$avg': '$leverage'},
                    'long_positions': {'$sum': {'$cond': ['$is_long', 1, 0]}},
                    'short_positions': {'$sum': {'$cond': [{'$not': '$is_long'}, 1, 0]}}
                }}
            ]))
            
            # Get hourly trading activity
            hourly_activity = list(positions_collection.aggregate([
                {'$match': {
                    'safe_address': safe_address,
                    'created_timestamp': {'$gte': datetime.now(timezone.utc) - timedelta(days=7)}  # Last 7 days
                }},
                {'$group': {
                    '_id': {'$hour': '$created_timestamp'},
                    'position_count': {'$sum': 1},
                    'total_size': {'$sum': '$size_delta_usd'}
                }},
                {'$sort': {'_id': 1}}
            ]))
            
            enhanced_stats = {
                **stats,
                'token_distribution': {item['_id']: item for item in token_stats},
                'hourly_activity': hourly_activity,
                'query_parameters': {
                    'safe_address': safe_address,
                    'days': days
                }
            }
            
            return jsonify({
                'status': 'success',
                'stats': enhanced_stats
            })
            
        except Exception as e:
            logger.error(f"Failed to get trading stats: {e}")
            return jsonify({
                'status': 'error',
                'error': str(e)
            }), 500
    
    @app.route('/db/position/<position_id>', methods=['GET'])
    def get_position_details(position_id: str):
        """Get detailed information for a specific position"""
        try:
            position = transaction_tracker.get_trading_position(position_id)
            
            if not position:
                return jsonify({
                    'status': 'error',
                    'error': f'Position not found: {position_id}'
                }), 404
            
            # Get related transactions
            related_transactions = []
            if not transaction_tracker.ensure_connected():
                return jsonify({
                    'status': 'error',
                    'error': 'Database not connected'
                }), 500
            
            collection = transaction_tracker.mongo_manager.get_collection('safe_transactions')
            
            # Find transactions related to this position
            tx_hashes = []
            if position.get('opening_tx_hash'):
                tx_hashes.append(position['opening_tx_hash'])
            if position.get('closing_tx_hashes'):
                tx_hashes.extend(position['closing_tx_hashes'])
            if position.get('tp_order_tx_hash'):
                tx_hashes.append(position['tp_order_tx_hash'])
            if position.get('sl_order_tx_hash'):
                tx_hashes.append(position['sl_order_tx_hash'])
            
            if tx_hashes:
                cursor = collection.find({'safe_tx_hash': {'$in': tx_hashes}})
                related_transactions = list(cursor)
            
            return jsonify({
                'status': 'success',
                'position': position,
                'related_transactions': related_transactions
            })
            
        except Exception as e:
            logger.error(f"Failed to get position details: {e}")
            return jsonify({
                'status': 'error',
                'error': str(e)
            }), 500
    
    @app.route('/db/export/<safe_address>', methods=['GET'])
    def export_trading_data(safe_address: str):
        """Export all trading data for a Safe address"""
        try:
            days = int(request.args.get('days', 90))
            format_type = request.args.get('format', 'json')  # json or csv
            
            if format_type not in ['json', 'csv']:
                return jsonify({
                    'status': 'error',
                    'error': 'Invalid format. Use json or csv'
                }), 400
            
            since_date = datetime.now(timezone.utc) - timedelta(days=days)
            
            if not transaction_tracker.ensure_connected():
                return jsonify({
                    'status': 'error',
                    'error': 'Database not connected'
                }), 500
            
            # Get all data
            db = transaction_tracker.mongo_manager.db
            
            # Positions
            positions = list(db.trading_positions.find({
                'safe_address': safe_address,
                'created_timestamp': {'$gte': since_date}
            }).sort('created_timestamp', -1))
            
            # Transactions
            transactions = list(db.safe_transactions.find({
                'safe_address': safe_address,
                'created_timestamp': {'$gte': since_date}
            }).sort('created_timestamp', -1))
            
            # Signals
            signals = list(db.trading_signals.find({
                'safe_address': safe_address,
                'received_timestamp': {'$gte': since_date}
            }).sort('received_timestamp', -1))
            
            export_data = {
                'export_info': {
                    'safe_address': safe_address,
                    'period_days': days,
                    'export_timestamp': datetime.now(timezone.utc).isoformat(),
                    'counts': {
                        'positions': len(positions),
                        'transactions': len(transactions),
                        'signals': len(signals)
                    }
                },
                'positions': positions,
                'transactions': transactions,
                'signals': signals
            }
            
            if format_type == 'json':
                return jsonify({
                    'status': 'success',
                    'data': export_data
                })
            else:
                # CSV export would need additional formatting
                return jsonify({
                    'status': 'error',
                    'error': 'CSV export not yet implemented'
                }), 501
            
        except Exception as e:
            logger.error(f"Failed to export trading data: {e}")
            return jsonify({
                'status': 'error',
                'error': str(e)
            }), 500

def setup_database_monitoring():
    """Setup database monitoring and cleanup tasks"""
    # This could include periodic cleanup of old data,
    # database health monitoring, etc.
    pass