#!/usr/bin/env python3
"""
Enhanced GMX Safe API Server with MongoDB Database Integration
Tracks all Safe transactions, trading positions, and execution history
"""

import os
import sys
import time
import logging
import json
from decimal import Decimal
from datetime import datetime
from typing import Dict, Any, Optional

from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from web3 import Web3

# GMX Python SDK imports
from gmx_python_sdk.scripts.v2.gmx_utils import ConfigManager
from gmx_python_sdk.scripts.v2.order.create_increase_order import IncreaseOrder
from gmx_python_sdk.scripts.v2.order.create_decrease_order import DecreaseOrder
from gmx_python_sdk.scripts.v2.order.create_position_with_tp_sl import PositionWithTPSL
from gmx_python_sdk.scripts.v2.order.order_argument_parser import OrderArgumentParser
from gmx_python_sdk.scripts.v2.get.get_open_positions import GetOpenPositions

# Safe SDK imports
from safe_eth.safe import Safe
from safe_eth.eth import EthereumClient

# Database integration imports
from gmx_python_sdk.scripts.v2.database.transaction_tracker import transaction_tracker
from gmx_python_sdk.scripts.v2.database.gmx_database_integration import gmx_db
from gmx_python_sdk.scripts.v2.database.api_endpoints import add_database_routes
from gmx_python_sdk.scripts.v2.database.mongo_models import (
    TransactionStatus, PositionStatus, OrderType
)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
logger.info("🔧 Environment variables loaded from .env file")

app = Flask(__name__)
CORS(app)

class EnhancedGMXAPI:
    def __init__(self):
        self.initialized = False
        self.db_connected = False
        
        # Configuration from environment
        self.safe_address = os.getenv('SAFE_ADDRESS')
        self.private_key = os.getenv('PRIVATE_KEY')
        self.rpc_url = os.getenv('RPC_URL', 'https://arb1.arbitrum.io/rpc')
        
        # MongoDB connection
        self.mongodb_connection = os.getenv('MONGODB_CONNECTION_STRING', 'mongodb://localhost:27017/')
        
        # GMX and Safe configuration
        self.config = None
        self.safe = None
        self.ethereum_client = None
        
        # GMX V2 addresses
        self.gmx_exchange_router = "0x7452c558d45f8afC8c83dAe62C3f8A5BE19c71f6"
        self.usdc_address = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
        
        # Token mapping loaded from JSON file
        self.supported_tokens = self._load_supported_tokens()
    
    def initialize(self):
        """Initialize GMX, Safe, and Database connections"""
        try:
            # Initialize database connection first
            self.db_connected = transaction_tracker.ensure_connected()
            if self.db_connected:
                logger.info("✅ MongoDB connected successfully")
            else:
                logger.warning("⚠️ MongoDB connection failed - continuing without database")
            
            # Get the address that corresponds to the private key
            w3 = Web3()
            private_key_address = w3.eth.account.from_key(self.private_key).address
            
            logger.info(f"🔍 Address derived from private key: {private_key_address}")
            logger.info(f"🔍 Safe wallet address: {self.safe_address}")
            
            # Initialize Safe SDK
            self.ethereum_client = EthereumClient(self.rpc_url)
            self.safe = Safe(self.safe_address, self.ethereum_client)
            
            # Initialize GMX SDK config
            self.config = ConfigManager(chain='arbitrum')
            self.config.set_rpc(self.rpc_url)
            self.config.set_chain_id(42161)
            self.config.set_wallet_address(self.safe_address)
            self.config.set_private_key(self.private_key)
            
            # Route transactions through Safe
            try:
                safe_api_url = os.getenv('SAFE_API_URL')
                safe_api_key = os.getenv('SAFE_TRANSACTION_SERVICE_API_KEY')
                
                self.config.enable_safe_transactions(
                    safe_address=self.safe_address,
                    safe_api_url=safe_api_url,
                    safe_api_key=safe_api_key
                )
                logger.info("✅ Safe transactions enabled in GMX config")
            except Exception as e:
                logger.warning(f"⚠️ Could not enable Safe transactions: {e}")
            
            self.private_key_address = private_key_address
            
            # Check balances
            self._log_wallet_balances()
            
            self.initialized = True
            logger.info("✅ Enhanced GMX Safe API with Database initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize: {e}")
            return False

    def _load_supported_tokens(self) -> Dict[str, Dict[str, str]]:
        """Load supported tokens configuration from supported_tokens.json.

        Falls back to minimal defaults if the file is missing or invalid.
        """
        try:
            config_path = os.path.join(os.path.dirname(__file__), 'supported_tokens.json')
            with open(config_path, 'r') as file_handle:
                data = json.load(file_handle)

            tokens_list = data.get('tokens', [])
            mapping: Dict[str, Dict[str, str]] = {}
            for token_entry in tokens_list:
                symbol = str(token_entry.get('token', '')).upper()
                market_key = token_entry.get('market_key')
                index_token = token_entry.get('index_token')
                collateral_token = token_entry.get('collateral_token')

                if not symbol or not market_key or not index_token or not collateral_token:
                    continue

                mapping[symbol] = {
                    'market_key': market_key,
                    'index_token': index_token,
                    'collateral_token': collateral_token
                }

            if not mapping:
                raise ValueError('No valid token entries found in supported_tokens.json')

            logger.info(f"✅ Loaded {len(mapping)} supported tokens from JSON configuration")
            return mapping
        except Exception as error:
            logger.warning(f"⚠️ Could not load supported tokens from JSON: {error}. Using minimal defaults.")
            return {
                'BTC': {
                    'market_key': '0x47c031236e19d024b42f8AE6780E44A573170703',
                    'index_token': '0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f',
                    'collateral_token': '0xaf88d065e77c8cC2239327C5EDb3A432268e5831'
                },
                'ETH': {
                    'market_key': '0x70d95587d40A2caf56bd97485aB3Eec10Bee6336',
                    'index_token': '0x82aF49447D8a07e3bd95BD0d56f35241523fBab1',
                    'collateral_token': '0xaf88d065e77c8cC2239327C5EDb3A432268e5831'
                }
            }
    
    def _log_wallet_balances(self):
        """Log wallet balances and store in database if connected"""
        try:
            w3_provider = Web3(Web3.HTTPProvider(self.rpc_url))
            usdc_abi = [{"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"}]
            usdc_contract = w3_provider.eth.contract(address=self.usdc_address, abi=usdc_abi)
            
            safe_balance = usdc_contract.functions.balanceOf(self.safe_address).call()
            eth_balance = w3_provider.eth.get_balance(self.safe_address)
            
            logger.info(f"💰 Safe Wallet Balance:")
            logger.info(f"   USDC Balance: {safe_balance / 10**6} USDC")
            logger.info(f"   ETH Balance: {Web3.from_wei(eth_balance, 'ether')} ETH")
            
            # Log to database if connected
            if self.db_connected:
                # Could store balance history in a separate collection
                pass
                
        except Exception as e:
            logger.warning(f"⚠️ Could not check balances: {e}")
    
    def execute_buy_order(self, token: str, size_usd: float, leverage: int = 2, **kwargs) -> Dict[str, Any]:
        """Execute a buy order with full database tracking"""
        try:
            if not self.initialized:
                raise Exception("API not initialized")
            
            token_config = self.supported_tokens.get(token.upper())
            if not token_config:
                raise Exception(f"Token {token} not supported")
            
            # Extract additional parameters for database logging
            signal_id = kwargs.get('signal_id')
            username = kwargs.get('username', 'api_user')
            original_signal = kwargs.get('original_signal', {})
            
            # Log position creation to database
            position_id = None
            if self.db_connected:
                position_id = gmx_db.log_order_creation(
                    safe_address=self.safe_address,
                    token=token.upper(),
                    order_type="buy",
                    size_usd=size_usd,
                    leverage=leverage,
                    is_long=True,
                    signal_id=signal_id,
                    username=username,
                    market_key=token_config['market_key'],
                    index_token=token_config['index_token'],
                    collateral_token=token_config['collateral_token'],  # Store actual USDC address
                    original_signal=original_signal
                )
            
            # Calculate amounts
            collateral_amount = Decimal(str(size_usd)) / Decimal(str(leverage))
            collateral_amount_wei = int(collateral_amount * Decimal(10**6))
            size_delta = int(collateral_amount * Decimal(str(leverage)) * Decimal(10**30))
            
            logger.info(f"📈 Executing BUY order for {token} (Position ID: {position_id})")
            logger.info(f"   Size: ${size_usd} USD, Leverage: {leverage}x")
            
            # Check Safe wallet funds
            if not self._ensure_safe_has_funds(float(collateral_amount)):
                raise Exception("Safe wallet has insufficient funds for trading")
            
            # Execute GMX order
            order = IncreaseOrder(
                config=self.config,
                market_key=token_config['market_key'],
                collateral_address=token_config['collateral_token'],
                index_token_address=token_config['index_token'],
                is_long=True,
                size_delta=size_delta,
                initial_collateral_delta_amount=collateral_amount_wei,
                slippage_percent=0.005,
                swap_path=[],
                debug_mode=False
            )
            
            # Extract Safe transaction information
            safe_info = {}
            safe_tx_hash = None
            
            last_payload = getattr(order, 'last_safe_tx_payload', None)
            last_proposal = getattr(order, 'last_safe_tx_proposal', None)
            
            if last_proposal and isinstance(last_proposal, dict):
                safe_tx_hash = last_proposal.get('safeTxHash') or last_proposal.get('contractTransactionHash')
                safe_info = {
                    'safeTxHash': safe_tx_hash,
                    'url': last_proposal.get('url')
                }
                
                # Log Safe transaction to database
                if self.db_connected and safe_tx_hash:
                    gmx_db.log_safe_transaction_from_order(
                        safe_tx_hash=safe_tx_hash,
                        safe_address=self.safe_address,
                        order_type=OrderType.MARKET_INCREASE,
                        token=token.upper(),
                        position_id=position_id,
                        signal_id=signal_id,
                        username=username,
                        market_key=token_config['market_key']
                    )
            
            result = {
                'status': 'success',
                'order': str(order),
                'token': token,
                'size_usd': size_usd,
                'leverage': leverage,
                'position_type': 'LONG',
                'safe_wallet': self.safe_address,
                'safe': safe_info,
                'position_id': position_id,
                'timestamp': datetime.now().isoformat()
            }
            
            # Update position status in database if execution seems successful
            if self.db_connected and position_id:
                gmx_db.update_position_from_execution(
                    position_id=position_id,
                    execution_result=result,
                    safe_tx_hash=safe_tx_hash
                )
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Error executing buy order: {e}")
            
            # Log failure to database
            if self.db_connected and position_id:
                transaction_tracker.update_position_status(
                    position_id=position_id,
                    status=PositionStatus.PENDING  # Keep as pending for potential retry
                )
            
            return {
                'status': 'error',
                'error': str(e),
                'position_id': position_id,
                'timestamp': datetime.now().isoformat()
            }
    
    def execute_sell_order(self, token: str, size_usd: float = None, **kwargs) -> Dict[str, Any]:
        """Execute a sell order with database tracking"""
        try:
            if not self.initialized:
                raise Exception("API not initialized")
            
            # Find open position in database
            active_positions = []
            if self.db_connected:
                active_positions = transaction_tracker.get_active_positions(self.safe_address)
                active_positions = [p for p in active_positions if p.get('token') == token.upper() and p.get('is_long')]
            
            if not active_positions:
                raise Exception(f"No open {token} position found to close")
            
            position = active_positions[0]  # Use first active position
            position_id = position.get('position_id')
            
            # Calculate close parameters
            if size_usd:
                size_delta = int(Decimal(str(size_usd)) * Decimal(10**30))
                collateral_to_withdraw = int(Decimal(str(size_usd)) * Decimal(10**6))
            else:
                # Convert database values to Decimal for consistent type handling
                position_size = Decimal(str(position.get('size_delta_usd', 0)))
                position_collateral = Decimal(str(position.get('collateral_delta_usd', 0)))
                size_delta = int(position_size * Decimal(10**30))
                collateral_to_withdraw = int(position_collateral * Decimal(10**6))
                size_usd = float(position_size)
            
            logger.info(f"📉 Executing SELL order for {token} (Position ID: {position_id})")
            logger.info(f"   Size to close: ${size_usd} USD")
            
            # Execute GMX decrease order
            # Use the correct token addresses from supported_tokens mapping
            token_config = self.supported_tokens.get(token.upper())
            if not token_config:
                raise Exception(f"Token {token} not supported")
            
            order = DecreaseOrder(
                config=self.config,
                market_key=position.get('market_key', ''),
                collateral_address=token_config['collateral_token'],
                index_token_address=token_config['index_token'],
                is_long=position.get('is_long', True),
                size_delta=size_delta,
                initial_collateral_delta_amount=collateral_to_withdraw,
                slippage_percent=0.005,
                swap_path=[],
                debug_mode=False
            )
            
            # Extract Safe transaction info
            safe_info = {}
            safe_tx_hash = None
            
            last_proposal = getattr(order, 'last_safe_tx_proposal', None)
            if last_proposal and isinstance(last_proposal, dict):
                safe_tx_hash = last_proposal.get('safeTxHash') or last_proposal.get('contractTransactionHash')
                safe_info = {
                    'safeTxHash': safe_tx_hash,
                    'url': last_proposal.get('url')
                }
                
                # Log Safe transaction to database
                if self.db_connected and safe_tx_hash:
                    gmx_db.log_safe_transaction_from_order(
                        safe_tx_hash=safe_tx_hash,
                        safe_address=self.safe_address,
                        order_type=OrderType.MARKET_DECREASE,
                        token=token.upper(),
                        position_id=position_id,
                        market_key=position.get('market_key', '')
                    )
            
            # Update position in database
            if self.db_connected and position_id:
                # Ensure consistent type comparison
                position_size_for_comparison = float(position.get('size_delta_usd', 0))
                full_close = not size_usd or size_usd >= position_size_for_comparison
                gmx_db.close_position(
                    position_id=position_id,
                    size_closed_usd=size_usd,
                    safe_tx_hash=safe_tx_hash
                )
            
            return {
                'status': 'success',
                'order': str(order),
                'token': token,
                'size_closed': size_usd or 'FULL',
                'action': 'SELL',
                'safe_wallet': self.safe_address,
                'safe': safe_info,
                'position_id': position_id,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Error executing sell order: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def _ensure_safe_has_funds(self, required_usdc: float) -> bool:
        """Check if Safe wallet has sufficient USDC"""
        try:
            w3 = Web3(Web3.HTTPProvider(self.rpc_url))
            usdc_abi = [{"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"}]
            usdc_contract = w3.eth.contract(address=self.usdc_address, abi=usdc_abi)
            
            safe_balance = usdc_contract.functions.balanceOf(self.safe_address).call()
            required_wei = int(required_usdc * 10**6)
            
            return safe_balance >= required_wei
        except Exception:
            return False
    
    def process_signal_with_database(self, signal_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process trading signal with full database integration"""
        try:
            # Log signal to database
            signal_id = ""
            if self.db_connected:
                username = signal_data.get('username', 'api_user')
                signal_id = gmx_db.log_signal_processing(
                    signal_data=signal_data,
                    username=username,
                    api_endpoint='/signal/process'
                )
            
            # Process the signal
            signal_type = signal_data.get('Signal Message', '').lower()
            token = signal_data.get('Token Mentioned', '').upper()
            
            # Add signal tracking info to kwargs
            kwargs = {
                'signal_id': signal_id,
                'username': signal_data.get('username', 'api_user'),
                'original_signal': signal_data
            }
            
            if signal_type in ['buy', 'long']:
                result = self.execute_buy_order(token=token, size_usd=2.02, leverage=1, **kwargs)
            elif signal_type in ['sell', 'short']:
                result = self.execute_sell_order(token=token, **kwargs)
            else:
                raise Exception(f"Unknown signal type: {signal_type}")
            
            # Update signal processing status
            if self.db_connected and signal_id:
                transaction_tracker.update_signal_processing(
                    signal_id=signal_id,
                    processed=True,
                    position_id=result.get('position_id'),
                    safe_tx_hashes=[result.get('safe', {}).get('safeTxHash')] if result.get('safe', {}).get('safeTxHash') else []
                )
            
            # Add signal metadata to result
            result.update({
                'signal_id': signal_id,
                'signal_type': signal_type,
                'original_signal': signal_data
            })
            
            return result
            
        except Exception as e:
            # Log processing error
            if self.db_connected and signal_id:
                transaction_tracker.update_signal_processing(
                    signal_id=signal_id,
                    processed=False,
                    processing_error=str(e)
                )
            
            logger.error(f"❌ Error processing signal: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'signal_id': signal_id,
                'timestamp': datetime.now().isoformat()
            }

# Initialize API instance
gmx_api = EnhancedGMXAPI()

# Add all the original routes
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'Enhanced GMX Safe API with Database',
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

@app.route('/sell', methods=['POST'])
def sell_position():
    """Execute a sell order"""
    try:
        data = request.get_json()
        token = data.get('token', 'BTC').upper()
        size_usd = data.get('size_usd')  # None means close entire position
        
        result = gmx_api.execute_sell_order(token=token, size_usd=size_usd)
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"❌ Error selling position: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500
        
# Add database-specific routes
add_database_routes(app)

if __name__ == '__main__':
    # Auto-initialize if environment variables are available
    if os.getenv('SAFE_ADDRESS') and os.getenv('PRIVATE_KEY'):
        logger.info("🔧 Auto-initializing Enhanced GMX API...")
        gmx_api.initialize()
    else:
        logger.info("⚠️ Missing SAFE_ADDRESS or PRIVATE_KEY - manual initialization required")
    
    # Start the Flask server
    port = int(os.getenv('GMX_PYTHON_API_PORT', 5001))
    logger.info(f"🚀 Starting Enhanced GMX Safe API with Database on port {port}")
    app.run(host='0.0.0.0', port=port, debug=True)