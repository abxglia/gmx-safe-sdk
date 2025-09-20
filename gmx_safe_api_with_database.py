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
from gmx_python_sdk.scripts.v2.order.create_take_profit_order import TakeProfitOrder
from gmx_python_sdk.scripts.v2.order.create_stop_loss_order import StopLossOrder
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

# Safe utilities imports
from gmx_python_sdk.scripts.v2.safe_utils import (
    execute_safe_transaction,
    list_safe_pending_transactions
)
from gmx_python_sdk.scripts.v2.approve_token_for_spend import check_if_approved

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
        # self.safe_address = os.getenv('SAFE_ADDRESS')  # Will be set from signal
        self.private_key = os.getenv('PRIVATE_KEY')
        self.rpc_url = os.getenv('RPC_URL', 'https://arb1.arbitrum.io/rpc')
        
        # Safe address will be set dynamically from signals
        self.safe_address = None
        
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
    
    def initialize(self, safe_address: str = None):
        """Initialize GMX, Safe, and Database connections"""
        try:
            # Set safe_address if provided
            if safe_address:
                self.safe_address = safe_address
                logger.info(f"🔧 Setting Safe address from signal: {self.safe_address}")
            elif not self.safe_address:
                # Fallback to environment variable if no safe_address provided
                self.safe_address = os.getenv('SAFE_ADDRESS')
                if self.safe_address:
                    logger.info(f"🔧 Using Safe address from environment: {self.safe_address}")
                else:
                    raise Exception("No Safe address provided - must be in signal or environment variable")
            
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
    
    def execute_buy_order(self, token: str, size_usd: float, leverage: int = 2, auto_execute: bool = False, **kwargs) -> Dict[str, Any]:
        """Execute a buy order with database tracking and optional auto-execution"""
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
            
            # Calculate amounts
            collateral_amount = Decimal(str(size_usd)) / Decimal(str(leverage))
            collateral_amount_usd = float(collateral_amount)
            
            logger.info(f"💰 Creating Buy order for {token}...")
            logger.info(f"   Size: ${size_usd} USD")
            logger.info(f"   Collateral: ${collateral_amount_usd} USDC")
            logger.info(f"   Leverage: {leverage}x")
            
            # Log position creation to database
            position_id = None
            if self.db_connected:
                position_id = gmx_db.log_order_creation(
                    safe_address=self.safe_address,
                    token=token.upper(),
                    order_type="market_increase",
                    size_usd=size_usd,
                    leverage=leverage,
                    is_long=True,
                    signal_id=signal_id,
                    username=username,
                    market_key=token_config['market_key'],
                    index_token=token_config['index_token'],
                    collateral_token=token_config['collateral_token'],
                    original_signal=original_signal
                )
            
            # Set auto_execute_approvals in config for approval transactions
            original_auto_execute = getattr(self.config, 'auto_execute_approvals', False)
            if auto_execute:
                self.config.auto_execute_approvals = True
            
            # Create the order (this will handle approvals during initialization)
            order = IncreaseOrder(
                config=self.config,
                market_key=token_config['market_key'],
                collateral_address=token_config['collateral_token'],
                index_token_address=token_config['index_token'],
                is_long=True,
                size_delta=int(Decimal(str(size_usd)) * Decimal(10**30)),  # Convert to proper GMX format
                initial_collateral_delta_amount=int(Decimal(str(collateral_amount_usd)) * Decimal(10**6)),  # Convert USDC to 6 decimals
                slippage_percent=0.5,
                swap_path=[]
            )
            
            # Reset config to original state
            self.config.auto_execute_approvals = original_auto_execute
            
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
            
            # Auto-execute the transaction if requested
            execution_result = None
            if auto_execute and safe_tx_hash:
                logger.info(f"⏳ Waiting for transaction to be processed by Safe API...")
                time.sleep(15)  # Wait for Safe Transaction Service to process the proposal
                
                logger.info(f"🚀 Auto-executing Safe transaction: {safe_tx_hash}")
                execution_result = self.execute_safe_transaction(safe_tx_hash)
                if execution_result.get('status') == 'success':
                    result['execution'] = {
                        'status': 'success',
                        'txHash': execution_result.get('txHash'),
                        'message': 'Transaction executed successfully'
                    }
                    # Update Safe info with execution details
                    safe_info['executed'] = True
                    safe_info['execution_tx_hash'] = execution_result.get('txHash')
                else:
                    result['execution'] = {
                        'status': 'error',
                        'error': execution_result.get('error'),
                        'message': 'Auto-execution failed, transaction remains pending'
                    }
                    logger.warning(f"⚠️ Auto-execution failed: {execution_result.get('error')}")
            
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
    
    def execute_sell_order(self, token: str, size_usd: float = None, auto_execute: bool = False, **kwargs) -> Dict[str, Any]:
        """Execute a sell order with database tracking and optional auto-execution"""
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
            
            # Auto-execute the transaction if requested
            if auto_execute and safe_tx_hash:
                logger.info(f"⏳ Waiting for transaction to be processed by Safe API...")
                time.sleep(15)  # Wait for Safe Transaction Service to process the proposal
                
                logger.info(f"🚀 Auto-executing Safe transaction: {safe_tx_hash}")
                execution_result = self.execute_safe_transaction(safe_tx_hash)
                if execution_result.get('status') == 'success':
                    safe_info['executed'] = True
                    safe_info['execution_tx_hash'] = execution_result.get('txHash')
                    safe_info['execution_message'] = 'Transaction executed successfully'
                else:
                    safe_info['execution_error'] = execution_result.get('error')
                    safe_info['execution_message'] = 'Auto-execution failed, transaction remains pending'
                    logger.warning(f"⚠️ Auto-execution failed: {execution_result.get('error')}")
            
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
    
    def execute_pending_approval_transactions(self) -> Dict[str, Any]:
        """Execute any pending approval transactions before creating orders"""
        try:
            logger.info("🔍 Checking for pending approval transactions...")
            
            # Get pending transactions
            pending_txs = self.list_pending_transactions(limit=10)
            approval_executed = False
            
            if pending_txs.get('status') == 'success' and pending_txs.get('transactions'):
                for tx in pending_txs['transactions']:
                    # Look for USDC approval transactions
                    tx_data = tx.get('data', '').lower()
                    tx_to = tx.get('to', '').lower()
                    
                    if (tx_to == self.usdc_address.lower() and 
                        'approval' in tx_data):
                        
                        safe_tx_hash = tx.get('safeTxHash')
                        logger.info(f"📋 Found pending approval transaction: {safe_tx_hash}")
                        
                        # Execute the approval transaction
                        execution_result = self.execute_safe_transaction(safe_tx_hash)
                        
                        if execution_result.get('status') == 'success':
                            logger.info(f"✅ Approval transaction executed: {execution_result.get('txHash')}")
                            approval_executed = True
                            # Wait for blockchain confirmation
                            time.sleep(15)
                        else:
                            logger.warning(f"⚠️ Approval execution failed: {execution_result.get('error')}")
                        break
                
                if not approval_executed:
                    logger.info("ℹ️ No pending approval transactions found")
            else:
                logger.warning("⚠️ Could not retrieve pending transactions")
            
            return {
                'status': 'success',
                'approval_executed': approval_executed,
                'message': 'Approval transaction check completed'
            }
            
        except Exception as e:
            logger.error(f"❌ Error executing pending approval transactions: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'approval_executed': False
            }

    def ensure_token_approval(self, token_amount_usd: float, auto_execute: bool = False) -> Dict[str, Any]:
        """Check and ensure USDC approval for GMX trading with auto-execution"""
        try:
            if not self.initialized:
                raise Exception("API not initialized")
            
            # GMX Exchange Router address
            spender_address = self.gmx_exchange_router
            token_address = self.usdc_address
            
            # Convert USD amount to token decimals (USDC uses 6 decimals)
            amount_in_tokens = int(token_amount_usd * 10**6)
            
            logger.info(f"🔍 Checking USDC approval for ${token_amount_usd} ({amount_in_tokens} tokens)")
            
            # Set Safe mode in config
            self.config.use_safe_transactions = True
            self.config.safe_address = self.safe_address
            self.config.safe_api_url = os.getenv('SAFE_API_URL')
            self.config.safe_api_key = os.getenv('SAFE_TRANSACTION_SERVICE_API_KEY')
            
            # Check current approval and approve if needed with auto-execution
            try:
                # This will check allowance and create/execute approval if needed
                approval_result = check_if_approved(
                    config=self.config,
                    spender=spender_address,
                    token_to_approve=token_address,
                    amount_of_tokens_to_spend=amount_in_tokens,
                    max_fee_per_gas=0,
                    approve=True,
                    auto_execute=auto_execute  # Use the auto_execute parameter
                )
                
                logger.info(f"✅ USDC approval check completed: {approval_result.get('message', '')}")
                
            except Exception as approval_error:
                logger.warning(f"⚠️ Approval check encountered issue: {approval_error}")
                approval_result = {
                    'status': 'error',
                    'error': str(approval_error),
                    'approval_needed': False,
                    'allowance_sufficient': False
                }
            
            result = {
                'status': 'success',
                'message': 'USDC approval check completed',
                'token_amount_usd': token_amount_usd,
                'token_amount': amount_in_tokens,
                'spender': spender_address,
                'safe_wallet': self.safe_address,
                'approval_result': approval_result
            }
            
            # Add approval transaction details if available
            if approval_result.get('safe_tx_hash'):
                result['approval_transaction'] = {
                    'safeTxHash': approval_result.get('safe_tx_hash'),
                    'executed': approval_result.get('approval_executed', False),
                    'execution_tx_hash': approval_result.get('execution_tx_hash'),
                    'payload_file': approval_result.get('payload_file')
                }
                
            # No approval transaction needed or no safe_tx_hash available
            elif not approval_result.get('approval_needed'):
                result['approval_transaction'] = {
                    'message': 'No approval transaction found (likely already approved)'
                }
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Error ensuring token approval: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'token_amount_usd': token_amount_usd,
                'timestamp': datetime.now().isoformat()
            }

    def execute_safe_transaction(self, safe_tx_hash: str) -> Dict[str, Any]:
        """Execute a Safe transaction using the safe_utils module"""
        try:
            if not self.initialized:
                raise Exception("API not initialized")
            
            if not self.safe_address:
                raise Exception("Safe address not set")
            
            # Get Safe API configuration from environment
            safe_api_url = os.getenv('SAFE_API_URL')
            safe_api_key = os.getenv('SAFE_TRANSACTION_SERVICE_API_KEY')
            
            if not safe_api_url:
                raise Exception("SAFE_API_URL environment variable not set")
            
            logger.info(f"🚀 Executing Safe transaction: {safe_tx_hash}")
            
            # Execute the transaction using safe_utils
            result = execute_safe_transaction(
                safe_address=self.safe_address,
                safe_tx_hash=safe_tx_hash,
                rpc_url=self.rpc_url,
                private_key=self.private_key,
                safe_api_url=safe_api_url,
                api_key=safe_api_key
            )
            
            if result.get('status') == 'success':
                logger.info(f"✅ Safe transaction executed successfully: {result.get('txHash')}")
            else:
                logger.error(f"❌ Safe transaction execution failed: {result.get('error')}")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Error executing Safe transaction: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def list_pending_transactions(self, limit: int = 10, offset: int = 0) -> Dict[str, Any]:
        """List pending Safe transactions"""
        try:
            if not self.initialized:
                raise Exception("API not initialized")
            
            if not self.safe_address:
                raise Exception("Safe address not set")
            
            # Get Safe API configuration from environment
            safe_api_url = os.getenv('SAFE_API_URL')
            safe_api_key = os.getenv('SAFE_TRANSACTION_SERVICE_API_KEY')
            
            if not safe_api_url:
                raise Exception("SAFE_API_URL environment variable not set")
            
            logger.info(f"📋 Listing pending transactions for Safe: {self.safe_address}")
            
            # List pending transactions using safe_utils
            result = list_safe_pending_transactions(
                safe_address=self.safe_address,
                safe_api_url=safe_api_url,
                api_key=safe_api_key,
                limit=limit,
                offset=offset
            )
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Error listing pending transactions: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def execute_position_with_tp_sl(
        self, 
        token: str, 
        size_usd: float, 
        leverage: int,
        take_profit_price: float,
        stop_loss_price: float,
        is_long: bool = True,
        auto_execute: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """Create a position with automatic Take Profit and Stop Loss orders with database tracking"""
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
            
            # Calculate amounts
            collateral_amount = Decimal(str(size_usd)) / Decimal(str(leverage))
            collateral_amount_wei = int(collateral_amount * Decimal(10**6))  # USDC has 6 decimals
            size_delta = int(collateral_amount * Decimal(str(leverage)) * Decimal(10**30))  # GMX uses 30 decimals
            
            logger.info(f"🎯 Creating position with TP/SL for {token}")
            logger.info(f"   Position: {'LONG' if is_long else 'SHORT'}")
            logger.info(f"   Size: ${size_usd} USD")
            logger.info(f"   Collateral: ${collateral_amount} USDC")
            logger.info(f"   Leverage: {leverage}x")
            logger.info(f"   Take Profit: ${take_profit_price}")
            logger.info(f"   Stop Loss: ${stop_loss_price}")
            logger.info(f"   Safe wallet: {self.safe_address}")
            
            # Check that Safe wallet has sufficient USDC
            if not self._ensure_safe_has_funds(float(collateral_amount)):
                raise Exception("Safe wallet has insufficient funds for trading")
            
            # Log position creation to database
            position_id = None
            if self.db_connected:
                position_id = gmx_db.log_order_creation(
                    safe_address=self.safe_address,
                    token=token.upper(),
                    order_type="tp_sl_position",
                    size_usd=size_usd,
                    leverage=leverage,
                    is_long=is_long,
                    signal_id=signal_id,
                    username=username,
                    market_key=token_config['market_key'],
                    index_token=token_config['index_token'],
                    collateral_token=token_config['collateral_token'],
                    original_signal=original_signal,
                    take_profit_price=take_profit_price,
                    stop_loss_price=stop_loss_price
                )
            
            # Parse order parameters
            parameters = {
                "chain": 'arbitrum',
                "index_token_symbol": token.upper(),
                "collateral_token_symbol": "USDC",
                "start_token_symbol": "USDC",
                "is_long": is_long,
                "size_delta_usd": size_usd,
                "leverage": leverage,
                "slippage_percent": 0.003
            }
            
            order_parameters = OrderArgumentParser(
                self.config,
                is_increase=True
            ).process_parameters_dictionary(parameters)
            
            # Create position with TP and SL
            position = PositionWithTPSL(
                config=self.config,
                market_key=order_parameters['market_key'],
                collateral_address=order_parameters['start_token_address'],
                index_token_address=order_parameters['index_token_address'],
                is_long=order_parameters['is_long'],
                size_delta=order_parameters['size_delta'],
                initial_collateral_delta_amount=order_parameters['initial_collateral_delta'],
                slippage_percent=order_parameters['slippage_percent'],
                swap_path=order_parameters['swap_path'],
                take_profit_price=take_profit_price,
                stop_loss_price=stop_loss_price,
                debug_mode=False,
                execution_buffer=1.3
            )
            
            # Get order summary
            summary = position.get_order_summary()
            
            # Extract Safe transaction info for all orders
            safe_info = {}
            safe_tx_hashes = []
            
            logger.info(f"🔍 Extracting Safe transaction info from PositionWithTPSL...")
            
            for order_type in ['main_order', 'take_profit_order', 'stop_loss_order']:
                # Map the order_type to the actual attribute names in PositionWithTPSL
                if order_type == 'main_order':
                    attr_name = 'main_order'
                elif order_type == 'take_profit_order':
                    attr_name = 'tp_order'
                elif order_type == 'stop_loss_order':
                    attr_name = 'sl_order'
                else:
                    attr_name = order_type.replace('_order', '')
                
                order_obj = getattr(position, attr_name, None)
                logger.info(f"🔍 Checking {order_type}: {order_obj}")
                
                if order_obj:
                    last_payload = getattr(order_obj, 'last_safe_tx_payload', None)
                    last_proposal = getattr(order_obj, 'last_safe_tx_proposal', None)
                    
                    logger.info(f"🔍 {order_type} - last_payload: {last_payload}")
                    logger.info(f"🔍 {order_type} - last_proposal: {last_proposal}")
                    
                    if last_payload or last_proposal:
                        safe_info[order_type] = {}
                        if last_payload:
                            safe_info[order_type]['to'] = last_payload.get('to')
                            safe_info[order_type]['data_len'] = len((last_payload.get('data') or '0x'))
                        if isinstance(last_proposal, dict):
                            safe_tx_hash = last_proposal.get('safeTxHash') or last_proposal.get('contractTransactionHash')
                            safe_info[order_type]['proposal'] = {
                                'safeTxHash': safe_tx_hash,
                                'url': last_proposal.get('url')
                            }
                            if safe_tx_hash:
                                safe_tx_hashes.append(safe_tx_hash)
                                logger.info(f"✅ Added {order_type} Safe TX hash: {safe_tx_hash}")
                                
                                # Log Safe transaction to database
                                if self.db_connected:
                                    gmx_db.log_safe_transaction_from_order(
                                        safe_tx_hash=safe_tx_hash,
                                        safe_address=self.safe_address,
                                        order_type=OrderType.MARKET_INCREASE if order_type == 'main_order' else OrderType.LIMIT_DECREASE,
                                        token=token.upper(),
                                        position_id=position_id,
                                        signal_id=signal_id,
                                        username=username,
                                        market_key=token_config['market_key']
                                    )
                    else:
                        logger.warning(f"⚠️ No Safe transaction info found for {order_type}")
                else:
                    logger.warning(f"⚠️ No order object found for {order_type}")
            
            logger.info(f"📊 Extracted {len(safe_tx_hashes)} Safe transaction hashes: {safe_tx_hashes}")
            
            # If no transaction hashes were extracted but auto_execute is requested,
            # try to extract them from the position object directly
            if auto_execute and len(safe_tx_hashes) == 0:
                logger.warning("⚠️ No Safe transaction hashes extracted, trying alternative method...")
                
                # Try to get transaction hashes directly from the position object
                for attr_name in ['main_order', 'tp_order', 'sl_order']:
                    order_obj = getattr(position, attr_name, None)
                    if order_obj:
                        # Try different attribute names
                        for attr in ['last_safe_tx_proposal', 'safe_tx_proposal', 'proposal']:
                            proposal = getattr(order_obj, attr, None)
                            if isinstance(proposal, dict):
                                safe_tx_hash = proposal.get('safeTxHash') or proposal.get('contractTransactionHash')
                                if safe_tx_hash:
                                    safe_tx_hashes.append(safe_tx_hash)
                                    logger.info(f"✅ Found {attr_name} Safe TX hash via {attr}: {safe_tx_hash}")
                                    break
                
                logger.info(f"📊 After fallback: {len(safe_tx_hashes)} Safe transaction hashes: {safe_tx_hashes}")
            
            result = {
                'status': 'success',
                'message': 'Position with TP/SL created successfully',
                'position': {
                    'token': token.upper(),
                    'type': 'LONG' if is_long else 'SHORT',
                    'size_usd': size_usd,
                    'collateral_usd': float(collateral_amount),
                    'leverage': leverage,
                    'take_profit_price': take_profit_price,
                    'stop_loss_price': stop_loss_price
                },
                'orders_created': summary['orders_created'],
                'safe_wallet': self.safe_address,
                'safe': safe_info,
                'position_id': position_id,
                'note': 'Position will exit automatically at TP or SL levels - no monitoring required',
                'timestamp': datetime.now().isoformat()
            }
            
            # Auto-execute all transactions if requested
            logger.info(f"🔍 Auto-execute check: auto_execute={auto_execute}, safe_tx_hashes count={len(safe_tx_hashes)}")
            if auto_execute and safe_tx_hashes:
                logger.info(f"🚀 Auto-executing {len(safe_tx_hashes)} Safe transactions for TP/SL position")
                
                execution_results = {}
                successful_executions = 0
                failed_executions = 0
                
                # Execute all transactions (main position, TP order, SL order)
                for i, safe_tx_hash in enumerate(safe_tx_hashes):
                    order_type = list(safe_info.keys())[i] if i < len(safe_info) else f'order_{i}'
                    logger.info(f"🚀 Auto-executing {order_type}: {safe_tx_hash}")
                    
                    execution_result = self.execute_safe_transaction(safe_tx_hash)
                    execution_results[order_type] = execution_result
                    
                    if execution_result.get('status') == 'success':
                        successful_executions += 1
                        # Update safe_info with execution details
                        if order_type in safe_info:
                            safe_info[order_type]['executed'] = True
                            safe_info[order_type]['execution_tx_hash'] = execution_result.get('txHash')
                            safe_info[order_type]['execution_message'] = f'{order_type} executed successfully'
                        logger.info(f"✅ {order_type} executed successfully: {execution_result.get('txHash')}")
                    else:
                        failed_executions += 1
                        # Update safe_info with error details
                        if order_type in safe_info:
                            safe_info[order_type]['execution_error'] = execution_result.get('error')
                            safe_info[order_type]['execution_message'] = f'{order_type} execution failed'
                        logger.warning(f"⚠️ {order_type} execution failed: {execution_result.get('error')}")
                
                # Create comprehensive execution summary
                if successful_executions == len(safe_tx_hashes):
                    result['execution'] = {
                        'status': 'success',
                        'message': f'All {len(safe_tx_hashes)} transactions executed successfully',
                        'executed_count': successful_executions,
                        'total_count': len(safe_tx_hashes),
                        'execution_results': execution_results
                    }
                elif successful_executions > 0:
                    result['execution'] = {
                        'status': 'partial_success',
                        'message': f'{successful_executions}/{len(safe_tx_hashes)} transactions executed successfully',
                        'executed_count': successful_executions,
                        'failed_count': failed_executions,
                        'total_count': len(safe_tx_hashes),
                        'execution_results': execution_results
                    }
                else:
                    result['execution'] = {
                        'status': 'error',
                        'message': f'All {len(safe_tx_hashes)} transactions failed to execute',
                        'failed_count': failed_executions,
                        'total_count': len(safe_tx_hashes),
                        'execution_results': execution_results
                    }
                
                logger.info(f"📊 Execution summary: {successful_executions}/{len(safe_tx_hashes)} transactions executed successfully")
            
            # Update position status in database if execution seems successful
            if self.db_connected and position_id:
                gmx_db.update_position_from_execution(
                    position_id=position_id,
                    execution_result=result,
                    safe_tx_hash=safe_tx_hashes[0] if safe_tx_hashes else None
                )
            
            logger.info("✅ Position with TP/SL created successfully!")
            logger.info("📈 Position will automatically exit at TP or SL levels")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Error creating position with TP/SL: {e}")
            
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

    def execute_position_with_tp_sl_sequential(
        self, 
        token: str, 
        size_usd: float, 
        leverage: int,
        take_profit_price: float,
        stop_loss_price: float,
        is_long: bool = True,
        auto_execute: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """Create a position with sequential execution: Approval → Buy → TP → SL"""
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
            
            # Calculate amounts
            collateral_amount = Decimal(str(size_usd)) / Decimal(str(leverage))
            collateral_amount_usd = float(collateral_amount)
            
            logger.info(f"🎯 Starting SEQUENTIAL position creation with TP/SL for {token}")
            logger.info(f"   Position: {'LONG' if is_long else 'SHORT'}")
            logger.info(f"   Size: ${size_usd} USD")
            logger.info(f"   Collateral: ${collateral_amount_usd} USDC")
            logger.info(f"   Leverage: {leverage}x")
            logger.info(f"   Take Profit: ${take_profit_price}")
            logger.info(f"   Stop Loss: ${stop_loss_price}")
            logger.info(f"   Auto-execute: {auto_execute}")
            
            # Check that Safe wallet has sufficient USDC
            if not self._ensure_safe_has_funds(collateral_amount_usd):
                raise Exception("Safe wallet has insufficient funds for trading")
            
            # Log position creation to database
            position_id = None
            if self.db_connected:
                position_id = gmx_db.log_order_creation(
                    safe_address=self.safe_address,
                    token=token.upper(),
                    order_type="tp_sl_position_sequential",
                    size_usd=size_usd,
                    leverage=leverage,
                    is_long=is_long,
                    signal_id=signal_id,
                    username=username,
                    market_key=token_config['market_key'],
                    index_token=token_config['index_token'],
                    collateral_token=token_config['collateral_token'],
                    original_signal=original_signal,
                    take_profit_price=take_profit_price,
                    stop_loss_price=stop_loss_price
                )
            
            sequential_results = {}
            
            # STEP 1: Create Buy Order (Main Position) - this will handle approvals automatically
            logger.info("💰 STEP 1: Creating Buy order...")
            
            # Set auto_execute_approvals in config for approval transactions
            original_auto_execute = getattr(self.config, 'auto_execute_approvals', False)
            if auto_execute:
                self.config.auto_execute_approvals = True
            
            try:
                # Create the buy order with auto_execute=False to check for approvals first
                buy_order_result = self.execute_buy_order(
                    token=token,
                    size_usd=size_usd,
                    leverage=leverage,
                    auto_execute=False,  # Don't auto-execute yet, need to handle approvals first
                    signal_id=signal_id,
                    username=username,
                    original_signal=original_signal
                )
            finally:
                # Always reset config to original state
                self.config.auto_execute_approvals = original_auto_execute
            sequential_results['buy_order'] = buy_order_result
            
            if buy_order_result.get('status') != 'success':
                raise Exception(f"Buy order failed: {buy_order_result.get('error')}")
            
            # Check if approval transaction was created during buy order
            logger.info("🔍 Checking if approval transaction was created during buy order...")
            approval_executed = self.execute_pending_approval_transactions()
            
            if approval_executed:
                logger.info("⏳ Waiting for approval transaction to confirm...")
                time.sleep(15)  # Wait for blockchain confirmation
            
            # Now execute the buy order if auto_execute is enabled
            buy_safe_tx_hash = None
            if buy_order_result.get('safe', {}).get('safeTxHash'):
                buy_safe_tx_hash = buy_order_result['safe']['safeTxHash']
                
                if auto_execute and buy_safe_tx_hash:
                    logger.info("⏳ Waiting for transaction to be processed by Safe API...")
                    time.sleep(15)  # Wait for Safe Transaction Service to process the proposal
                    
                    logger.info("🚀 Auto-executing Buy order...")
                    execution_result = self.execute_safe_transaction(buy_safe_tx_hash)
                    if execution_result.get('status') == 'success':
                        buy_order_result['execution'] = {
                            'status': 'success',
                            'txHash': execution_result.get('txHash'),
                            'message': 'Buy order executed successfully'
                        }
                        logger.info("✅ Buy order executed successfully")
                    else:
                        buy_order_result['execution'] = {
                            'status': 'error',
                            'error': execution_result.get('error'),
                            'message': 'Buy order execution failed'
                        }
                        logger.error(f"❌ Buy order execution failed: {execution_result.get('error')}")
            
            # Wait for buy order to execute if auto-executed
            if auto_execute and buy_order_result.get('execution', {}).get('status') == 'success':
                logger.info("⏳ Waiting for buy order to execute...")
                time.sleep(15)  # Wait for position to open
            
            # STEP 2: Create Take Profit Order
            logger.info("📈 STEP 2: Creating Take Profit order...")
            tp_order_result = self._create_take_profit_order(
                token=token,
                size_usd=size_usd,
                trigger_price=take_profit_price,
                is_long=is_long,
                auto_execute=auto_execute,
                position_id=position_id,
                signal_id=signal_id,
                username=username
            )
            sequential_results['take_profit_order'] = tp_order_result
            
            if tp_order_result.get('status') != 'success':
                logger.warning(f"⚠️ Take Profit order failed: {tp_order_result.get('error')}")
            
            # STEP 3: Create Stop Loss Order
            logger.info("📉 STEP 3: Creating Stop Loss order...")
            sl_order_result = self._create_stop_loss_order(
                token=token,
                size_usd=size_usd,
                trigger_price=stop_loss_price,
                is_long=is_long,
                auto_execute=auto_execute,
                position_id=position_id,
                signal_id=signal_id,
                username=username
            )
            sequential_results['stop_loss_order'] = sl_order_result
            
            if sl_order_result.get('status') != 'success':
                logger.warning(f"⚠️ Stop Loss order failed: {sl_order_result.get('error')}")
            
            # Compile final result
            result = {
                'status': 'success',
                'message': 'Sequential position creation completed',
                'position': {
                    'token': token.upper(),
                    'type': 'LONG' if is_long else 'SHORT',
                    'size_usd': size_usd,
                    'collateral_usd': collateral_amount_usd,
                    'leverage': leverage,
                    'take_profit_price': take_profit_price,
                    'stop_loss_price': stop_loss_price
                },
                'sequential_results': sequential_results,
                'safe_wallet': self.safe_address,
                'position_id': position_id,
                'flow_completed': True,
                'timestamp': datetime.now().isoformat()
            }
            
            # Add execution summary
            executed_steps = 0
            total_steps = 3
            
            if sequential_results['buy_order'].get('execution', {}).get('status') == 'success':
                executed_steps += 1
            if sequential_results['take_profit_order'].get('execution', {}).get('status') == 'success':
                executed_steps += 1
            if sequential_results['stop_loss_order'].get('execution', {}).get('status') == 'success':
                executed_steps += 1
            
            # Also count successful buy order creation even if not auto-executed
            if sequential_results['buy_order'].get('status') == 'success' and not sequential_results['buy_order'].get('execution'):
                executed_steps += 1
            
            result['execution_summary'] = {
                'executed_steps': executed_steps,
                'total_steps': total_steps,
                'success_rate': f"{executed_steps}/{total_steps}"
            }
            
            logger.info(f"✅ Sequential position creation completed! ({executed_steps}/{total_steps} steps executed)")
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Error in sequential position creation: {e}")
            
            # Log failure to database
            if self.db_connected and position_id:
                transaction_tracker.update_position_status(
                    position_id=position_id,
                    status=PositionStatus.FAILED
                )
            
            return {
                'status': 'error',
                'error': str(e),
                'position_id': position_id,
                'timestamp': datetime.now().isoformat()
            }

    def _create_take_profit_order(
        self,
        token: str,
        size_usd: float,
        trigger_price: float,
        is_long: bool,
        auto_execute: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """Create a Take Profit order"""
        try:
            if not self.initialized:
                raise Exception("API not initialized")
            
            token_config = self.supported_tokens.get(token.upper())
            if not token_config:
                raise Exception(f"Token {token} not supported")
            
            # Extract additional parameters
            signal_id = kwargs.get('signal_id')
            username = kwargs.get('username', 'api_user')
            position_id = kwargs.get('position_id')
            
            # Calculate order parameters
            size_delta = int(Decimal(str(size_usd)) * Decimal(10**30))
            collateral_to_withdraw = int(Decimal(str(size_usd)) * Decimal(10**6))  # Withdraw full collateral for TP
            
            logger.info(f"🎯 Creating Take Profit order for {token} at ${trigger_price}")
            
            # Create take profit order
            order = TakeProfitOrder(
                trigger_price=float(trigger_price),
                config=self.config,
                market_key=token_config['market_key'],
                collateral_address=token_config['collateral_token'],
                index_token_address=token_config['index_token'],
                is_long=is_long,
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
                        order_type=OrderType.LIMIT_DECREASE,
                        token=token.upper(),
                        position_id=position_id,
                        signal_id=signal_id,
                        username=username,
                        market_key=token_config['market_key']
                    )
            
            # Auto-execute if requested
            if auto_execute and safe_tx_hash:
                logger.info(f"⏳ Waiting for transaction to be processed by Safe API...")
                time.sleep(15)  # Wait for Safe Transaction Service to process the proposal
                
                logger.info(f"🚀 Auto-executing Take Profit order: {safe_tx_hash}")
                execution_result = self.execute_safe_transaction(safe_tx_hash)
                if execution_result.get('status') == 'success':
                    safe_info['executed'] = True
                    safe_info['execution_tx_hash'] = execution_result.get('txHash')
                    safe_info['execution_message'] = 'Take Profit order executed successfully'
                else:
                    safe_info['execution_error'] = execution_result.get('error')
                    safe_info['execution_message'] = 'Take Profit order execution failed'
            
            return {
                'status': 'success',
                'order_type': 'take_profit',
                'token': token,
                'trigger_price': trigger_price,
                'size_usd': size_usd,
                'safe': safe_info,
                'order': str(order),
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Error creating Take Profit order: {e}")
            return {
                'status': 'error',
                'order_type': 'take_profit',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }

    def _create_stop_loss_order(
        self,
        token: str,
        size_usd: float,
        trigger_price: float,
        is_long: bool,
        auto_execute: bool = False,
        **kwargs
    ) -> Dict[str, Any]:
        """Create a Stop Loss order"""
        try:
            if not self.initialized:
                raise Exception("API not initialized")
            
            token_config = self.supported_tokens.get(token.upper())
            if not token_config:
                raise Exception(f"Token {token} not supported")
            
            # Extract additional parameters
            signal_id = kwargs.get('signal_id')
            username = kwargs.get('username', 'api_user')
            position_id = kwargs.get('position_id')
            
            # Calculate order parameters
            size_delta = int(Decimal(str(size_usd)) * Decimal(10**30))
            collateral_to_withdraw = int(Decimal(str(size_usd)) * Decimal(10**6))  # Withdraw full collateral for SL
            
            logger.info(f"🎯 Creating Stop Loss order for {token} at ${trigger_price}")
            
            # Create stop loss order
            order = StopLossOrder(
                trigger_price=float(trigger_price),
                config=self.config,
                market_key=token_config['market_key'],
                collateral_address=token_config['collateral_token'],
                index_token_address=token_config['index_token'],
                is_long=is_long,
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
                        order_type=OrderType.LIMIT_DECREASE,
                        token=token.upper(),
                        position_id=position_id,
                        signal_id=signal_id,
                        username=username,
                        market_key=token_config['market_key']
                    )
            
            # Auto-execute if requested
            if auto_execute and safe_tx_hash:
                logger.info(f"⏳ Waiting for transaction to be processed by Safe API...")
                time.sleep(15)  # Wait for Safe Transaction Service to process the proposal
                
                logger.info(f"🚀 Auto-executing Stop Loss order: {safe_tx_hash}")
                execution_result = self.execute_safe_transaction(safe_tx_hash)
                if execution_result.get('status') == 'success':
                    safe_info['executed'] = True
                    safe_info['execution_tx_hash'] = execution_result.get('txHash')
                    safe_info['execution_message'] = 'Stop Loss order executed successfully'
                else:
                    safe_info['execution_error'] = execution_result.get('error')
                    safe_info['execution_message'] = 'Stop Loss order execution failed'
            
            return {
                'status': 'success',
                'order_type': 'stop_loss',
                'token': token,
                'trigger_price': trigger_price,
                'size_usd': size_usd,
                'safe': safe_info,
                'order': str(order),
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Error creating Stop Loss order: {e}")
            return {
                'status': 'error',
                'order_type': 'stop_loss',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def process_signal_with_database(self, signal_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process trading signal with full database integration"""
        try:
            # Extract safe_address from signal
            safe_address = signal_data.get('safeAddress')
            if not safe_address:
                raise Exception("safeAddress is required in signal data")
            
            # Initialize API with safe_address from signal if not already initialized
            if not self.initialized or self.safe_address != safe_address:
                logger.info(f"🔄 Re-initializing API with Safe address from signal: {safe_address}")
                self.initialize(safe_address=safe_address)
            
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
            
            # Check for auto_execute in signal data
            auto_execute = signal_data.get('autoExecute', False)
            
            if signal_type in ['buy', 'long']:
                result = self.execute_buy_order(
                    token=token, 
                    size_usd=10.00, 
                    leverage=1, 
                    auto_execute=auto_execute,
                    **kwargs
                )
            elif signal_type in ['sell', 'short']:
                result = self.execute_sell_order(
                    token=token, 
                    auto_execute=auto_execute,
                    **kwargs
                )
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
        size_usd = float(data.get('size_usd', 10.00))
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
            
            # Validate safe_address is present
            if not safe_address:
                return jsonify({
                    'status': 'error',
                    'error': 'safeAddress is required in signal data'
                }), 400
            
            # Validate required signal fields
            if not signal_message:
                return jsonify({
                    'status': 'error',
                    'error': 'Signal Message is required'
                }), 400
                
            if not token:
                return jsonify({
                    'status': 'error',
                    'error': 'Token Mentioned is required'
                }), 400
                
            if tp1 is None:
                return jsonify({
                    'status': 'error',
                    'error': 'TP1 is required'
                }), 400
                
            if sl is None:
                return jsonify({
                    'status': 'error',
                    'error': 'SL is required'
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
            
            # Default trading parameters for signals (same as normal orders)
            size_usd = 10.00  # Default size for signals (matches normal orders)
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
            size_usd = float(data.get('size_usd', 10.00))  # Default matches normal orders
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
            # Log signal to database first
            signal_id = ""
            if gmx_api.db_connected:
                signal_id = gmx_db.log_signal_processing(
                    signal_data=data,
                    username=username,
                    api_endpoint='/position/create-with-tp-sl'
                )
                kwargs['signal_id'] = signal_id
        
        # Check for execution mode parameters
        auto_execute = data.get('autoExecute', False)
        sequential_execution = data.get('sequentialExecution', True)  # Default to new sequential flow
        
        logger.info(f"🔄 Using {'sequential' if sequential_execution else 'batch'} execution mode")
        
        # Choose execution method based on parameter
        if sequential_execution:
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
        else:
            # Use original batch method for backward compatibility
            result = gmx_api.execute_position_with_tp_sl(
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
            
            # Validate safe_address is present
            if not safe_address:
                return jsonify({
                    'status': 'error',
                    'error': 'safeAddress is required in signal data'
                }), 400
            
            # Validate required signal fields
            if not signal_message:
                return jsonify({
                    'status': 'error',
                    'error': 'Signal Message is required'
                }), 400
                
            if not token:
                return jsonify({
                    'status': 'error',
                    'error': 'Token Mentioned is required'
                }), 400
                
            if tp1 is None:
                return jsonify({
                    'status': 'error',
                    'error': 'TP1 is required for Take Profit order'
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
            
            # Default trading parameters for signals (same as normal orders)
            size_usd = 10.00  # Default size for signals (matches normal orders)
            
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
            
            # Validate required parameters
            if not token:
                return jsonify({
                    'status': 'error',
                    'error': 'token is required'
                }), 400
                
            if trigger_price is None:
                return jsonify({
                    'status': 'error',
                    'error': 'trigger_price is required'
                }), 400
                
            if size_usd is None:
                return jsonify({
                    'status': 'error',
                    'error': 'size_usd is required'
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
        if 'Signal Message' in data and gmx_api.db_connected:
            signal_id = gmx_db.log_signal_processing(
                signal_data=data,
                username=username,
                api_endpoint='/tp-order'
            )
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
        # Get positions from database if connected
        if gmx_api.db_connected:
            active_positions = transaction_tracker.get_active_positions(gmx_api.safe_address)
            return jsonify({
                'status': 'success',
                'positions': active_positions,
                'timestamp': datetime.now().isoformat()
            })
        else:
            return jsonify({
                'status': 'error',
                'error': 'Database not connected',
                'timestamp': datetime.now().isoformat()
            }), 500
        
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

@app.route('/safe/test', methods=['GET'])
def test_safe_api():
    """Test Safe API connection and diagnose issues"""
    try:
        if not gmx_api.initialized:
            return jsonify({
                'status': 'error',
                'error': 'API not initialized'
            }), 400
        
        from gmx_python_sdk.scripts.v2.safe_utils import test_safe_api_connection
        
        safe_api_url = os.getenv('SAFE_API_URL')
        safe_api_key = os.getenv('SAFE_TRANSACTION_SERVICE_API_KEY')
        
        if not safe_api_url:
            return jsonify({
                'status': 'error',
                'error': 'SAFE_API_URL not configured',
                'suggestion': 'Set SAFE_API_URL environment variable'
            }), 400
        
        safe_api_key = os.getenv('SAFE_TRANSACTION_SERVICE_API_KEY')
        result = test_safe_api_connection(
            safe_address=gmx_api.safe_address,
            safe_api_url=safe_api_url,
            api_key=safe_api_key  # Use API key from environment
        )
        
        return jsonify({
            **result,
            'config': {
                'safe_address': gmx_api.safe_address,
                'safe_api_url': safe_api_url,
                'api_key_provided': bool(safe_api_key)
            },
            'timestamp': datetime.now().isoformat()
        })
        
    except Exception as e:
        logger.error(f"❌ Error testing Safe API: {e}")
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

@app.route('/wallet-info', methods=['GET'])
def wallet_info():
    """Get information about Safe wallet and signer address"""
    try:
        if not gmx_api.initialized:
            return jsonify({
                'status': 'error',
                'error': 'API not initialized'
            }), 400
        
        # Check Safe wallet balance
        try:
            w3 = Web3(Web3.HTTPProvider(gmx_api.rpc_url))
            usdc_abi = [{"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"}]
            usdc_contract = w3.eth.contract(address=gmx_api.usdc_address, abi=usdc_abi)
            
            safe_balance = usdc_contract.functions.balanceOf(gmx_api.safe_address).call()
            eth_balance = w3.eth.get_balance(gmx_api.safe_address)
            
            return jsonify({
                'status': 'success',
                'architecture': 'Safe wallet funds used directly, private key for signing only',
                'safe_wallet': {
                    'address': gmx_api.safe_address,
                    'usdc_balance': safe_balance / 10**6,
                    'eth_balance': float(Web3.from_wei(eth_balance, 'ether')),
                    'role': 'Funds source and trading account'
                },
                'signer': {
                    'address': gmx_api.private_key_address,
                    'role': 'Transaction signing only'
                },
                'note': 'No fund transfers needed - trades execute directly from Safe wallet',
                'timestamp': datetime.now().isoformat()
            })
            
        except Exception as balance_error:
            return jsonify({
                'status': 'success',
                'architecture': 'Safe wallet funds used directly, private key for signing only',
                'safe_wallet': {
                    'address': gmx_api.safe_address,
                    'role': 'Funds source and trading account'
                },
                'signer': {
                    'address': gmx_api.private_key_address,
                    'role': 'Transaction signing only'
                },
                'note': f'Balance check failed: {balance_error}',
                'timestamp': datetime.now().isoformat()
            })
        
    except Exception as e:
        logger.error(f"❌ Error getting wallet info: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500
        
# Add database-specific routes
add_database_routes(app)

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