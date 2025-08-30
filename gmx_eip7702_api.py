#!/usr/bin/env python3
"""
EIP7702 Delegation-based GMX Safe API Server
Integrates EIP7702 delegation contracts with GMX V2 trading functionality
Tracks delegated funds, trading positions, and execution history
"""

import os
import sys
import time
import logging
import json
from decimal import Decimal
from datetime import datetime
from typing import Dict, Any, Optional, List, Tuple

from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from web3 import Web3
from web3.exceptions import ContractLogicError

# GMX Python SDK imports
from gmx_python_sdk.scripts.v2.gmx_utils import ConfigManager
from gmx_python_sdk.scripts.v2.order.create_increase_order import IncreaseOrder
from gmx_python_sdk.scripts.v2.order.create_decrease_order import DecreaseOrder
from gmx_python_sdk.scripts.v2.order.create_position_with_tp_sl import PositionWithTPSL
from gmx_python_sdk.scripts.v2.order.order_argument_parser import OrderArgumentParser
from gmx_python_sdk.scripts.v2.get.get_open_positions import GetOpenPositions
from gmx_python_sdk.scripts.v2.order.withdraw import Withdraw

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

class EIP7702DelegationManager:
    """Manages EIP7702 delegation interactions and fund tracking"""
    
    def __init__(self, web3: Web3, delegation_manager_address: str):
        self.web3 = web3
        self.delegation_manager_address = delegation_manager_address
        
        # EIP7702 Delegation Manager ABI (minimal for our needs)
        self.abi = [
            {
                "inputs": [{"name": "delegationId", "type": "uint256"}],
                "name": "getDelegation",
                "outputs": [{
                    "components": [
                        {"name": "delegator", "type": "address"},
                        {"name": "delegate", "type": "address"},
                        {"name": "asset", "type": "address"},
                        {"name": "amount", "type": "uint256"},
                        {"name": "startTime", "type": "uint256"},
                        {"name": "endTime", "type": "uint256"},
                        {"name": "isActive", "type": "bool"},
                        {"name": "isRevoked", "type": "bool"}
                    ],
                    "name": "",
                    "type": "tuple"
                }],
                "stateMutability": "view",
                "type": "function"
            },
            {
                "inputs": [
                    {"name": "delegationId", "type": "uint256"},
                    {"name": "to", "type": "address"},
                    {"name": "amount", "type": "uint256"}
                ],
                "name": "transferDelegatedTokens",
                "outputs": [],
                "stateMutability": "nonpayable",
                "type": "function"
            },
            {
                "inputs": [{"name": "delegate", "type": "address"}],
                "name": "getReceivedDelegations",
                "outputs": [{"name": "", "type": "uint256[]"}],
                "stateMutability": "view",
                "type": "function"
            },
            {
                "inputs": [{"name": "delegationId", "type": "uint256"}],
                "name": "getAvailableDelegatedAmount",
                "outputs": [{"name": "", "type": "uint256"}],
                "stateMutability": "view",
                "type": "function"
            },
            {
                "inputs": [{"name": "delegationId", "type": "uint256"}],
                "name": "getDelegationStatus",
                "outputs": [
                    {"name": "isActive", "type": "bool"},
                    {"name": "timeLeft", "type": "uint256"}
                ],
                "stateMutability": "view",
                "type": "function"
            }
        ]
        
        self.contract = web3.eth.contract(
            address=delegation_manager_address,
            abi=self.abi
        )
    
    def get_active_delegations(self, delegate_address: str) -> List[Dict[str, Any]]:
        """Get all active delegations for a delegate address"""
        try:
            delegation_ids = self.contract.functions.getReceivedDelegations(
                delegate_address
            ).call()
            
            active_delegations = []
            for delegation_id in delegation_ids:
                delegation = self.contract.functions.getDelegation(delegation_id).call()
                is_active, time_left = self.contract.functions.getDelegationStatus(
                    delegation_id
                ).call()
                
                if is_active:
                    active_delegations.append({
                        'delegation_id': delegation_id,
                        'delegator': delegation[0],
                        'delegate': delegation[1],
                        'asset': delegation[2],
                        'amount': delegation[3],
                        'start_time': delegation[4],
                        'end_time': delegation[5],
                        'is_active': delegation[6],
                        'is_revoked': delegation[7],
                        'time_left_seconds': time_left,
                        'time_left_hours': time_left // 3600
                    })
            
            return active_delegations
            
        except Exception as e:
            logger.error(f"Error getting active delegations: {e}")
            return []
    
    def get_total_delegated_funds(self, delegate_address: str) -> Dict[str, int]:
        """Get total delegated funds by asset type"""
        active_delegations = self.get_active_delegations(delegate_address)
        
        total_funds = {}
        for delegation in active_delegations:
            asset = delegation['asset']
            amount = delegation['amount']
            
            if asset == '0x0000000000000000000000000000000000000000':  # ETH
                asset_key = 'ETH'
            else:
                asset_key = asset
            
            if asset_key not in total_funds:
                total_funds[asset_key] = 0
            total_funds[asset_key] += amount
        
        return total_funds
    
    def can_use_delegated_funds(self, delegate_address: str, required_amount: int, asset: str) -> bool:
        """Check if delegate can use required amount of delegated funds"""
        total_funds = self.get_total_delegated_funds(delegate_address)
        
        if asset == '0x0000000000000000000000000000000000000000':  # ETH
            asset_key = 'ETH'
        else:
            asset_key = asset
        
        available_amount = total_funds.get(asset_key, 0)
        return available_amount >= required_amount

class EIP7702GMXAPI:
    """Enhanced GMX API with EIP7702 delegation support"""
    
    def __init__(self):
        self.initialized = False
        self.db_connected = False
        
        # Configuration from environment
        self.delegate_address = os.getenv('DELEGATE_ADDRESS')  # Our address that received delegation
        self.private_key = os.getenv('PRIVATE_KEY')
        self.rpc_url = os.getenv('RPC_URL', 'https://arb1.arbitrum.io/rpc')
        
        # EIP7702 Delegation Manager address
        self.delegation_manager_address = os.getenv(
            'EIP7702_DELEGATION_MANAGER_ADDRESS',
            '0x0000000000000000000000000000000000000000'  # Default placeholder
        )
        
        # MongoDB connection
        self.mongodb_connection = os.getenv('MONGODB_CONNECTION_STRING', 'mongodb://localhost:27017/')
        
        # GMX and Safe configuration
        self.config = None
        self.safe = None
        self.ethereum_client = None
        self.web3 = None
        
        # EIP7702 Delegation Manager
        self.delegation_manager = None
        
        # GMX V2 addresses
        self.gmx_exchange_router = "0x7452c558d45f8afC8c83dAe62C3f8A5BE19c71f6"
        self.usdc_address = "0xaf88d065e77c8cC2239327C5EDb3A432268e5831"
        
        # Token mapping loaded from JSON file
        self.supported_tokens = self._load_supported_tokens()
    
    def initialize(self):
        """Initialize EIP7702 delegation, GMX, and Database connections"""
        try:
            # Initialize database connection first
            self.db_connected = transaction_tracker.ensure_connected()
            if self.db_connected:
                logger.info("✅ MongoDB connected successfully")
            else:
                logger.warning("⚠️ MongoDB connection failed - continuing without database")
            
            # Initialize Web3
            self.web3 = Web3(Web3.HTTPProvider(self.rpc_url))
            if not self.web3.is_connected():
                raise Exception("Failed to connect to RPC endpoint")
            
            # Initialize EIP7702 Delegation Manager
            if self.delegation_manager_address == '0x0000000000000000000000000000000000000000':
                raise Exception("EIP7702_DELEGATION_MANAGER_ADDRESS not configured")
            
            self.delegation_manager = EIP7702DelegationManager(
                self.web3, 
                self.delegation_manager_address
            )
            
            # Get the address that corresponds to the private key
            private_key_address = self.web3.eth.account.from_key(self.private_key).address
            
            logger.info(f"🔍 Address derived from private key: {private_key_address}")
            logger.info(f"🔍 Delegate address: {self.delegate_address}")
            logger.info(f"🔍 Delegation Manager: {self.delegation_manager_address}")
            
            # Initialize Safe SDK
            self.ethereum_client = EthereumClient(self.rpc_url)
            self.safe = Safe(self.delegate_address, self.ethereum_client)
            
            # Initialize GMX SDK config
            self.config = ConfigManager(chain='arbitrum')
            self.config.set_rpc(self.rpc_url)
            self.config.set_chain_id(42161)
            self.config.set_wallet_address(self.delegate_address)
            self.config.set_private_key(self.private_key)
            
            # Use direct EIP-7702 execution (no Safe wallet)
            try:
                self.config.disable_safe_transactions()
                # Set the delegate address as the wallet address for direct transactions
                self.config.user_wallet_address = self.delegate_address
                logger.info("✅ Direct EIP-7702 execution enabled (no Safe wallet)")
            except Exception as e:
                logger.warning(f"⚠️ Could not configure direct execution: {e}")
            
            self.private_key_address = private_key_address
            
            # Check delegated funds
            self._log_delegated_funds()
            
            self.initialized = True
            logger.info("✅ EIP7702 GMX API initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize: {e}")
            return False

    def _load_supported_tokens(self) -> Dict[str, Dict[str, str]]:
        """Load supported tokens configuration from supported_tokens.json"""
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
    
    def _log_delegated_funds(self):
        """Log delegated funds and store in database if connected"""
        try:
            if not self.delegation_manager:
                logger.warning("⚠️ Delegation manager not initialized")
                return
            
            active_delegations = self.delegation_manager.get_active_delegations(self.delegate_address)
            total_funds = self.delegation_manager.get_total_delegated_funds(self.delegate_address)
            
            logger.info(f"💰 Delegated Funds for {self.delegate_address}:")
            for asset, amount in total_funds.items():
                if asset == 'ETH':
                    formatted_amount = self.web3.from_wei(amount, 'ether')
                    logger.info(f"   {asset}: {formatted_amount} ETH")
                else:
                    # For USDC and other tokens, assume 6 decimals
                    formatted_amount = amount / 10**6
                    logger.info(f"   {asset}: {formatted_amount} USDC")
            
            logger.info(f"   Active Delegations: {len(active_delegations)}")
            
            # Log to database if connected
            if self.db_connected:
                # Store delegation summary in database
                pass
                
        except Exception as e:
            logger.warning(f"⚠️ Could not check delegated funds: {e}")
    
    def get_delegation_summary(self) -> Dict[str, Any]:
        """Get comprehensive summary of delegated funds and status"""
        try:
            if not self.delegation_manager:
                raise Exception("Delegation manager not initialized")
            
            active_delegations = self.delegation_manager.get_active_delegations(self.delegate_address)
            total_funds = self.delegation_manager.get_total_delegated_funds(self.delegate_address)
            
            # Calculate time-based metrics
            total_time_remaining = 0
            for delegation in active_delegations:
                total_time_remaining += delegation['time_left_seconds']
            
            avg_time_remaining = total_time_remaining / len(active_delegations) if active_delegations else 0
            
            return {
                'status': 'success',
                'delegate_address': self.delegate_address,
                'total_delegations': len(active_delegations),
                'total_funds': total_funds,
                'active_delegations': active_delegations,
                'time_metrics': {
                    'total_time_remaining_seconds': total_time_remaining,
                    'average_time_remaining_seconds': avg_time_remaining,
                    'average_time_remaining_hours': avg_time_remaining / 3600
                },
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting delegation summary: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }

    def execute_withdrawal(self, market_key: str, out_token: str, gm_amount: int) -> Dict[str, Any]:
        """Execute a GM withdrawal order using the GMX SDK."""
        if not self.initialized:
            raise Exception("API not initialized")
        order = Withdraw(
            config=self.config,
            market_key=market_key,
            out_token=out_token,
            gm_amount=gm_amount,
            debug_mode=False
        )
        order.create_withdraw_order()
        return {
            'status': 'success',
            'market_key': market_key,
            'out_token': out_token,
            'gm_amount': gm_amount
        }
    
    def execute_buy_order_with_delegation(self, token: str, size_usd: float, leverage: int = 2, **kwargs) -> Dict[str, Any]:
        """Execute a buy order using delegated funds"""
        try:
            if not self.initialized:
                raise Exception("API not initialized")
            
            if not self.delegation_manager:
                raise Exception("Delegation manager not initialized")
            
            token_config = self.supported_tokens.get(token.upper())
            if not token_config:
                raise Exception(f"Token {token} not supported")
            
            # Calculate required collateral
            collateral_amount = Decimal(str(size_usd)) / Decimal(str(leverage))
            collateral_amount_wei = int(collateral_amount * Decimal(10**6))
            
            # Check if we have sufficient delegated funds
            # COMMENTED OUT: User has already transferred funds from contract
            # if not self.delegation_manager.can_use_delegated_funds(
            #     self.delegate_address, 
            #     collateral_amount_wei, 
            #     token_config['collateral_token']
            # ):
            #     raise Exception(f"Insufficient delegated funds. Required: {collateral_amount} USDC")
            
            # Extract additional parameters for database logging
            signal_id = kwargs.get('signal_id')
            username = kwargs.get('username', 'api_user')
            original_signal = kwargs.get('original_signal', {})
            
            # Log position creation to database
            position_id = None
            if self.db_connected:
                position_id = gmx_db.log_order_creation(
                    safe_address=self.delegate_address,
                    token=token.upper(),
                    order_type="buy",
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
            
            # Calculate GMX order parameters
            size_delta = int(collateral_amount * Decimal(str(leverage)) * Decimal(10**30))
            
            logger.info(f"📈 Executing BUY order for {token} using delegated funds (Position ID: {position_id})")
            logger.info(f"   Size: ${size_usd} USD, Leverage: {leverage}x")
            logger.info(f"   Collateral Required: {collateral_amount} USDC")
            
            # Pre-transfer collateral from DelegationManager to GMX router receiver using EIP-7702
            # COMMENTED OUT: User has already transferred funds from contract
            # Find a USDC delegation
            # active_delegations = self.delegation_manager.get_active_delegations(self.delegate_address)
            # usdc_delegations = [d for d in active_delegations if d['asset'].lower() == token_config['collateral_token'].lower()]
            # if not usdc_delegations:
            #     raise Exception("No active USDC delegation found")
            # delegation_id = usdc_delegations[0]['delegation_id']

            # GMX token receiver (router's token vault)
            # gmx_token_receiver = '0x31eF83a530Fde1B38EE9A18093A333D8Bbbc40D5'

            # try:
            #     tx = self.delegation_manager.contract.functions.transferDelegatedTokens(
            #         delegation_id,
            #         Web3.to_checksum_address(gmx_token_receiver),
            #         int(collateral_amount_wei)
            #     ).build_transaction({
            #         'from': Web3.to_checksum_address(self.delegate_address),
            #         'nonce': self.web3.eth.get_transaction_count(Web3.to_checksum_address(self.delegate_address), 'pending'),
            #         'gas': 300000,
            #         'gasPrice': self.web3.eth.gas_price,
            #         'chainId': self.web3.eth.chain_id
            #     })
            #     signed = self.web3.eth.account.sign_transaction(tx, private_key=self.private_key)
            #     raw_tx = getattr(signed, 'rawTransaction', None)
            #     if raw_tx is None:
            #         raw_tx = getattr(signed, 'raw_transaction', None)
            #     if raw_tx is None:
            #         raise Exception('Could not extract raw transaction bytes from signed tx')
            #     tx_hash = self.web3.eth.send_raw_transaction(raw_tx)
            #     receipt = self.web3.eth.wait_for_transaction_receipt(tx_hash)
            #     logger.info(f"✅ Delegated tokens transferred to GMX receiver. Tx: {tx_hash.hex()}")
            # except Exception as e:
            #     raise Exception(f"Failed to transfer delegated tokens: {e}")

            # Execute GMX order (skip internal token transfer; only fee + createOrder)
            # Create a temporary config that uses DelegationManager as the user address for the order
            temp_config = ConfigManager(chain='arbitrum')
            temp_config.set_rpc(self.rpc_url)
            temp_config.set_chain_id(42161)
            temp_config.set_wallet_address(self.delegation_manager_address)  # Use DelegationManager as user
            temp_config.set_private_key(self.private_key)  # Keep your private key for signing
            # Also set the actual sender address for nonce purposes
            temp_config.actual_sender_address = self.delegate_address
            
            order = IncreaseOrder(
                config=temp_config,
                market_key=token_config['market_key'],
                collateral_address=token_config['collateral_token'],
                index_token_address=token_config['index_token'],
                is_long=True,
                size_delta=size_delta,
                initial_collateral_delta_amount=collateral_amount_wei,
                slippage_percent=0.005,
                swap_path=[],
                debug_mode=False,
                eip7702_delegation_manager=self.delegation_manager,
                delegate_address=self.delegate_address,
                external_collateral_transfer=True
            )
            # external_collateral_transfer is now carried via constructor
            
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
                        safe_address=self.delegate_address,
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
                'delegate_address': self.delegate_address,
                'delegation_used': {
                    'collateral_amount': float(collateral_amount),
                    'collateral_token': token_config['collateral_token']
                },
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
            logger.error(f"❌ Error executing buy order with delegation: {e}")
            
            # Log failure to database
            if self.db_connected and position_id:
                transaction_tracker.update_position_status(
                    position_id=position_id,
                    status=PositionStatus.PENDING
                )
            
            return {
                'status': 'error',
                'error': str(e),
                'position_id': position_id,
                'timestamp': datetime.now().isoformat()
            }
    
    def execute_sell_order_with_delegation(self, token: str, size_usd: float = None, **kwargs) -> Dict[str, Any]:
        """Execute a sell order using delegated funds"""
        try:
            if not self.initialized:
                raise Exception("API not initialized")
            
            # Find open position in database
            active_positions = []
            if self.db_connected:
                active_positions = transaction_tracker.get_active_positions(self.delegate_address)
                active_positions = [p for p in active_positions if p.get('token') == token.upper() and p.get('is_long')]
            
            if not active_positions:
                raise Exception(f"No open {token} position found to close")
            
            position = active_positions[0]
            position_id = position.get('position_id')
            
            # Calculate close parameters
            if size_usd:
                size_delta = int(Decimal(str(size_usd)) * Decimal(10**30))
                collateral_to_withdraw = int(Decimal(str(size_usd)) * Decimal(10**6))
            else:
                position_size = Decimal(str(position.get('size_delta_usd', 0)))
                position_collateral = Decimal(str(position.get('collateral_delta_usd', 0)))
                size_delta = int(position_size * Decimal(10**30))
                collateral_to_withdraw = int(position_collateral * Decimal(10**6))
                size_usd = float(position_size)
            
            logger.info(f"📉 Executing SELL order for {token} using delegated funds (Position ID: {position_id})")
            logger.info(f"   Size to close: ${size_usd} USD")
            
            # Execute GMX decrease order
            token_config = self.supported_tokens.get(token.upper())
            if not token_config:
                raise Exception(f"Token {token} not supported")
            
            # Create a temporary config that uses DelegationManager as the user address for the order
            temp_config = ConfigManager(chain='arbitrum')
            temp_config.set_rpc(self.rpc_url)
            temp_config.set_chain_id(42161)
            temp_config.set_wallet_address(self.delegation_manager_address)  # Use DelegationManager as user
            temp_config.set_private_key(self.private_key)  # Keep your private key for signing
            # Also set the actual sender address for nonce purposes
            temp_config.actual_sender_address = self.delegate_address
            
            order = DecreaseOrder(
                config=temp_config,
                market_key=position.get('market_key', ''),
                collateral_address=token_config['collateral_token'],
                index_token_address=token_config['index_token'],
                is_long=position.get('is_long', True),
                size_delta=size_delta,
                initial_collateral_delta_amount=collateral_to_withdraw,
                slippage_percent=0.005,
                swap_path=[],
                debug_mode=False,
                eip7702_delegation_manager=self.delegation_manager,
                delegate_address=self.delegate_address,
                # On close, send proceeds back to DelegationManager so funds return to contract
                receiver_address_override=self.delegation_manager_address
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
                        safe_address=self.delegate_address,
                        order_type=OrderType.MARKET_DECREASE,
                        token=token.upper(),
                        position_id=position_id,
                        market_key=position.get('market_key', '')
                    )
            
            # Update position in database
            if self.db_connected and position_id:
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
                'delegate_address': self.delegate_address,
                'safe': safe_info,
                'position_id': position_id,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Error executing sell order with delegation: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def process_signal_with_delegation(self, signal_data: Dict[str, Any]) -> Dict[str, Any]:
        """Process trading signal using delegated funds"""
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
                result = self.execute_buy_order_with_delegation(
                    token=token, 
                    size_usd=2.0090, 
                    leverage=1, 
                    **kwargs
                )
            elif signal_type in ['sell', 'short']:
                result = self.execute_sell_order_with_delegation(
                    token=token, 
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
            
            logger.error(f"❌ Error processing signal with delegation: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'signal_id': signal_id,
                'timestamp': datetime.now().isoformat()
            }

# Initialize API instance
eip7702_gmx_api = EIP7702GMXAPI()

# API Routes
@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'EIP7702 GMX Safe API with Delegation',
        'delegate_address': eip7702_gmx_api.delegate_address,
        'delegation_manager': eip7702_gmx_api.delegation_manager_address,
        'initialized': eip7702_gmx_api.initialized,
        'database_connected': eip7702_gmx_api.db_connected,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/initialize', methods=['POST'])
def initialize():
    """Initialize the EIP7702 GMX API"""
    try:
        success = eip7702_gmx_api.initialize()
        return jsonify({
            'status': 'success' if success else 'error',
            'message': 'EIP7702 GMX API initialized successfully' if success else 'Failed to initialize EIP7702 GMX API',
            'database_connected': eip7702_gmx_api.db_connected,
            'timestamp': datetime.now().isoformat()
        }), 200 if success else 500
    except Exception as e:
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/delegations/summary', methods=['GET'])
def get_delegation_summary():
    """Get comprehensive summary of delegated funds"""
    try:
        if not eip7702_gmx_api.initialized:
            return jsonify({
                'status': 'error',
                'error': 'API not initialized'
            }), 400
        
        result = eip7702_gmx_api.get_delegation_summary()
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"❌ Error getting delegation summary: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/signal/process', methods=['POST'])
def process_signal():
    """Process a trading signal using delegated funds"""
    try:
        signal_data = request.get_json()
        if not signal_data:
            return jsonify({
                'status': 'error',
                'error': 'No signal data provided'
            }), 400
        
        result = eip7702_gmx_api.process_signal_with_delegation(signal_data)
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
    """Execute a buy order using delegated funds"""
    try:
        data = request.get_json()
        token = data.get('token', 'BTC').upper()
        size_usd = data.get('size_usd', 2.0090)
        leverage = data.get('leverage', 1)
        
        result = eip7702_gmx_api.execute_buy_order_with_delegation(
            token=token, 
            size_usd=size_usd, 
            leverage=leverage
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
    """Execute a sell order using delegated funds"""
    try:
        data = request.get_json()
        token = data.get('token', 'BTC').upper()
        size_usd = data.get('size_usd')  # None means close entire position
        
        result = eip7702_gmx_api.execute_sell_order_with_delegation(
            token=token, 
            size_usd=size_usd
        )
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"❌ Error selling position: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/positions/open', methods=['GET'])
def get_open_positions_endpoint():
    """Return current open GMX positions for the provided address or delegate."""
    try:
        if not eip7702_gmx_api.initialized:
            return jsonify({'status': 'error', 'error': 'API not initialized'}), 400

        address = request.args.get('address') or eip7702_gmx_api.delegate_address
        data = GetOpenPositions(eip7702_gmx_api.config, address).get_data()
        return jsonify({
            'status': 'success',
            'address': address,
            'positions': data,
            'timestamp': datetime.now().isoformat()
        })
    except Exception as e:
        logger.error(f"❌ Error fetching open positions: {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500

@app.route('/withdraw', methods=['POST'])
def withdraw_gm():
    """Create a withdrawal order (GM -> token)."""
    try:
        data = request.get_json() or {}
        market_key = data.get('market_key')
        out_token = data.get('out_token')  # token address to receive
        gm_amount = int(data.get('gm_amount', 0))
        if not market_key or not out_token or gm_amount <= 0:
            return jsonify({'status': 'error', 'error': 'market_key, out_token, gm_amount required'}), 400
        result = eip7702_gmx_api.execute_withdrawal(market_key, out_token, gm_amount)
        return jsonify(result)
    except Exception as e:
        logger.error(f"❌ Error creating withdraw order: {e}")
        return jsonify({'status': 'error', 'error': str(e)}), 500

# Add database-specific routes
add_database_routes(app)

if __name__ == '__main__':
    # Auto-initialize if environment variables are available
    if (os.getenv('DELEGATE_ADDRESS') and 
        os.getenv('PRIVATE_KEY') and 
        os.getenv('EIP7702_DELEGATION_MANAGER_ADDRESS')):
        logger.info("🔧 Auto-initializing EIP7702 GMX API...")
        eip7702_gmx_api.initialize()
    else:
        logger.info("⚠️ Missing required environment variables - manual initialization required")
        logger.info("   Required: DELEGATE_ADDRESS, PRIVATE_KEY, EIP7702_DELEGATION_MANAGER_ADDRESS")
    
    # Start the Flask server
    port = int(os.getenv('GMX_EIP7702_API_PORT', 5002))
    logger.info(f"🚀 Starting EIP7702 GMX Safe API with Delegation on port {port}")
    app.run(host='0.0.0.0', port=port, debug=True)
