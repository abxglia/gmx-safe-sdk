#!/usr/bin/env python3
"""
Service module containing the EnhancedGMXAPI class
"""

import os
import time
import logging
import json
from decimal import Decimal
from datetime import datetime
from typing import Dict, Any

from dotenv import load_dotenv
from web3 import Web3

# GMX Python SDK imports
from gmx_python_sdk.scripts.v2.gmx_utils import ConfigManager
from gmx_python_sdk.scripts.v2.order.create_increase_order import IncreaseOrder
from gmx_python_sdk.scripts.v2.order.create_decrease_order import DecreaseOrder
from gmx_python_sdk.scripts.v2.order.create_take_profit_order import TakeProfitOrder
from gmx_python_sdk.scripts.v2.order.create_stop_loss_order import StopLossOrder
from gmx_python_sdk.scripts.v2.get.get_open_positions import GetOpenPositions

# Safe SDK imports
from safe_eth.safe import Safe
from safe_eth.eth import EthereumClient

# Database integration imports
from gmx_python_sdk.scripts.v2.database.transaction_tracker import transaction_tracker
from gmx_python_sdk.scripts.v2.database.gmx_database_integration import gmx_db
from gmx_python_sdk.scripts.v2.database.mongo_models import (
    TransactionStatus, PositionStatus, OrderType
)

# Safe utilities imports
from gmx_python_sdk.scripts.v2.safe_utils import (
    execute_safe_transaction as execute_safe_tx_util,
    list_safe_pending_transactions
)
from gmx_python_sdk.scripts.v2.approve_token_for_spend import check_if_approved


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()


class EnhancedGMXAPI:
    def __init__(self):
        self.initialized = False
        self.db_connected = False

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
            if safe_address:
                self.safe_address = safe_address
                logger.info(f"🔧 Setting Safe address from signal: {self.safe_address}")
            elif not self.safe_address:
                self.safe_address = os.getenv('SAFE_ADDRESS')
                if self.safe_address:
                    logger.info(f"🔧 Using Safe address from environment: {self.safe_address}")
                else:
                    raise Exception("No Safe address provided - must be in signal or environment variable")

            self.db_connected = transaction_tracker.ensure_connected()
            if self.db_connected:
                logger.info("✅ MongoDB connected successfully")
            else:
                logger.warning("⚠️ MongoDB connection failed - continuing without database")

            w3 = Web3()
            private_key_address = w3.eth.account.from_key(self.private_key).address

            logger.info(f"🔍 Address derived from private key: {private_key_address}")
            logger.info(f"🔍 Safe wallet address: {self.safe_address}")

            self.ethereum_client = EthereumClient(self.rpc_url)
            self.safe = Safe(self.safe_address, self.ethereum_client)

            self.config = ConfigManager(chain='arbitrum')
            self.config.set_rpc(self.rpc_url)
            self.config.set_chain_id(42161)
            self.config.set_wallet_address(self.safe_address)
            self.config.set_private_key(self.private_key)

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
            config_path = os.path.join(os.path.dirname(__file__), '..', 'supported_tokens.json')
            config_path = os.path.abspath(config_path)
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

            signal_id = kwargs.get('signal_id')
            username = kwargs.get('username', 'api_user')
            original_signal = kwargs.get('original_signal', {})
            position_id = kwargs.get('position_id')

            collateral_amount = Decimal(str(size_usd)) / Decimal(str(leverage))
            collateral_amount_usd = float(collateral_amount)

            if self.db_connected and not position_id:
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

            original_auto_execute = getattr(self.config, 'auto_execute_approvals', False)
            if auto_execute:
                self.config.auto_execute_approvals = True

            self.config.use_safe_transactions = True
            self.config.safe_address = self.safe_address

            order = IncreaseOrder(
                config=self.config,
                market_key=token_config['market_key'],
                collateral_address=token_config['collateral_token'],
                index_token_address=token_config['index_token'],
                is_long=True,
                size_delta=int(Decimal(str(size_usd)) * Decimal(10**30)),
                initial_collateral_delta_amount=int(Decimal(str(collateral_amount_usd)) * Decimal(10**6)),
                slippage_percent=0.5,
                swap_path=[]
            )

            self.config.auto_execute_approvals = original_auto_execute

            safe_info = {}
            safe_tx_hash = None
            last_proposal = getattr(order, 'last_safe_tx_proposal', None)
            if last_proposal and isinstance(last_proposal, dict):
                safe_tx_hash = last_proposal.get('safeTxHash') or last_proposal.get('contractTransactionHash')
                safe_info = {
                    'safeTxHash': safe_tx_hash,
                    'url': last_proposal.get('url')
                }
                if self.db_connected and safe_tx_hash:
                    gmx_db.log_safe_transaction_from_order(
                        safe_tx_hash=safe_tx_hash,
                        safe_address=self.safe_address,
                        order_type=OrderType.MARKET_INCREASE.value,
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

            if auto_execute and safe_tx_hash:
                time.sleep(15)
                execution_result = self.execute_safe_transaction(safe_tx_hash)
                if execution_result.get('status') == 'success':
                    result['execution'] = {
                        'status': 'success',
                        'txHash': execution_result.get('txHash'),
                        'message': 'Transaction executed successfully'
                    }
                    safe_info['executed'] = True
                    safe_info['execution_tx_hash'] = execution_result.get('txHash')
                else:
                    result['execution'] = {
                        'status': 'error',
                        'error': execution_result.get('error'),
                        'message': 'Auto-execution failed, transaction remains pending'
                    }

            if self.db_connected and position_id:
                gmx_db.update_position_from_execution(
                    position_id=position_id,
                    execution_result=result,
                    safe_tx_hash=safe_tx_hash
                )

            return result
        except Exception as e:
            if self.db_connected and 'position_id' in locals() and position_id:
                transaction_tracker.update_position_status(
                    position_id=position_id,
                    status=PositionStatus.PENDING
                )
            return {
                'status': 'error',
                'error': str(e),
                'position_id': locals().get('position_id'),
                'timestamp': datetime.now().isoformat()
            }

    def execute_sell_order(self, token: str, size_usd: float = None, auto_execute: bool = False, **kwargs) -> Dict[str, Any]:
        """Execute a sell order with database tracking and optional auto-execution"""
        try:
            if not self.initialized:
                raise Exception("API not initialized")

            active_positions = []
            if self.db_connected:
                active_positions = transaction_tracker.get_active_positions(self.safe_address)
                active_positions = [p for p in active_positions if p.get('token') == token.upper() and p.get('is_long')]

            if not active_positions:
                raise Exception(f"No open {token} position found to close")

            position = active_positions[0]
            position_id = position.get('position_id')

            if size_usd:
                size_delta = int(Decimal(str(size_usd)) * Decimal(10**30))
                collateral_to_withdraw = int(Decimal(str(size_usd)) * Decimal(10**6))
            else:
                position_size = Decimal(str(position.get('size_delta_usd', 0)))
                position_collateral = Decimal(str(position.get('collateral_delta_usd', 0)))
                size_delta = int(position_size * Decimal(10**30))
                collateral_to_withdraw = int(position_collateral * Decimal(10**6))
                size_usd = float(position_size)

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

            safe_info = {}
            safe_tx_hash = None
            last_proposal = getattr(order, 'last_safe_tx_proposal', None)
            if last_proposal and isinstance(last_proposal, dict):
                safe_tx_hash = last_proposal.get('safeTxHash') or last_proposal.get('contractTransactionHash')
                safe_info = {
                    'safeTxHash': safe_tx_hash,
                    'url': last_proposal.get('url')
                }
                if self.db_connected and safe_tx_hash:
                    gmx_db.log_safe_transaction_from_order(
                        safe_tx_hash=safe_tx_hash,
                        safe_address=self.safe_address,
                        order_type=OrderType.MARKET_DECREASE.value,
                        token=token.upper(),
                        position_id=position_id,
                        market_key=position.get('market_key', '')
                    )

            if auto_execute and safe_tx_hash:
                time.sleep(15)
                execution_result = self.execute_safe_transaction(safe_tx_hash)
                if execution_result.get('status') == 'success':
                    safe_info['executed'] = True
                    safe_info['execution_tx_hash'] = execution_result.get('txHash')
                    safe_info['execution_message'] = 'Transaction executed successfully'
                else:
                    safe_info['execution_error'] = execution_result.get('error')
                    safe_info['execution_message'] = 'Auto-execution failed, transaction remains pending'

            if self.db_connected and position_id:
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
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }

    def get_active_positions(self, safe_address: str | None = None) -> Dict[str, Any]:
        try:
            if not self.db_connected:
                return {
                    'status': 'error',
                    'error': 'Database not connected',
                    'timestamp': datetime.now().isoformat()
                }
            address_to_query = safe_address or self.safe_address
            if not address_to_query:
                return {
                    'status': 'error',
                    'error': 'Safe address not set',
                    'timestamp': datetime.now().isoformat()
                }
            positions = transaction_tracker.get_active_positions(address_to_query)
            return {
                'status': 'success',
                'positions': positions,
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }

    def _ensure_safe_has_funds(self, required_usdc: float) -> bool:
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
        try:
            pending_txs = self.list_pending_transactions(limit=10)
            approval_executed = False
            if pending_txs.get('status') == 'success' and pending_txs.get('transactions'):
                for tx in pending_txs['transactions']:
                    tx_data = tx.get('data', '').lower()
                    tx_to = tx.get('to', '').lower()
                    if (tx_to == self.usdc_address.lower() and 'approval' in tx_data):
                        safe_tx_hash = tx.get('safeTxHash')
                        execution_result = self.execute_safe_transaction(safe_tx_hash)
                        if execution_result.get('status') == 'success':
                            approval_executed = True
                            time.sleep(15)
                        break
            return {
                'status': 'success',
                'approval_executed': approval_executed,
                'message': 'Approval transaction check completed'
            }
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e),
                'approval_executed': False
            }

    def ensure_token_approval(self, token_amount_usd: float, auto_execute: bool = False) -> Dict[str, Any]:
        try:
            if not self.initialized:
                raise Exception("API not initialized")

            spender_address = self.gmx_exchange_router
            token_address = self.usdc_address
            amount_in_tokens = int(token_amount_usd * 10**6)

            self.config.use_safe_transactions = True
            self.config.safe_address = self.safe_address
            self.config.safe_api_url = os.getenv('SAFE_API_URL')
            self.config.safe_api_key = os.getenv('SAFE_TRANSACTION_SERVICE_API_KEY')

            try:
                approval_result = check_if_approved(
                    config=self.config,
                    spender=spender_address,
                    token_to_approve=token_address,
                    amount_of_tokens_to_spend=amount_in_tokens,
                    max_fee_per_gas=0,
                    approve=True,
                    auto_execute=auto_execute
                )
            except Exception as approval_error:
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

            if approval_result.get('safe_tx_hash'):
                result['approval_transaction'] = {
                    'safeTxHash': approval_result.get('safe_tx_hash'),
                    'executed': approval_result.get('approval_executed', False),
                    'execution_tx_hash': approval_result.get('execution_tx_hash'),
                    'payload_file': approval_result.get('payload_file')
                }
            elif not approval_result.get('approval_needed'):
                result['approval_transaction'] = {
                    'message': 'No approval transaction found (likely already approved)'
                }
            return result
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e),
                'token_amount_usd': token_amount_usd,
                'timestamp': datetime.now().isoformat()
            }

    def execute_safe_transaction(self, safe_tx_hash: str) -> Dict[str, Any]:
        try:
            if not self.initialized:
                raise Exception("API not initialized")
            if not self.safe_address:
                raise Exception("Safe address not set")
            safe_api_url = os.getenv('SAFE_API_URL')
            safe_api_key = os.getenv('SAFE_TRANSACTION_SERVICE_API_KEY')
            if not safe_api_url:
                raise Exception("SAFE_API_URL environment variable not set")
            result = execute_safe_tx_util(
                safe_address=self.safe_address,
                safe_tx_hash=safe_tx_hash,
                rpc_url=self.rpc_url,
                private_key=self.private_key,
                safe_api_url=safe_api_url,
                api_key=safe_api_key
            )
            return result
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }

    def list_pending_transactions(self, limit: int = 10, offset: int = 0) -> Dict[str, Any]:
        try:
            if not self.initialized:
                raise Exception("API not initialized")
            if not self.safe_address:
                raise Exception("Safe address not set")
            safe_api_url = os.getenv('SAFE_API_URL')
            safe_api_key = os.getenv('SAFE_TRANSACTION_SERVICE_API_KEY')
            if not safe_api_url:
                raise Exception("SAFE_API_URL environment variable not set")
            result = list_safe_pending_transactions(
                safe_address=self.safe_address,
                safe_api_url=safe_api_url,
                api_key=safe_api_key,
                limit=limit,
                offset=offset
            )
            return result
        except Exception as e:
            return {
                'status': 'error',
                'error': str(e),
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
        try:
            if not self.initialized:
                raise Exception("API not initialized")
            token_config = self.supported_tokens.get(token.upper())
            if not token_config:
                raise Exception(f"Token {token} not supported")
            signal_id = kwargs.get('signal_id')
            username = kwargs.get('username', 'api_user')
            original_signal = kwargs.get('original_signal', {})
            collateral_amount = Decimal(str(size_usd)) / Decimal(str(leverage))
            collateral_amount_usd = float(collateral_amount)

            if not self._ensure_safe_has_funds(collateral_amount_usd):
                raise Exception("Safe wallet has insufficient funds for trading")

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

            original_auto_execute = getattr(self.config, 'auto_execute_approvals', False)
            if auto_execute:
                self.config.auto_execute_approvals = True
            try:
                buy_order_result = self.execute_buy_order(
                    token=token,
                    size_usd=size_usd,
                    leverage=leverage,
                    auto_execute=False,
                    signal_id=signal_id,
                    username=username,
                    original_signal=original_signal,
                    position_id=position_id
                )
            finally:
                self.config.auto_execute_approvals = original_auto_execute
            sequential_results['buy_order'] = buy_order_result
            if buy_order_result.get('status') != 'success':
                raise Exception(f"Buy order failed: {buy_order_result.get('error')}")

            approval_executed = self.execute_pending_approval_transactions()
            if approval_executed:
                time.sleep(15)

            buy_safe_tx_hash = None
            if buy_order_result.get('safe', {}).get('safeTxHash'):
                buy_safe_tx_hash = buy_order_result['safe']['safeTxHash']
                if auto_execute and buy_safe_tx_hash:
                    time.sleep(15)
                    execution_result = self.execute_safe_transaction(buy_safe_tx_hash)
                    if execution_result.get('status') == 'success':
                        buy_order_result['execution'] = {
                            'status': 'success',
                            'txHash': execution_result.get('txHash'),
                            'message': 'Buy order executed successfully'
                        }
                    else:
                        buy_order_result['execution'] = {
                            'status': 'error',
                            'error': execution_result.get('error'),
                            'message': 'Buy order execution failed'
                        }

            if auto_execute and buy_order_result.get('execution', {}).get('status') == 'success':
                time.sleep(15)

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

            executed_steps = 0
            total_steps = 3
            if sequential_results['buy_order'].get('execution', {}).get('status') == 'success':
                executed_steps += 1
            if sequential_results['take_profit_order'].get('execution', {}).get('status') == 'success':
                executed_steps += 1
            if sequential_results['stop_loss_order'].get('execution', {}).get('status') == 'success':
                executed_steps += 1
            if sequential_results['buy_order'].get('status') == 'success' and not sequential_results['buy_order'].get('execution'):
                executed_steps += 1
            result['execution_summary'] = {
                'executed_steps': executed_steps,
                'total_steps': total_steps,
                'success_rate': f"{executed_steps}/{total_steps}"
            }
            return result
        except Exception as e:
            if self.db_connected and 'position_id' in locals() and position_id:
                transaction_tracker.update_position_status(
                    position_id=position_id,
                    status=PositionStatus.FAILED
                )
            return {
                'status': 'error',
                'error': str(e),
                'position_id': locals().get('position_id'),
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
        try:
            if not self.initialized:
                raise Exception("API not initialized")
            token_config = self.supported_tokens.get(token.upper())
            if not token_config:
                raise Exception(f"Token {token} not supported")
            signal_id = kwargs.get('signal_id')
            username = kwargs.get('username', 'api_user')
            position_id = kwargs.get('position_id')
            size_delta = int(Decimal(str(size_usd)) * Decimal(10**30))
            collateral_to_withdraw = int(Decimal(str(size_usd)) * Decimal(10**6))
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
            safe_info = {}
            safe_tx_hash = None
            last_proposal = getattr(order, 'last_safe_tx_proposal', None)
            if last_proposal and isinstance(last_proposal, dict):
                safe_tx_hash = last_proposal.get('safeTxHash') or last_proposal.get('contractTransactionHash')
                safe_info = {
                    'safeTxHash': safe_tx_hash,
                    'url': last_proposal.get('url')
                }
                if self.db_connected and safe_tx_hash:
                    gmx_db.log_safe_transaction_from_order(
                        safe_tx_hash=safe_tx_hash,
                        safe_address=self.safe_address,
                        order_type=OrderType.LIMIT_DECREASE.value,
                        token=token.upper(),
                        position_id=position_id,
                        signal_id=signal_id,
                        username=username,
                        market_key=token_config['market_key']
                    )
            if auto_execute and safe_tx_hash:
                time.sleep(15)
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
        try:
            if not self.initialized:
                raise Exception("API not initialized")
            token_config = self.supported_tokens.get(token.upper())
            if not token_config:
                raise Exception(f"Token {token} not supported")
            signal_id = kwargs.get('signal_id')
            username = kwargs.get('username', 'api_user')
            position_id = kwargs.get('position_id')
            size_delta = int(Decimal(str(size_usd)) * Decimal(10**30))
            collateral_to_withdraw = int(Decimal(str(size_usd)) * Decimal(10**6))
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
            safe_info = {}
            safe_tx_hash = None
            last_proposal = getattr(order, 'last_safe_tx_proposal', None)
            if last_proposal and isinstance(last_proposal, dict):
                safe_tx_hash = last_proposal.get('safeTxHash') or last_proposal.get('contractTransactionHash')
                safe_info = {
                    'safeTxHash': safe_tx_hash,
                    'url': last_proposal.get('url')
                }
                if self.db_connected and safe_tx_hash:
                    gmx_db.log_safe_transaction_from_order(
                        safe_tx_hash=safe_tx_hash,
                        safe_address=self.safe_address,
                        order_type=OrderType.LIMIT_DECREASE.value,
                        token=token.upper(),
                        position_id=position_id,
                        signal_id=signal_id,
                        username=username,
                        market_key=token_config['market_key']
                    )
            if auto_execute and safe_tx_hash:
                time.sleep(15)
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
            return {
                'status': 'error',
                'order_type': 'stop_loss',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }

    def _create_close_order(
        self,
        token: str,
        size_usd: float,
        is_long: bool,
        auto_execute: bool = False,
        slippage_percent: float = 0.03,
        username: str = '',
        **kwargs
    ) -> Dict[str, Any]:
        try:
            if not self.initialized:
                raise Exception("API not initialized")
            token_config = self.supported_tokens.get(token.upper())
            if not token_config:
                raise Exception(f"Token {token} not supported")

            actual_position_size = None
            try:
                positions = GetOpenPositions(config=self.config, address=self.safe_address).get_data()
                direction = 'long' if is_long else 'short'
                position_key = f"{token}_{direction}"
                if position_key in positions:
                    actual_position_size = positions[position_key]['position_size']
            except Exception:
                try:
                    from gmx_python_sdk.scripts.v2.gmx_utils import get_reader_contract, contract_map
                    reader_contract = get_reader_contract(self.config)
                    datastore_address = contract_map[self.config.chain]["datastore"]['contract_address']
                    raw_result = reader_contract.functions.getAccountPositions(
                        datastore_address,
                        self.safe_address,
                        0,
                        10
                    ).call()
                    for raw_pos in raw_result:
                        try:
                            pos_is_long = raw_pos[2][0] if len(raw_pos) > 2 and len(raw_pos[2]) > 0 else None
                            if pos_is_long == is_long:
                                position_size_raw = raw_pos[1][0] if len(raw_pos) > 1 and len(raw_pos[1]) > 0 else 0
                                actual_position_size = position_size_raw / 10**30
                                break
                        except Exception:
                            continue
                except Exception:
                    pass

            if actual_position_size is not None and actual_position_size > 0:
                final_position_size = actual_position_size
                if size_usd > final_position_size:
                    size_usd = final_position_size

            self.config.use_safe_transactions = True
            self.config.safe_address = self.safe_address

            order = DecreaseOrder(
                config=self.config,
                market_key=token_config['market_key'],
                collateral_address=token_config['collateral_token'],
                index_token_address=token_config['index_token'],
                is_long=is_long,
                size_delta=int(size_usd * 10**30),
                initial_collateral_delta_amount=int(size_usd * 10**6),
                slippage_percent=slippage_percent,
                swap_path=[],
                debug_mode=False
            )

            safe_payload = getattr(order, 'last_safe_tx_payload', None)
            safe_proposal = getattr(order, 'last_safe_tx_proposal', None)
            safe_tx_hash = None
            safe_info = {}
            if safe_proposal and safe_proposal.get('status') == 'success':
                safe_tx_hash = safe_proposal.get('safeTxHash')
                safe_info = {
                    'safeTxHash': safe_tx_hash,
                    'proposed': True,
                    'executed': False
                }
            elif safe_proposal:
                safe_info = {
                    'proposal_status': safe_proposal.get('status'),
                    'error': safe_proposal.get('error', 'Unknown error'),
                    'proposed': False,
                    'executed': False
                }
            else:
                safe_info = {
                    'proposed': False,
                    'executed': False,
                    'note': 'No Safe transaction proposal created'
                }

            if self.db_connected and safe_tx_hash:
                signal_id = kwargs.get('signal_id', '')
                gmx_db.log_order_transaction(
                    safe_tx_hash=safe_tx_hash,
                    order_type=OrderType.MARKET_DECREASE.value,
                    token=token,
                    size_usd=size_usd,
                    is_long=is_long,
                    status=TransactionStatus.PROPOSED,
                    signal_id=signal_id,
                    username=username,
                    market_key=token_config['market_key']
                )

            if auto_execute and safe_tx_hash:
                time.sleep(15)
                execution_result = self.execute_safe_transaction(safe_tx_hash)
                if execution_result.get('status') == 'success':
                    safe_info['executed'] = True
                    safe_info['execution_tx_hash'] = execution_result.get('txHash')
                    safe_info['execution_message'] = 'Close order executed successfully'
                else:
                    safe_info['execution_error'] = execution_result.get('error')
                    safe_info['execution_message'] = 'Close order execution failed'

            return {
                'status': 'success',
                'order_type': 'close',
                'token': token,
                'size_usd': size_usd,
                'is_long': is_long,
                'safe': safe_info,
                'message': f'Close order created for {token} position',
                'timestamp': datetime.now().isoformat()
            }
        except Exception as e:
            return {
                'status': 'error',
                'order_type': 'close',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }

    def process_signal_with_database(self, signal_data: Dict[str, Any]) -> Dict[str, Any]:
        try:
            safe_address = signal_data.get('safeAddress')
            if not safe_address:
                raise Exception("safeAddress is required in signal data")
            if not self.initialized or self.safe_address != safe_address:
                self.initialize(safe_address=safe_address)
            signal_id = ""
            if self.db_connected:
                username = signal_data.get('username', 'api_user')
                signal_id = gmx_db.log_signal_processing(
                    signal_data=signal_data,
                    username=username,
                    api_endpoint='/signal/process'
                )
            signal_type = signal_data.get('Signal Message', '').lower()
            token = signal_data.get('Token Mentioned', '').upper()
            kwargs = {
                'signal_id': signal_id,
                'username': signal_data.get('username', 'api_user'),
                'original_signal': signal_data
            }
            auto_execute = signal_data.get('autoExecute', False)
            if signal_type in ['buy', 'long']:
                result = self.execute_buy_order(
                    token=token,
                    size_usd=2.1,
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
            if self.db_connected and signal_id:
                transaction_tracker.update_signal_processing(
                    signal_id=signal_id,
                    processed=True,
                    position_id=result.get('position_id'),
                    safe_tx_hashes=[result.get('safe', {}).get('safeTxHash')] if result.get('safe', {}).get('safeTxHash') else []
                )
            result.update({
                'signal_id': signal_id,
                'signal_type': signal_type,
                'original_signal': signal_data
            })
            return result
        except Exception as e:
            if self.db_connected and 'signal_id' in locals() and signal_id:
                transaction_tracker.update_signal_processing(
                    signal_id=signal_id,
                    processed=False,
                    processing_error=str(e)
                )
            return {
                'status': 'error',
                'error': str(e),
                'signal_id': locals().get('signal_id', ''),
                'timestamp': datetime.now().isoformat()
            }