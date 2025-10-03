#!/usr/bin/env python3
"""
Enhanced GMX Safe API Server with MongoDB Database Integration
Tracks all Safe transactions, trading positions, and execution history
"""

from datetime import datetime
import logging
import os

from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS
from services.enhanced_gmx_api import EnhancedGMXAPI as EnhancedGMXAPIService

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
logger.info("🔧 Environment variables loaded from .env file")

app = Flask(__name__)
CORS(app)

# Initialize API instance
gmx_api = EnhancedGMXAPIService()

# Add all the original routes
@app.route('/', methods=['GET'])
def home_page():
    """Home page endpoint showing a welcome message"""
    return jsonify({
        'message': 'Welcome to the GMX Safe API',
        'status': 'ok',
        'timestamp': datetime.now().isoformat()
    })

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'GMX Safe API',
        'safe_address': gmx_api.safe_address,
        'initialized': gmx_api.initialized,
        'database_connected': gmx_api.db_connected,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/initialize', methods=['POST'])
def initialize():
    """Initialize the GMX API"""
    try:
        success = gmx_api.initialize()
        return jsonify({
            'status': 'success' if success else 'error',
            'message': 'GMX API initialized successfully' if success else 'Failed to initialize GMX API',
            'database_connected': gmx_api.db_connected,
            'timestamp': datetime.now().isoformat()
        }), 200 if success else 500
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/signal/process', methods=['POST'])
def process_signal():
    """Process a trading signal with database tracking"""
    try:
        signal_data = request.get_json()
        if not signal_data:
            return jsonify({
                'status': 'error',
                'error': 'No signal data provided'
            }), 400
        
        result = gmx_api.process_signal_with_database(signal_data)
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"❌ Error processing signal: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/buy', methods=['POST'])
def buy_position():
    """Execute a buy order"""
    try:
        data = request.get_json()
        token = data.get('token', 'BTC').upper()
        size_usd = float(data.get('size_usd', 2.1))
        leverage = int(data.get('leverage', 1))
        safe_address = data.get('safeAddress')
        auto_execute = data.get('autoExecute', False)  # New parameter for auto-execution
        
        # Initialize API with safe_address if provided
        if safe_address:
            if not gmx_api.initialized or gmx_api.safe_address != safe_address:
                logger.info(f"🔄 Re-initializing API with Safe address from request: {safe_address}")
                gmx_api.initialize(safe_address=safe_address)
        
        result = gmx_api.execute_buy_order(
            token=token, 
            size_usd=size_usd, 
            leverage=leverage,
            auto_execute=auto_execute
        )
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"❌ Error buying position: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/sell', methods=['POST'])
def sell_position():
    """Execute a sell order"""
    try:
        data = request.get_json()
        token = data.get('token', 'BTC').upper()
        size_usd = data.get('size_usd')  # None means close entire position
        safe_address = data.get('safeAddress')
        auto_execute = data.get('autoExecute', False)  # New parameter for auto-execution
        
        # Initialize API with safe_address if provided
        if safe_address:
            if not gmx_api.initialized or gmx_api.safe_address != safe_address:
                logger.info(f"🔄 Re-initializing API with Safe address from request: {safe_address}")
                gmx_api.initialize(safe_address=safe_address)
        
        result = gmx_api.execute_sell_order(
            token=token, 
            size_usd=size_usd,
            auto_execute=auto_execute
        )
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"❌ Error selling position: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/position/create-with-tp-sl', methods=['POST'])
def create_position_with_tp_sl():
    """Create a position with automatic Take Profit and Stop Loss orders from signal format
    
    New Sequential Flow (default):
    1. Execute pending approval transactions (if any)
    2. Create Buy order (handles approval automatically if needed)
    3. Create Take Profit order
    4. Create Stop Loss order
    
    Parameters:
    - sequentialExecution: True (default) for new flow, False for old batch flow
    - autoExecute: False (default) for manual execution, True for auto-execution
    """
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'status': 'error',
                'error': 'No data provided'
            }), 400
        
        # Check if this is the new signal format or direct API format
        if 'Signal Message' in data and 'Token Mentioned' in data:
            # New signal format - extract parameters
            signal_message = data.get('Signal Message', '').lower()
            token = data.get('Token Mentioned', '').upper()
            tp1 = data.get('TP1')
            tp2 = data.get('TP2')  # Optional, will log but use TP1
            sl = data.get('SL')
            current_price = data.get('Current Price')
            max_exit_time = data.get('Max Exit Time')
            username = data.get('username', 'api_user')
            safe_address = data.get('safeAddress')
            
            # Validate all required signal fields in a single check
            missing_fields = []
            if not safe_address:
                missing_fields.append('safeAddress')
            if not signal_message:
                missing_fields.append('Signal Message')
            if not token:
                missing_fields.append('Token Mentioned')
            if tp1 is None:
                missing_fields.append('TP1')
            if sl is None:
                missing_fields.append('SL')
            if missing_fields:
                return jsonify({
                    'status': 'error',
                    'error': f"Missing required field(s): {', '.join(missing_fields)}"
                }), 400
            
            # Convert to float and validate
            try:
                take_profit_price = float(tp1)
                stop_loss_price = float(sl)
                current_price_val = float(current_price) if current_price else None
                tp2_val = float(tp2) if tp2 else None
                
            except (ValueError, TypeError) as e:
                return jsonify({
                    'status': 'error',
                    'error': f'Invalid numeric values in signal: {str(e)}'
                }), 400
            
            # Determine position direction
            if signal_message in ['buy', 'long']:
                is_long = True
            elif signal_message in ['sell', 'short']:
                is_long = False
            else:
                return jsonify({
                    'status': 'error',
                    'error': f'Invalid Signal Message: {signal_message}. Must be buy, long, sell, or short'
                }), 400
            
            size_usd = 2.1  # Default size for signals
            leverage = 1     # Default leverage
            
            # Log signal details
            logger.info(f"📡 Processing signal format for TP/SL position:")
            logger.info(f"   Signal Message: {signal_message.upper()}")
            logger.info(f"   Token: {token}")
            logger.info(f"   Current Price: ${current_price_val}")
            logger.info(f"   TP1: ${take_profit_price}")
            if tp2_val:
                logger.info(f"   TP2: ${tp2_val} (noted but using TP1 as primary)")
            logger.info(f"   SL: ${stop_loss_price}")
            logger.info(f"   Username: {username}")
            if safe_address:
                logger.info(f"   Safe Address: {safe_address}")
            if max_exit_time:
                logger.info(f"   Max Exit Time: {max_exit_time}")
        
        else:
            # Direct API format (backward compatibility)
            token = data.get('token', 'ETH').upper()
            size_usd = float(data.get('size_usd', 2.1))  # Default matches normal orders
            leverage = int(data.get('leverage', 2))
            take_profit_price = float(data.get('take_profit_price'))
            stop_loss_price = float(data.get('stop_loss_price'))
            is_long = data.get('is_long', True)
            username = data.get('username', 'api_user')
            
            # Validate required fields for direct format
            if not take_profit_price:
                return jsonify({
                    'status': 'error',
                    'error': 'take_profit_price is required'
                }), 400
                
            if not stop_loss_price:
                return jsonify({
                    'status': 'error', 
                    'error': 'stop_loss_price is required'
                }), 400
        
        # Validate price relationship
        if is_long:
            if take_profit_price <= stop_loss_price:
                return jsonify({
                    'status': 'error',
                    'error': 'For long positions, TP1 must be greater than SL'
                }), 400
        else:
            if take_profit_price >= stop_loss_price:
                return jsonify({
                    'status': 'error',
                    'error': 'For short positions, TP1 must be less than SL'
                }), 400
        
        # Additional validation for signal format
        if 'Signal Message' in data and current_price_val:
            if is_long:
                if take_profit_price <= current_price_val:
                    logger.warning(f"⚠️ TP1 ({take_profit_price}) should be above current price ({current_price_val}) for long positions")
                if stop_loss_price >= current_price_val:
                    logger.warning(f"⚠️ SL ({stop_loss_price}) should be below current price ({current_price_val}) for long positions")
            else:
                if take_profit_price >= current_price_val:
                    logger.warning(f"⚠️ TP1 ({take_profit_price}) should be below current price ({current_price_val}) for short positions")
                if stop_loss_price <= current_price_val:
                    logger.warning(f"⚠️ SL ({stop_loss_price}) should be above current price ({current_price_val}) for short positions")
        
        logger.info(f"🎯 Creating position with TP/SL:")
        logger.info(f"   Token: {token}")
        logger.info(f"   Position: {'LONG' if is_long else 'SHORT'}")
        logger.info(f"   Size: ${size_usd}")
        logger.info(f"   Leverage: {leverage}x")
        logger.info(f"   Take Profit: ${take_profit_price}")
        logger.info(f"   Stop Loss: ${stop_loss_price}")
        
        # Initialize API with safe_address from signal if needed
        if 'Signal Message' in data and safe_address:
            if not gmx_api.initialized or gmx_api.safe_address != safe_address:
                logger.info(f"🔄 Re-initializing API with Safe address from signal: {safe_address}")
                gmx_api.initialize(safe_address=safe_address)
        
        # Prepare kwargs for database tracking
        kwargs = {
            'username': username,
            'original_signal': data
        }
        
        # Add signal_id if this is a signal format
        if 'Signal Message' in data:
            # Database logging is handled within the service layer
            kwargs['signal_id'] = ""
        
        # Execution mode
        auto_execute = data.get('autoExecute', False)
        logger.info("🔄 Using sequential execution mode")
        result = gmx_api.execute_position_with_tp_sl_sequential(
            token=token,
            size_usd=size_usd,
            leverage=leverage,
            take_profit_price=take_profit_price,
            stop_loss_price=stop_loss_price,
            is_long=is_long,
            auto_execute=auto_execute,
            **kwargs
        )
        
        # Add signal-specific metadata if it's a signal format
        if 'Signal Message' in data:
            result.update({
                'signal_id': kwargs.get('signal_id', ''),
                'signal_type': signal_message,
                'username': username,
                'signal_details': {
                    'current_price': current_price_val,
                    'take_profit_tp1': take_profit_price,
                    'take_profit_tp2': tp2_val,
                    'stop_loss': stop_loss_price,
                    'max_exit_time': max_exit_time,
                    'safe_address': safe_address
                },
                'original_signal': data
            })
        
        return jsonify(result) 
        
    except ValueError as e:
        logger.error(f"❌ Validation error: {e}")
        return jsonify({
            'status': 'error',
            'error': f'Invalid input: {str(e)}',
            'timestamp': datetime.now().isoformat()
        }), 400
        
    except Exception as e:
        logger.error(f"❌ Error creating position with TP/SL: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/tp-order', methods=['POST'])
def create_tp_order():
    """Create a Take Profit order using signal format similar to /position/create-with-tp-sl"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'status': 'error',
                'error': 'No data provided'
            }), 400
        
        # Check if this is the signal format or direct API format
        if 'Signal Message' in data and 'Token Mentioned' in data:
            # Signal format - extract parameters
            signal_message = data.get('Signal Message', '').lower()
            token = data.get('Token Mentioned', '').upper()
            tp1 = data.get('TP1')
            tp2 = data.get('TP2')  # Optional, will use TP1 for TP order
            sl = data.get('SL')
            current_price = data.get('Current Price')
            max_exit_time = data.get('Max Exit Time')
            username = data.get('username', 'api_user')
            safe_address = data.get('safeAddress')
            auto_execute = str(data.get('autoExecute', False)).lower() == 'true'
            
            # Validate all required signal fields in a single check
            missing_fields = []
            if not safe_address:
                missing_fields.append('safeAddress')
            if not signal_message:
                missing_fields.append('Signal Message')
            if not token:
                missing_fields.append('Token Mentioned')
            if tp1 is None:
                missing_fields.append('TP1')
            if missing_fields:
                return jsonify({
                    'status': 'error',
                    'error': f"Missing required field(s): {', '.join(missing_fields)}"
                }), 400
            
            # Convert to float and validate
            try:
                trigger_price = float(tp1)
                current_price_val = float(current_price) if current_price else None
                tp2_val = float(tp2) if tp2 else None
                sl_val = float(sl) if sl else None
                
            except (ValueError, TypeError) as e:
                return jsonify({
                    'status': 'error',
                    'error': f'Invalid numeric values in signal: {str(e)}'
                }), 400
            
            # Determine position direction
            if signal_message in ['buy', 'long']:
                is_long = True
            elif signal_message in ['sell', 'short']:
                is_long = False
            else:
                return jsonify({
                    'status': 'error',
                    'error': f'Invalid Signal Message: {signal_message}. Must be buy, long, sell, or short'
                }), 400
            
            # Default trading parameters for signals
            size_usd = 2.1  # Default size for signals
            
            # Log signal details
            logger.info(f"📡 Processing signal format for Take Profit order:")
            logger.info(f"   Signal Message: {signal_message.upper()}")
            logger.info(f"   Token: {token}")
            logger.info(f"   Current Price: ${current_price_val}")
            logger.info(f"   TP1: ${trigger_price}")
            if tp2_val:
                logger.info(f"   TP2: ${tp2_val} (noted but using TP1 as primary)")
            if sl_val:
                logger.info(f"   SL: ${sl_val} (noted but not used for TP order)")
            logger.info(f"   Username: {username}")
            logger.info(f"   Safe Address: {safe_address}")
            if max_exit_time:
                logger.info(f"   Max Exit Time: {max_exit_time}")
            
            # Validate TP price makes sense for position direction
            if current_price_val:
                if is_long and trigger_price <= current_price_val:
                    logger.warning(f"⚠️ TP1 ({trigger_price}) should be above current price ({current_price_val}) for long positions")
                elif not is_long and trigger_price >= current_price_val:
                    logger.warning(f"⚠️ TP1 ({trigger_price}) should be below current price ({current_price_val}) for short positions")
        
        else:
            # Direct API format (backward compatibility)
            token = data.get('token', '').upper()
            trigger_price = data.get('trigger_price')
            is_long = data.get('is_long', True)
            size_usd = data.get('size_usd')
            safe_address = data.get('safeAddress')
            auto_execute = data.get('autoExecute', False)
            username = data.get('username', 'api_user')
            
            # Validate required parameters in a single check
            missing_fields = []
            if not token:
                missing_fields.append('token')
            if trigger_price is None:
                missing_fields.append('trigger_price')
            if size_usd is None:
                missing_fields.append('size_usd')
            if missing_fields:
                return jsonify({
                    'status': 'error',
                    'error': f"Missing required field(s): {', '.join(missing_fields)}"
                }), 400
            
            # Convert and validate numeric values
            try:
                trigger_price = float(trigger_price)
                size_usd = float(size_usd)
            except (ValueError, TypeError) as e:
                return jsonify({
                    'status': 'error',
                    'error': f'Invalid numeric values: {str(e)}'
                }), 400
            
            logger.info(f"🎯 Creating Take Profit order (direct format):")
            logger.info(f"   Token: {token}")
            logger.info(f"   Trigger Price: ${trigger_price}")
            logger.info(f"   Size: ${size_usd}")
            logger.info(f"   Position: {'LONG' if is_long else 'SHORT'}")
        
        # Initialize API with safe_address if provided
        if safe_address:
            if not gmx_api.initialized or gmx_api.safe_address != safe_address:
                logger.info(f"🔄 Re-initializing API with Safe address from request: {safe_address}")
                gmx_api.initialize(safe_address=safe_address)
        
        # Prepare kwargs for database tracking
        kwargs = {
            'username': username,
            'original_signal': data
        }
        
        # Add signal_id if this is a signal format
        signal_id = ""
        if 'Signal Message' in data:
            # Database logging is handled within the service layer
            kwargs['signal_id'] = signal_id
        
        # Create the take profit order
        result = gmx_api._create_take_profit_order(
            token=token,
            size_usd=size_usd,
            trigger_price=trigger_price,
            is_long=is_long,
            auto_execute=auto_execute,
            **kwargs
        )
        
        # Add signal-specific metadata if it's a signal format
        if 'Signal Message' in data:
            result.update({
                'signal_id': signal_id,
                'signal_type': signal_message,
                'signal_details': {
                    'current_price': current_price_val,
                    'take_profit_tp1': trigger_price,
                    'take_profit_tp2': tp2_val,
                    'stop_loss': sl_val,
                    'max_exit_time': max_exit_time,
                    'safe_address': safe_address
                },
                'original_signal': data
            })
        
        return jsonify(result)
        
    except ValueError as e:
        logger.error(f"❌ Validation error: {e}")
        return jsonify({
            'status': 'error',
            'error': f'Invalid input: {str(e)}',
            'timestamp': datetime.now().isoformat()
        }), 400
        
    except Exception as e:
        logger.error(f"❌ Error creating Take Profit order: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/positions', methods=['GET'])
def get_positions():
    """Get current positions"""
    try:
        positions_result = gmx_api.get_active_positions()
        status = positions_result.get('status')
        code = 200 if status == 'success' else 500
        return jsonify(positions_result), code
        
    except Exception as e:
        logger.error(f"❌ Error getting positions: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/tokens', methods=['GET'])
def get_supported_tokens():
    """Get supported tokens"""
    return jsonify({
        'status': 'success',
        'tokens': list(gmx_api.supported_tokens.keys()),
        'timestamp': datetime.now().isoformat()
    })

@app.route('/position/close', methods=['POST'])
def close_position():
    """Close an existing position"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'status': 'error',
                'error': 'No data provided'
            }), 400

        # Extract parameters
        safe_address = data.get('safeAddress')
        token = data.get('token')
        size_usd = data.get('size_usd')
        is_long = data.get('is_long', True)
        auto_execute = data.get('autoExecute', False)
        slippage_percent = data.get('slippage_percent', 0.03)  # Default 3%
        username = data.get('username', 'api_user')

        # Validate required parameters
        missing_fields = []
        if not token:
            missing_fields.append('token')
        if size_usd is None:
            missing_fields.append('size_usd')
        if missing_fields:
            return jsonify({
                'status': 'error',
                'error': f"Missing required field(s): {', '.join(missing_fields)}"
            }), 400

        # Convert and validate numeric values
        try:
            size_usd = float(size_usd)
            slippage_percent = float(slippage_percent)
        except (ValueError, TypeError) as e:
            return jsonify({
                'status': 'error',
                'error': f'Invalid numeric value: {str(e)}'
            }), 400

        logger.info(f"🚪 Closing position:")
        logger.info(f"   Token: {token}")
        logger.info(f"   Size: ${size_usd}")
        logger.info(f"   Position: {'LONG' if is_long else 'SHORT'}")
        logger.info(f"   Slippage: {slippage_percent * 100}%")
        logger.info(f"   Auto-execute: {auto_execute}")

        # Initialize API with safe_address if provided
        if safe_address:
            if not gmx_api.initialized or gmx_api.safe_address != safe_address:
                logger.info(f"🔄 Re-initializing API with Safe address from request: {safe_address}")
                gmx_api.initialize(safe_address=safe_address)

        # Prepare kwargs for database tracking
        kwargs = {
            'original_signal': data
        }

        # Create the close order
        result = gmx_api._create_close_order(
            token=token,
            size_usd=size_usd,
            is_long=is_long,
            auto_execute=auto_execute,
            slippage_percent=slippage_percent,
            username=username,
            **kwargs
        )

        return jsonify(result)

    except ValueError as e:
        logger.error(f"❌ Validation error: {e}")
        return jsonify({
            'status': 'error',
            'error': f'Invalid input: {str(e)}',
            'timestamp': datetime.now().isoformat()
        }), 400

    except Exception as e:
        logger.error(f"❌ Error closing position: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/safe/execute', methods=['POST'])
def execute_safe_transaction_endpoint():
    """Execute a Safe transaction"""
    try:
        data = request.get_json()
        if not data:
            return jsonify({
                'status': 'error',
                'error': 'No data provided'
            }), 400
        
        safe_tx_hash = data.get('safeTxHash')
        safe_address = data.get('safeAddress')
        
        if not safe_tx_hash:
            return jsonify({
                'status': 'error',
                'error': 'safeTxHash is required'
            }), 400
        
        # Initialize API with safe_address if provided
        if safe_address:
            if not gmx_api.initialized or gmx_api.safe_address != safe_address:
                logger.info(f"🔄 Re-initializing API with Safe address from request: {safe_address}")
                gmx_api.initialize(safe_address=safe_address)
        
        result = gmx_api.execute_safe_transaction(safe_tx_hash)
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"❌ Error executing Safe transaction: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/safe/pending', methods=['GET'])
def list_pending_transactions_endpoint():
    """List pending Safe transactions"""
    try:
        # Get query parameters
        limit = int(request.args.get('limit', 10))
        offset = int(request.args.get('offset', 0))
        safe_address = request.args.get('safeAddress')
        
        # Initialize API with safe_address if provided
        if safe_address:
            if not gmx_api.initialized or gmx_api.safe_address != safe_address:
                logger.info(f"🔄 Re-initializing API with Safe address from request: {safe_address}")
                gmx_api.initialize(safe_address=safe_address)
        
        result = gmx_api.list_pending_transactions(limit=limit, offset=offset)
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"❌ Error listing pending transactions: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

if __name__ == '__main__':
    # Initialize API without safe_address - will be set from signals
    try:
        gmx_api.initialize()
        logger.info("🔧 Enhanced GMX API initialized - Safe address will be set from signals")
    except Exception as e:
        logger.warning(f"⚠️ Initial initialization failed: {e}")
        logger.info("💡 API will be initialized when first signal with safeAddress is received")

    # Start the Flask server
    port = int(os.getenv('GMX_PYTHON_API_PORT', 5001))
    logger.info(f"🚀 Starting Enhanced GMX Safe API with Database on port {port}")
    app.run(host='0.0.0.0', port=port, debug=True)