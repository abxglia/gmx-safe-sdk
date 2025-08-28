#!/usr/bin/env python3
"""
GMX Safe API Server
Python Flask API that processes trading signals and executes GMX trades using Safe wallet funds directly,
with private key used only for signing transactions
"""

import os
import sys
import time
import logging
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
from eth_abi import encode

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables from .env file
load_dotenv()
logger.info("🔧 Environment variables loaded from .env file")

app = Flask(__name__)
CORS(app)

class SimplifiedGMXAPI:
    def __init__(self):
        self.initialized = False
        
        # Configuration from environment
        self.safe_address = os.getenv('SAFE_ADDRESS')  # Safe wallet address (funds source)
        self.private_key = os.getenv('PRIVATE_KEY')    # Your private key (for signing)
        self.rpc_url = os.getenv('RPC_URL', 'https://arb1.arbitrum.io/rpc')
        
        # GMX and Safe configuration
        self.config = None
        self.safe = None
        self.ethereum_client = None
        self.current_positions = {}
        
        # GMX V2 addresses
        self.gmx_exchange_router = "0x7452c558d45f8afC8c83dAe62C3f8A5BE19c71f6"
        self.usdc_address = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
        
        # Token mapping (same as BTCUSDC.py)
        self.supported_tokens = {
            'BTC': {
                'market_key': '0x47c031236e19d024b42f8AE6780E44A573170703',
                'index_token': '0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f',  # WBTC
                'collateral_token': '0xaf88d065e77c8cC2239327C5EDb3A432268e5831'  # USDC
            },
            'ETH': {
                'market_key': '0x70d95587d40A2caf56bd97485aB3Eec10Bee6336',
                'index_token': '0x82aF49447D8a07e3bd95BD0d56f35241523fBab1',  # WETH
                'collateral_token': '0xaf88d065e77c8cC2239327C5EDb3A432268e5831'  # USDC
            }
        }
    
    def initialize(self):
        """Initialize GMX and Safe configuration"""
        try:
            # Get the address that corresponds to the private key
            from web3 import Web3
            w3 = Web3()
            private_key_address = w3.eth.account.from_key(self.private_key).address
            
            logger.info(f"🔍 Address derived from private key: {private_key_address}")
            logger.info(f"🔍 Safe wallet address: {self.safe_address}")
            
            # Initialize Safe SDK
            self.ethereum_client = EthereumClient(self.rpc_url)
            self.safe = Safe(self.safe_address, self.ethereum_client)
            
            # Initialize GMX SDK config to use Safe wallet funds with private key signing
            self.config = ConfigManager(chain='arbitrum')
            self.config.set_rpc(self.rpc_url)
            self.config.set_chain_id(42161)
            self.config.set_wallet_address(self.safe_address)    # Use Safe address for funds
            self.config.set_private_key(self.private_key)        # Private key for signing orders
            # Route transactions through Safe and read balances from Safe address
            try:
                safe_api_url = os.getenv('SAFE_API_URL')
                safe_api_key = os.getenv('SAFE_TRANSACTION_SERVICE_API_KEY')  # Use API key like working implementation
                
                self.config.enable_safe_transactions(
                    safe_address=self.safe_address,
                    safe_api_url=safe_api_url,
                    safe_api_key=safe_api_key
                )
                logger.info("✅ Safe transactions enabled in GMX config")
                if safe_api_url:
                    auth_status = "with API key" if safe_api_key else "without auth"
                    logger.info(f"🔗 Safe API integration enabled: {safe_api_url} ({auth_status})")
                else:
                    logger.info("💡 No Safe API URL provided - transactions will be saved as JSON payloads")
            except Exception as e:
                logger.warning(f"⚠️ Could not enable Safe transactions: {e}")
            
            # Store both addresses for reference
            self.private_key_address = private_key_address
            
            # Check USDC balance on Safe wallet
            try:
                w3_provider = Web3(Web3.HTTPProvider(self.rpc_url))
                usdc_abi = [{"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"}]
                usdc_contract = w3_provider.eth.contract(address=self.usdc_address, abi=usdc_abi)
                
                safe_balance = usdc_contract.functions.balanceOf(self.safe_address).call()
                eth_balance = w3_provider.eth.get_balance(self.safe_address)
                
                logger.info(f"💰 Safe Wallet Balance Check:")
                logger.info(f"   USDC Balance: {safe_balance / 10**6} USDC")
                logger.info(f"   ETH Balance: {Web3.from_wei(eth_balance, 'ether')} ETH")
                
                if safe_balance < 1010000:  # Less than 1.01 USDC
                    logger.warning(f"⚠️ WARNING: Safe wallet has insufficient USDC for trading!")
                    logger.warning(f"   Required: 1.01 USDC, Available: {safe_balance / 10**6} USDC")
                    
            except Exception as balance_error:
                logger.warning(f"⚠️ Could not check balances: {balance_error}")
            
            self.initialized = True
            logger.info("✅ GMX Safe API initialized successfully")
            logger.info(f"   Safe wallet (funds & trading): {self.safe_address}")
            logger.info(f"   Private key (signing only): {private_key_address}")
            logger.info(f"   RPC: {self.rpc_url}")
            logger.info("📋 Trading Strategy: Use Safe wallet funds directly → Execute GMX trades with private key signing → Profits stay in Safe")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize: {e}")
            return False
    
    def _ensure_safe_has_funds(self, required_usdc: float) -> bool:
        """Check if Safe wallet has sufficient USDC for trading"""
        try:
            w3 = Web3(Web3.HTTPProvider(self.rpc_url))
            usdc_abi = [{"constant": True, "inputs": [{"name": "_owner", "type": "address"}], "name": "balanceOf", "outputs": [{"name": "balance", "type": "uint256"}], "type": "function"}]
            usdc_contract = w3.eth.contract(address=self.usdc_address, abi=usdc_abi)
            
            safe_balance = usdc_contract.functions.balanceOf(self.safe_address).call()
            required_wei = int(required_usdc * 10**6)
            
            logger.info(f"💰 Safe Wallet Fund Check:")
            logger.info(f"   Safe balance: {safe_balance / 10**6} USDC")
            logger.info(f"   Required for trade: {required_usdc} USDC")
            
            if safe_balance >= required_wei:
                logger.info("✅ Sufficient funds available in Safe wallet")
                return True
            else:
                logger.error(f"❌ Insufficient funds in Safe wallet!")
                logger.error(f"   Required: {required_usdc} USDC, Available: {safe_balance / 10**6} USDC")
                return False
            
        except Exception as e:
            logger.error(f"❌ Error checking Safe wallet funds: {e}")
            return False
    
    
    def execute_buy_order(self, token: str, size_usd: float, leverage: int = 2) -> Dict[str, Any]:
        """Execute a buy order using Safe wallet funds directly with private key for signing"""
        try:
            if not self.initialized:
                raise Exception("API not initialized")
            
            token_config = self.supported_tokens.get(token.upper())
            if not token_config:
                raise Exception(f"Token {token} not supported")
            
            # Calculate amounts (exactly like BTCUSDC.py)
            collateral_amount = Decimal(str(size_usd)) / Decimal(str(leverage))
            collateral_amount_wei = int(collateral_amount * Decimal(10**6))  # USDC has 6 decimals
            size_delta = int(collateral_amount * Decimal(str(leverage)) * Decimal(10**30))  # GMX uses 30 decimals
            
            logger.info(f"📈 Executing BUY order for {token} using Safe wallet funds")
            logger.info(f"   Size: ${size_usd} USD")
            logger.info(f"   Collateral: ${collateral_amount} USDC") 
            logger.info(f"   Leverage: {leverage}x")
            logger.info(f"   Safe wallet (funds): {self.safe_address}")
            logger.info(f"   Signer (private key): {self.private_key_address}")
            
            # Step 1: Check that Safe wallet has sufficient USDC
            if not self._ensure_safe_has_funds(float(collateral_amount)): 
                raise Exception("Safe wallet has insufficient funds for trading")
            
            # Step 2: Execute GMX order using Safe wallet funds with private key signing
            order = IncreaseOrder(
                config=self.config,  # Configured with Safe address for funds, private key for signing
                market_key=token_config['market_key'],
                collateral_address=token_config['collateral_token'],
                index_token_address=token_config['index_token'],
                is_long=True,
                size_delta=size_delta,
                initial_collateral_delta_amount=collateral_amount_wei,
                slippage_percent=0.005,  # 0.5% slippage
                swap_path=[],
                debug_mode=False  # Ensure approvals are handled and Safe payloads are generated
            )

            # Access all attributes available in the config object for debugging and clarity
            config_data = getattr(order, 'config', None)
            config_attributes = {}
            if config_data:
                # dir() lists all attributes, filter out special/magic methods
                for attr in dir(config_data):
                    if not attr.startswith('__') and not callable(getattr(config_data, attr)):
                        config_attributes[attr] = getattr(config_data, attr)
                logger.info("🔍 Config object attributes:")
                for key, value in config_attributes.items():
                    logger.info(f"   {key}: {value}")
            else:
                logger.warning("⚠️ No config data found in order object.")
            
            config_chain = getattr(config_data, 'chain', None)
            config_chain_id = getattr(config_data, 'chain_id', None)
            config_private_key = getattr(config_data, 'private_key', None)
            config_rpc = getattr(config_data, 'rpc', None)
            config_user_wallet_address = getattr(config_data, 'user_wallet_address', None)

            print(f"Config data: {config_data}")
            print(f"Config chain: {config_chain}")
            print(f"Config chain_id: {config_chain_id}")
            print(f"Config private_key: {config_private_key}")
            print(f"Config rpc: {config_rpc}")

            # Destructure order object attributes for easier access and clarity
            order_data = getattr(order, 'config', None)
            order_market_key = getattr(order, 'market_key', None)
            order_collateral_address = getattr(order, 'collateral_address', None)
            order_index_token_address = getattr(order, 'index_token_address', None)
            order_is_long = getattr(order, 'is_long', None)
            order_size_delta = getattr(order, 'size_delta', None)
            order_initial_collateral_delta_amount = getattr(order, 'initial_collateral_delta_amount', None)
            order_slippage_percent = getattr(order, 'slippage_percent', None)
            order_swap_path = getattr(order, 'swap_path', None)
            order_debug_mode = getattr(order, 'debug_mode', None)

            print(f"Order: {order}")
            print(f"Order data: {order_data}")
            print(f"Order market_key: {order_market_key}")
            print(f"Order collateral_address: {order_collateral_address}")
            print(f"Order index_token_address: {order_index_token_address}")
            print(f"Order is_long: {order_is_long}")
            print(f"Order size_delta: {order_size_delta}")
            print(f"Order initial_collateral_delta_amount: {order_initial_collateral_delta_amount}")
            print(f"Order slippage_percent: {order_slippage_percent}")
            print(f"Order swap_path: {order_swap_path}")
            print(f"Order debug_mode: {order_debug_mode}")

            # Store position info for later selling
            position_key = f"{token}_LONG"
            self.current_positions[position_key] = {
                'market_key': token_config['market_key'],
                'collateral_address': token_config['collateral_token'],
                'index_token_address': token_config['index_token'],
                'is_long': True,
                'size_delta': size_delta,
                'collateral_amount': collateral_amount_wei,
                'token': token
            }
            
            logger.info("✅ Buy order executed successfully using Safe wallet funds!")
            logger.info("💡 Funds used directly from Safe wallet, order signed with private key")
            
            # Attach Safe proposal info if present
            safe_info = {}
            last_payload = getattr(order, 'last_safe_tx_payload', None)
            last_proposal = getattr(order, 'last_safe_tx_proposal', None)
            if last_payload:
                safe_info['payload_file'] = None
                try:
                    # Will be visible in server logs from earlier step
                    safe_info['to'] = last_payload.get('to')
                    safe_info['value'] = last_payload.get('value')
                    safe_info['data_len'] = len((last_payload.get('data') or '0x'))
                except Exception:
                    pass
            if isinstance(last_proposal, dict):
                safe_info['proposal'] = {
                    'safeTxHash': last_proposal.get('safeTxHash') or last_proposal.get('contractTransactionHash'),
                    'url': last_proposal.get('url')
                }
            
            return {
                'status': 'success',
                'order': str(order),
                'token': token,
                'size_usd': size_usd,
                'leverage': leverage,
                'position_type': 'LONG',
                'safe_wallet': self.safe_address,
                'signer_address': self.private_key_address,
                'safe': safe_info,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Error executing buy order: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def execute_sell_order(self, token: str, size_usd: float = None) -> Dict[str, Any]:
        """Execute a sell order using Safe wallet funds directly with private key for signing"""
        try:
            if not self.initialized:
                raise Exception("API not initialized")
            
            position_key = f"{token.upper()}_LONG"
            position = self.current_positions.get(position_key)
            
            if not position:
                raise Exception(f"No open {token} position found to close")
            
            # Use provided size or close entire position
            if size_usd:
                size_delta = int(Decimal(str(size_usd)) * Decimal(10**30))
                collateral_to_withdraw = int(Decimal(str(size_usd)) * Decimal(10**6))  # Partial withdrawal
            else:
                size_delta = position['size_delta']  # Close entire position
                collateral_to_withdraw = position['collateral_amount']  # Withdraw all collateral
            
            logger.info(f"📉 Executing SELL order for {token} using Safe wallet")
            logger.info(f"   Size to close: ${size_usd or 'ALL'} USD")
            logger.info(f"   Safe wallet: {self.safe_address}")
            logger.info(f"   Signer: {self.private_key_address}")
            
            # Execute GMX order using Safe wallet funds with private key signing
            order = DecreaseOrder(
                config=self.config,  # Configured with Safe address for funds, private key for signing
                market_key=position['market_key'],
                collateral_address=position['collateral_address'],
                index_token_address=position['index_token_address'],
                is_long=position['is_long'],
                size_delta=size_delta,
                initial_collateral_delta_amount=collateral_to_withdraw,
                slippage_percent=0.005,  # 0.5% slippage
                swap_path=[],
                debug_mode=False  # No debug to avoid extra logs
            )
            
            # Remove or update position
            if not size_usd or size_usd >= (position['size_delta'] / 10**30):
                # Full close
                del self.current_positions[position_key]
                logger.info("✅ Position fully closed using Safe wallet!")
            else:
                # Partial close - update position
                self.current_positions[position_key]['size_delta'] -= size_delta
                self.current_positions[position_key]['collateral_amount'] -= collateral_to_withdraw
                logger.info("✅ Position partially closed using Safe wallet!")
            
            logger.info("💡 Profits will remain in Safe wallet")
            
            # Attach Safe proposal info if present
            safe_info = {}
            last_payload = getattr(order, 'last_safe_tx_payload', None)
            last_proposal = getattr(order, 'last_safe_tx_proposal', None)
            if last_payload:
                safe_info['to'] = last_payload.get('to')
                safe_info['value'] = last_payload.get('value')
                safe_info['data_len'] = len((last_payload.get('data') or '0x'))
            if isinstance(last_proposal, dict):
                safe_info['proposal'] = {
                    'safeTxHash': last_proposal.get('safeTxHash') or last_proposal.get('contractTransactionHash'),
                    'url': last_proposal.get('url')
                }
            
            return {
                'status': 'success',
                'order': str(order),
                'token': token,
                'size_closed': size_usd or 'FULL',
                'action': 'SELL',
                'safe_wallet': self.safe_address,
                'signer_address': self.private_key_address,
                'safe': safe_info,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Error executing sell order: {e}")
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
        is_long: bool = True
    ) -> Dict[str, Any]:
        """Create a position with automatic Take Profit and Stop Loss orders"""
        try:
            if not self.initialized:
                raise Exception("API not initialized")
            
            token_config = self.supported_tokens.get(token.upper())
            if not token_config:
                raise Exception(f"Token {token} not supported")
            
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
            
            # Track position locally for status monitoring
            position_key = f"{token.upper()}_{'LONG' if is_long else 'SHORT'}"
            self.current_positions[position_key] = {
                'token': token.upper(),
                'market_key': order_parameters['market_key'],
                'collateral_address': order_parameters['start_token_address'],
                'index_token_address': order_parameters['index_token_address'],
                'is_long': is_long,
                'size_delta': size_delta,
                'collateral_amount': collateral_amount_wei,
                'leverage': leverage,
                'entry_price': None,  # Would need to fetch from market
                'take_profit_price': take_profit_price,
                'stop_loss_price': stop_loss_price,
                'created_at': datetime.now().isoformat()
            }
            
            logger.info("✅ Position with TP/SL created successfully!")
            logger.info("📈 Position will automatically exit at TP or SL levels")
            
            # Get order summary
            summary = position.get_order_summary()
            
            # Extract Safe transaction info if available
            safe_info = {}
            for order_type in ['main_order', 'take_profit_order', 'stop_loss_order']:
                order_obj = getattr(position, order_type.replace('_order', ''), None)
                if order_obj:
                    last_payload = getattr(order_obj, 'last_safe_tx_payload', None)
                    last_proposal = getattr(order_obj, 'last_safe_tx_proposal', None)
                    if last_payload or last_proposal:
                        safe_info[order_type] = {}
                        if last_payload:
                            safe_info[order_type]['to'] = last_payload.get('to')
                            safe_info[order_type]['data_len'] = len((last_payload.get('data') or '0x'))
                        if isinstance(last_proposal, dict):
                            safe_info[order_type]['proposal'] = {
                                'safeTxHash': last_proposal.get('safeTxHash') or last_proposal.get('contractTransactionHash'),
                                'url': last_proposal.get('url')
                            }
            
            return {
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
                'note': 'Position will exit automatically at TP or SL levels - no monitoring required',
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Error creating position with TP/SL: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def get_positions(self) -> Dict[str, Any]:
        """Get current positions"""
        try:
            if not self.initialized:
                return {'status': 'error', 'error': 'API not initialized'}
            
            # Get positions from GMX SDK
            try:
                positions = GetOpenPositions(
                    config=self.config,
                    address=self.safe_address
                ).get_data()
                
                return {
                    'status': 'success',
                    'positions': positions,
                    'local_positions': self.current_positions,
                    'timestamp': datetime.now().isoformat()
                }
            except Exception as e:
                # Fallback to local tracking
                return {
                    'status': 'success',
                    'positions': [],
                    'local_positions': self.current_positions,
                    'note': f'Using local tracking due to: {str(e)}',
                    'timestamp': datetime.now().isoformat()
                }
                
        except Exception as e:
            logger.error(f"❌ Error getting positions: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def validate_signal(self, signal_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate incoming signal data"""
        errors = []
        
        # Required fields
        required_fields = ['Signal Message', 'Token Mentioned']
        for field in required_fields:
            if field not in signal_data:
                errors.append(f"Missing required field: {field}")
        
        # Validate token
        token = signal_data.get('Token Mentioned', '').upper()
        if token and token not in self.supported_tokens:
            errors.append(f"Token {token} not supported")
        
        # Validate signal type
        signal_type = signal_data.get('Signal Message', '').lower()
        if signal_type and signal_type not in ['buy', 'sell', 'long', 'short']:
            errors.append(f"Invalid signal type: {signal_type}")
        
        return {
            'is_valid': len(errors) == 0,
            'errors': errors
        }
    
    def process_signal(self, signal_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process trading signal and execute order"""
        try:
            # Extract signal parameters
            signal_type = signal_data.get('Signal Message', '').lower()
            token = signal_data.get('Token Mentioned', '').upper()
            username = signal_data.get('username', 'api_user')
            
            # Default trading parameters
            size_usd = 2.02  # Default position size
            leverage = 1     # Default leverage
            
            logger.info(f"📡 Processing {signal_type.upper()} signal for {token}")
            
            if signal_type in ['buy', 'long']:
                result = self.execute_buy_order(token=token, size_usd=size_usd, leverage=leverage)
            elif signal_type in ['sell', 'short']:
                result = self.execute_sell_order(token=token)
            else:
                raise Exception(f"Unknown signal type: {signal_type}")
            
            # Add signal metadata to result
            result.update({
                'signal_id': f"gmx_{int(time.time())}_{username}",
                'signal_type': signal_type,
                'username': username,
                'original_signal': signal_data
            })
            
            return result
            
        except Exception as e:
            logger.error(f"❌ Error processing signal: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }

# Initialize API instance
gmx_api = SimplifiedGMXAPI()

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'Simplified GMX Safe API',
        'safe_address': gmx_api.safe_address,
        'initialized': gmx_api.initialized,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/initialize', methods=['POST'])
def initialize():
    """Initialize the GMX API"""
    try:
        success = gmx_api.initialize()
        if success:
            return jsonify({
                'status': 'success',
                'message': 'GMX API initialized successfully',
                'timestamp': datetime.now().isoformat()
            })
        else:
            return jsonify({
                'status': 'error',
                'error': 'Failed to initialize GMX API',
                'timestamp': datetime.now().isoformat()
            }), 500
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/signal/process', methods=['POST'])
def process_signal():
    """Process a trading signal"""
    try:
        signal_data = request.get_json()
        
        if not signal_data:
            return jsonify({
                'status': 'error',
                'error': 'No signal data provided'
            }), 400
        
        logger.info(f"📡 Received signal: {signal_data}")
        
        # Validate signal
        validation = gmx_api.validate_signal(signal_data)
        if not validation['is_valid']:
            return jsonify({
                'status': 'error',
                'error': 'Signal validation failed',
                'details': validation['errors']
            }), 400
        
        # Process signal and execute trade
        result = gmx_api.process_signal(signal_data)
        
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
        size_usd = float(data.get('size_usd', 2.02))
        leverage = int(data.get('leverage', 2))
        
        result = gmx_api.execute_buy_order(token=token, size_usd=size_usd, leverage=leverage)
        
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
        
        result = gmx_api.execute_sell_order(token=token, size_usd=size_usd)
        
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
    """Create a position with automatic Take Profit and Stop Loss orders from signal format"""
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
            size_usd = 2.02  # Default size for signals (matches normal orders)
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
            size_usd = float(data.get('size_usd', 2.02))  # Default matches normal orders
            leverage = int(data.get('leverage', 2))
            take_profit_price = float(data.get('take_profit_price'))
            stop_loss_price = float(data.get('stop_loss_price'))
            is_long = data.get('is_long', True)
            
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
        
        result = gmx_api.execute_position_with_tp_sl(
            token=token,
            size_usd=size_usd,
            leverage=leverage,
            take_profit_price=take_profit_price,
            stop_loss_price=stop_loss_price,
            is_long=is_long
        )
        
        # Add signal-specific metadata if it's a signal format
        if 'Signal Message' in data:
            result.update({
                'signal_id': f"gmx_tp_sl_{int(time.time())}_{username}",
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

@app.route('/positions', methods=['GET'])
def get_positions():
    """Get current positions"""
    try:
        result = gmx_api.get_positions()
        return jsonify(result)
        
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

if __name__ == '__main__':
    # Auto-initialize if environment variables are available
    if os.getenv('SAFE_ADDRESS') and os.getenv('PRIVATE_KEY'):
        logger.info("🔧 Auto-initializing GMX API...")
        gmx_api.initialize()
    else:
        logger.info("⚠️ Missing SAFE_ADDRESS or PRIVATE_KEY - manual initialization required")
    
    # Start the Flask server
    port = int(os.getenv('GMX_PYTHON_API_PORT', 5001))
    logger.info(f"🚀 Starting Simplified GMX Safe API on port {port}")
    app.run(host='0.0.0.0', port=port, debug=True)
