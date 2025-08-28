#!/usr/bin/env python3
"""
GMX + Safe API Server
Python Flask API that integrates GMX Python SDK with Safe wallet functionality
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
import requests
from dotenv import load_dotenv

# Setup logging first to avoid reference errors
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Safe SDK imports
from web3 import Web3, HTTPProvider

# Add current directory to path for imports
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import your existing GMX trader
from BTCUSDC import GMXPythonTrader

# Load environment variables from .env file
load_dotenv()
logger.info("🔧 Environment variables loaded from .env file")

# Try to import Safe SDKs from the 'safe_eth' namespace
SAFE_IMPORTS: Dict[str, Any] = {}
try:
    # Downgrade web3 version if needed for compatibility
    import web3
    logger.info(f"Using web3 version: {web3.__version__}")
    
    # Import Safe SDK from safe_eth namespace (newer versions)
    from safe_eth.safe import Safe
    from safe_eth.eth import EthereumClient
    
    # Try to import service client if available - test multiple import paths
    SafeServiceClient = None
    try:
        from safe_eth.safe.api.transaction_service_api import TransactionServiceApi as SafeServiceClient
        logger.info("✅ Using TransactionServiceApi as SafeServiceClient")
    except ImportError:
        try:
            from safe_eth.safe.services.safe_service_client import SafeServiceClient
            logger.info("✅ Using SafeServiceClient from services")
        except ImportError:
            try:
                from safe_eth.safe.api.clients import SafeServiceClient
                logger.info("✅ Using SafeServiceClient from api.clients")
            except ImportError:
                try:
                    from safe_eth.safe import SafeServiceClient
                    logger.info("✅ Using SafeServiceClient from safe")
                except ImportError:
                    logger.warning("❌ SafeServiceClient not available - transaction service features disabled")
                    SafeServiceClient = None
    
    SAFE_IMPORTS['SafeServiceClient'] = SafeServiceClient
    
    # Store the imported classes
    SAFE_IMPORTS['Safe'] = Safe
    SAFE_IMPORTS['EthereumClient'] = EthereumClient
    logger.info("Successfully imported Safe SDK from 'safe_eth' namespace")
    
except Exception as e:
    logger.warning(f"Failed to import Safe SDK: {str(e)}")
    logger.warning("Safe SDK not importable. Core Safe features disabled.")
    # Clear imports dictionary to indicate failure
    SAFE_IMPORTS = {}

# No need for a second import attempt - we've already tried in the block above
# Continue with app initialization

app = Flask(__name__)
CORS(app)

class GMXSafeAPI:
    def __init__(self):
        self.gmx_trader = None
        self.safe_api_url = os.getenv('SAFE_API_URL', 'http://localhost:3001')
        self.initialized = False
        
        # Safe SDK configuration
        self.ethereum_client = None
        self.safe_instance = None
        self.w3 = None
        
        # Network configuration
        # Network configuration - value used for reference
        self.network = 'arbitrum-one'
        self.arbitrum_rpc_url = os.getenv('RPC_URL', 'https://arb1.arbitrum.io/rpc')
        self.safe_address = os.getenv('SAFE_ADDRESS')
        self.private_key = os.getenv('PRIVATE_KEY')
        self.safe_api_key = os.getenv('SAFE_TRANSACTION_SERVICE_API_KEY')
        
        # Token mapping for GMX - updated with actual addresses from BTCUSDC.py
        self.supported_tokens = {
            'BTC': {
                'symbol': 'WBTC', 
                'market': 'BTC/USD',
                'market_key': '0x47c031236e19d024b42f8AE6780E44A573170703',  # BTC/USD market
                'index_token': '0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f',  # WBTC
                'collateral_token': '0xaf88d065e77c8cC2239327C5EDb3A432268e5831'  # USDC
            },
            'WBTC': {
                'symbol': 'WBTC', 
                'market': 'BTC/USD',
                'market_key': '0x47c031236e19d024b42f8AE6780E44A573170703',
                'index_token': '0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f',
                'collateral_token': '0xaf88d065e77c8cC2239327C5EDb3A432268e5831'
            },
            'ETH': {
                'symbol': 'WETH', 
                'market': 'ETH/USD',
                'market_key': '0x70d95587d40A2caf56bd97485aB3Eec10Bee6336',  # ETH/USD market  
                'index_token': '0x82aF49447D8a07e3bd95BD0d56f35241523fBab1',  # WETH
                'collateral_token': '0xaf88d065e77c8cC2239327C5EDb3A432268e5831'  # USDC
            },
            'WETH': {
                'symbol': 'WETH', 
                'market': 'ETH/USD',
                'market_key': '0x70d95587d40A2caf56bd97485aB3Eec10Bee6336',
                'index_token': '0x82aF49447D8a07e3bd95BD0d56f35241523fBab1',
                'collateral_token': '0xaf88d065e77c8cC2239327C5EDb3A432268e5831'
            },
            'ARB': {
                'symbol': 'ARB', 
                'market': 'ARB/USD',
                'market_key': '0xC25cEf6061Cf5dE5eb761b50E4743c1F5D7E5407',  # ARB/USD market
                'index_token': '0x912CE59144191C1204E64559FE8253a0e49E6548',  # ARB
                'collateral_token': '0xaf88d065e77c8cC2239327C5EDb3A432268e5831'  # USDC
            },
        }
    
    def initialize(self):
        """Initialize the GMX trader and Safe SDK"""
        try:
            # Initialize GMX trader
            self.gmx_trader = GMXPythonTrader(chain='arbitrum')
            
            # Setup GMX configuration with Safe wallet address instead of private key wallet
            success = self.gmx_trader.setup_config(
                wallet_address=self.safe_address,  # Use Safe address as the wallet
                private_key=self.private_key,      # Keep private key for signing
                rpc_url=self.arbitrum_rpc_url
            )
            if not success:
                raise Exception("Failed to setup GMX configuration")
            
            # Initialize Safe SDK
            self._initialize_safe_client()
            
            self.initialized = True
            logger.info("✅ GMX Safe API initialized successfully")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize GMX Safe API: {e}")
            return False
    
    def _initialize_safe_client(self):
        """Initialize Safe client and Web3 connection"""
        try:
            # Initialize Web3 connection to Arbitrum
            self.w3 = Web3(HTTPProvider(self.arbitrum_rpc_url))
            
            if not self.w3.is_connected():
                raise Exception("Failed to connect to Arbitrum RPC")
            
            # Initialize Safe client using available import path
            Safe = SAFE_IMPORTS.get('Safe')
            EthereumClient = SAFE_IMPORTS.get('EthereumClient')
            if not Safe or not EthereumClient:
                raise ImportError("Safe SDK not available. Ensure 'safe-eth-py' is installed.")

            self.ethereum_client = EthereumClient(self.arbitrum_rpc_url)
            if self.safe_address:
                self.safe_instance = Safe(self.safe_address, self.ethereum_client)
                logger.info(f"✅ Safe instance initialized for address: {self.safe_address}")
            else:
                logger.warning("⚠️ No Safe address provided - Safe transactions will require address parameter")
            
            logger.info("✅ Safe SDK client initialized successfully")
            
        except Exception as e:
            logger.error(f"❌ Failed to initialize Safe client: {e}")
            raise
    
    def _create_approval_transaction_data(self, spender: str, amount: int) -> bytes:
        """Create USDC approval transaction data"""
        from web3 import Web3
        
        # USDC approval function signature: approve(address spender, uint256 amount)
        approve_function_selector = Web3.keccak(text='approve(address,uint256)')[:4]
        
        # Encode parameters: spender address (32 bytes) + amount (32 bytes)  
        spender_padded = Web3.to_bytes(hexstr=spender).rjust(32, b'\x00')
        amount_padded = amount.to_bytes(32, byteorder='big')
        
        return approve_function_selector + spender_padded + amount_padded

    def _create_gmx_safe_transaction(self, safe_address: str, signal_type: str, token: str, 
                               position_size_usd: float, leverage: int, is_long: bool) -> Dict[str, Any]:
        """Create actual Safe transaction for GMX trade with automatic approval if needed"""
        try:
            # Initialize Safe instance for the specific address if different from default
            Safe = SAFE_IMPORTS.get('Safe')
            if safe_address != self.safe_address:
                safe_instance = SAFE_IMPORTS['Safe'](safe_address, self.ethereum_client)
            else:
                safe_instance = self.safe_instance
            
            if not safe_instance:
                raise Exception("Safe instance not initialized")
            
            # Calculate amounts first to check approval
            from decimal import Decimal
            collateral_amount = position_size_usd / leverage
            collateral_amount_wei = int(Decimal(str(collateral_amount)) * Decimal(10**6))  # USDC has 6 decimals
            
            # Check if approval is needed
            from web3 import Web3
            w3 = Web3(Web3.HTTPProvider(self.arbitrum_rpc_url))
            usdc_address = '0xaf88d065e77c8cC2239327C5EDb3A432268e5831'
            gmx_exchange_router_address = self._get_gmx_router_address()
            gmx_approval_router_address = self._get_gmx_approval_router_address()
            
            # Check current allowance and balances
            erc20_abi = [
                {
                    "constant": True,
                    "inputs": [
                        {"name": "_owner", "type": "address"},
                        {"name": "_spender", "type": "address"}
                    ],
                    "name": "allowance",
                    "outputs": [{"name": "", "type": "uint256"}],
                    "type": "function"
                },
                {
                    "constant": True,
                    "inputs": [{"name": "_owner", "type": "address"}],
                    "name": "balanceOf",
                    "outputs": [{"name": "balance", "type": "uint256"}],
                    "type": "function"
                }
            ]
            
            usdc_contract = w3.eth.contract(address=usdc_address, abi=erc20_abi)
            current_allowance = usdc_contract.functions.allowance(safe_address, gmx_approval_router_address).call()
            usdc_balance = usdc_contract.functions.balanceOf(safe_address).call()
            eth_balance = w3.eth.get_balance(safe_address)
            
            # GMX V2 requires ETH for execution fee
            execution_fee_wei = Web3.to_wei(0.00001, 'ether')
            
            approval_needed = current_allowance < collateral_amount_wei
            logger.info(f"💰 Balance Check:")
            logger.info(f"   ETH Balance: {Web3.from_wei(eth_balance, 'ether')} ETH")
            logger.info(f"   USDC Balance: {usdc_balance / 10**6} USDC")
            logger.info(f"   Required ETH: {Web3.from_wei(execution_fee_wei, 'ether')} ETH")
            logger.info(f"   Required USDC: {collateral_amount_wei / 10**6} USDC")
            logger.info(f"   Current allowance: {current_allowance}, Required: {collateral_amount_wei}")
            logger.info(f"   Approval needed: {approval_needed}")
            
            # Check if we have sufficient balances
            if eth_balance < execution_fee_wei:
                raise Exception(f"Insufficient ETH balance. Have: {Web3.from_wei(eth_balance, 'ether')} ETH, Need: {Web3.from_wei(execution_fee_wei, 'ether')} ETH")
            
            if usdc_balance < collateral_amount_wei:
                raise Exception(f"Insufficient USDC balance. Have: {usdc_balance / 10**6} USDC, Need: {collateral_amount_wei / 10**6} USDC")
            
            # Prepare GMX transaction data
            gmx_tx_data = self._prepare_gmx_transaction_data(
                signal_type=signal_type,
                token=token,
                position_size_usd=position_size_usd,
                leverage=leverage,
                is_long=is_long
            )
            
            # Get next nonce for the Safe
            nonce = safe_instance.retrieve_nonce()
            
            if approval_needed:
                logger.info("⚠️ USDC approval needed but creating approval-only transaction first")
                logger.info("💡 Please execute this approval transaction, then create the GMX trade separately")
                
                # Create approval transaction data only
                # Use max approval to avoid future approvals
                max_approval = 2**256 - 1
                approval_data = self._create_approval_transaction_data(gmx_approval_router_address, max_approval)
                
                # Create Safe transaction for approval only
                safe_tx = safe_instance.build_multisig_tx(
                    to=usdc_address,
                    value=0,
                    data=approval_data,
                    operation=0,  # CALL operation
                    safe_tx_gas=0,
                    base_gas=0,
                    gas_price=0,
                    gas_token=None,
                    refund_receiver=None,
                )
                
                logger.info("✅ Created USDC approval transaction only")
                logger.info("🔄 After approving, send the signal again to create the GMX trade")
                    
            else:
                logger.info("✅ Sufficient USDC allowance exists, creating GMX trade transaction only")
                
                # GMX V2 requires ETH for execution fee (0.00001 ETH)
                from web3 import Web3
                execution_fee_wei = Web3.to_wei(0.00001, 'ether')
                
                # Create Safe transaction for GMX trade only
                safe_tx = safe_instance.build_multisig_tx(
                    to=gmx_exchange_router_address,
                    value=execution_fee_wei,  # ETH needed for GMX execution fee
                    data=gmx_tx_data,
                    operation=0,  # CALL operation
                    safe_tx_gas=0,  # Let Safe estimate
                    base_gas=0,
                    gas_price=0,
                    gas_token=None,
                    refund_receiver=None,
                )
            
            # Get transaction hash
            # safe-eth-py returns HexBytes for hashes; normalize to hex string
            safe_tx_hash = safe_tx.safe_tx_hash.hex()
            
            # If we have a private key, sign the Safe transaction directly
            signatures_hex = []
            if self.private_key:
                try:
                    logger.info(f"🔐 Signing transaction hash: {safe_tx_hash}")
                    # Use Safe SDK's built-in signing method
                    safe_tx.sign(self.private_key)
                    logger.info(f"✅ Transaction signed successfully using Safe SDK")
                    signatures_hex.append("signed")  # Just indicate it's signed
                except Exception as sign_err:
                    logger.error(f"❌ Could not sign Safe transaction: {sign_err}")
                    import traceback
                    logger.error(f"❌ Signing traceback: {traceback.format_exc()}")
            
            # Propose transaction to Safe service
            try:
                # Propose to service if available (safe-eth-py provides service client)
                SafeServiceClient = SAFE_IMPORTS.get('SafeServiceClient')
                if SafeServiceClient is None:
                    logger.warning("⚠️ SafeServiceClient not available - Safe transaction created but not proposed to service")
                    logger.info(f"💡 Manual submission required - Transaction hash: {safe_tx_hash}")
                    logger.info(f"💡 You can manually import this transaction to your Safe wallet using the transaction hash")
                else:
                    # Use the correct network enum instead of URL
                    from safe_eth.eth.ethereum_network import EthereumNetwork
                    logger.info(f"🔗 Connecting to Safe service for Arbitrum One")
                    
                    # Initialize with API key if available
                    if self.safe_api_key:
                        logger.info("🔑 Using Safe API key for authentication")
                        service_client = SafeServiceClient(
                            EthereumNetwork.ARBITRUM_ONE, 
                            api_key=self.safe_api_key
                        )
                    else:
                        logger.warning("⚠️ No Safe API key provided - using service without authentication")
                        service_client = SafeServiceClient(EthereumNetwork.ARBITRUM_ONE)
                    
                    # Post the signed transaction to Safe service
                    try:
                        # Use post_transaction method with signed SafeTx
                        result = service_client.post_transaction(safe_tx)
                        logger.info(f"✅ Safe transaction proposed successfully: {safe_tx_hash}")
                        logger.info(f"✅ Post result: {result}")
                    except Exception as method_error:
                        # If posting fails due to JWT or other API issues, provide manual import instructions
                        if "JWT token" in str(method_error) or "Missing JWT" in str(method_error):
                            logger.warning(f"⚠️ Safe transaction service requires authentication")
                            logger.info(f"💡 Transaction hash for manual import: {safe_tx_hash}")
                            logger.info(f"💡 Raw transaction data: {safe_tx.data.hex() if safe_tx.data else '0x'}")
                            logger.info(f"💡 To: {safe_tx.to}")
                            logger.info(f"💡 Value: {safe_tx.value}")
                            logger.info(f"💡 You can manually create this transaction in your Safe wallet")
                        else:
                            logger.error(f"❌ post_transaction method failed: {method_error}")
                            import traceback
                            logger.error(f"❌ Post transaction traceback: {traceback.format_exc()}")
                            raise method_error
            except Exception as e:
                logger.error(f"❌ Could not propose to Safe service: {e}")
                logger.error(f"❌ Error type: {type(e).__name__}")
                import traceback
                logger.error(f"❌ Full traceback: {traceback.format_exc()}")
                logger.info(f"💡 Transaction still created locally with hash: {safe_tx_hash}")
                logger.info("💡 Consider manually importing the transaction or checking your Safe SDK installation")
            
            return {
                'safe_tx_hash': safe_tx_hash,
                'safe_tx_data': safe_tx.data.hex() if safe_tx.data else '0x',
                'to': safe_tx.to,
                'value': safe_tx.value,
                'data': safe_tx.data.hex() if safe_tx.data else '0x',
                'operation': safe_tx.operation,
                'nonce': safe_tx.safe_nonce,
                'signatures': signatures_hex,
                'manual_import_instructions': {
                    'safe_address': safe_address,
                    'transaction_hash': safe_tx_hash,
                    'to_address': safe_tx.to,
                    'value_wei': str(safe_tx.value),
                    'data': safe_tx.data.hex() if safe_tx.data else '0x',
                    'instructions': 'Go to your Safe wallet, click New Transaction -> Contract Interaction, paste the To address and Data fields'
                }
            }
            
        except Exception as e:
            logger.error(f"❌ Error creating GMX Safe transaction: {e}")
            raise
    
    def _get_gmx_router_address(self) -> str:
        """Get GMX V2 Exchange Router address for Arbitrum"""
        # GMX V2 Exchange Router on Arbitrum - this is the main contract for createOrder
        # This is the official GMX V2 ExchangeRouter contract address
        return "0x7452c558d45f8afC8c83dAe62C3f8A5BE19c71f6"
    
    def _get_gmx_approval_router_address(self) -> str:
        """Get GMX V2 Router address for Arbitrum (used for ERC20 approvals)"""
        return "0x7452c558d45f8afC8c83dAe62C3f8A5BE19c71f6"

    def _ensure_token_approval(self, collateral_amount_wei: int) -> bool:
        """Ensure USDC is approved for GMX Router spending (like BTCUSDC.py)"""
        try:
            logger.info("🔑 Ensuring USDC approval for GMX Router...")
            
            # Minimal ERC20 ABI for approve and allowance functions
            erc20_abi = [
                {
                    "constant": False,
                    "inputs": [
                        {"name": "_spender", "type": "address"},
                        {"name": "_value", "type": "uint256"}
                    ],
                    "name": "approve",
                    "outputs": [{"name": "", "type": "bool"}],
                    "type": "function"
                },
                {
                    "constant": True,
                    "inputs": [
                        {"name": "_owner", "type": "address"},
                        {"name": "_spender", "type": "address"}
                    ],
                    "name": "allowance",
                    "outputs": [{"name": "", "type": "uint256"}],
                    "type": "function"
                },
                {
                    "constant": True,
                    "inputs": [{"name": "_owner", "type": "address"}],
                    "name": "balanceOf",
                    "outputs": [{"name": "balance", "type": "uint256"}],
                    "type": "function"
                }
            ]
            
            # Setup web3 connection
            w3 = Web3(Web3.HTTPProvider(self.arbitrum_rpc_url))
            if not w3.is_connected():
                raise Exception("Failed to connect to Arbitrum RPC")
            
            # USDC contract and GMX V2 Router (for approvals)
            usdc_address = '0xaf88d065e77c8cC2239327C5EDb3A432268e5831'
            gmx_approval_router = self._get_gmx_approval_router_address()  # Use the correct GMX V2 Router for approvals
            usdc_contract = w3.eth.contract(address=usdc_address, abi=erc20_abi)
            
            # Check current allowance
            current_allowance = usdc_contract.functions.allowance(
                self.safe_address, gmx_approval_router
            ).call()
            
            logger.info(f"   Current USDC allowance for GMX Router: {current_allowance}")
            logger.info(f"   Required collateral amount: {collateral_amount_wei}")
            
            # If allowance is sufficient, no need to approve
            if current_allowance >= collateral_amount_wei:
                logger.info("✅ Sufficient USDC allowance already exists")
                return True
            
            # Check USDC balance
            balance = usdc_contract.functions.balanceOf(self.safe_address).call()
            logger.info(f"   Safe USDC balance: {balance / 10**6} USDC")
            
            if balance < collateral_amount_wei:
                raise Exception(f"Insufficient USDC balance in Safe: {balance / 10**6} < {collateral_amount_wei / 10**6}")
            
            logger.info("⚠️ USDC approval needed but will be handled by the Safe transaction")
            logger.info("💡 The Safe transaction will include both approval and position creation")
            return True
            
        except Exception as e:
            logger.error(f"❌ Error checking token approval: {e}")
            return False

    def _build_gmx_create_order_data(self, token_config: dict, collateral_amount_wei: int, 
                                   size_delta: int, is_long: bool, safe_address: str) -> bytes:
        """Build GMX V2 ExchangeRouter.createOrder transaction data with proper ABI encoding"""
        from web3 import Web3
        from eth_abi import encode
        
        logger.info("🔧 Building GMX V2 ExchangeRouter.createOrder with proper ABI encoding...")
        
        # Calculate execution fee (0.00001 ETH in wei)
        execution_fee_wei = Web3.to_wei(0.00001, 'ether')
        
        # Calculate acceptable price with 1% slippage for market orders
        # For long positions: use a slightly higher price (allowing 1% slippage up)
        # For short positions: use a slightly lower price (allowing 1% slippage down)
        # Using uint256 max value to indicate no specific price limit (let GMX handle market price)
        acceptable_price = 2**256 - 1  # uint256 max - GMX interprets this as "use market price"
        
        # Build CreateOrderParams struct according to GMX V2 specification
        # The struct has nested structures: addresses, numbers, orderType, etc.
        
        # Addresses struct
        addresses = (
            Web3.to_checksum_address(safe_address),  # receiver
            Web3.to_checksum_address(safe_address),  # cancellationReceiver
            Web3.to_checksum_address('0x0000000000000000000000000000000000000000'),  # callbackContract
            Web3.to_checksum_address('0x0000000000000000000000000000000000000000'),  # uiFeeReceiver
            Web3.to_checksum_address(token_config['market_key']),  # market
            Web3.to_checksum_address(token_config['collateral_token']),  # initialCollateralToken
            [],  # swapPath - empty array of addresses
        )
        
        # Numbers struct
        numbers = (
            size_delta,  # sizeDeltaUsd (30 decimals)
            collateral_amount_wei,  # initialCollateralDeltaAmount
            0,  # triggerPrice - 0 for market order
            acceptable_price,  # acceptablePrice - uint256 max for market price
            execution_fee_wei,  # executionFee
            0,  # callbackGasLimit
            0,  # minOutputAmount
            0,  # validFromTime - 0 for immediate execution
        )
        
        # Complete CreateOrderParams struct - flattened format with autoCancel (GMX V2.1)
        create_order_params = (
            # Addresses section (flattened)
            Web3.to_checksum_address(safe_address),  # receiver
            Web3.to_checksum_address(safe_address),  # cancellationReceiver
            Web3.to_checksum_address('0x0000000000000000000000000000000000000000'),  # callbackContract
            Web3.to_checksum_address('0x0000000000000000000000000000000000000000'),  # uiFeeReceiver
            Web3.to_checksum_address(token_config['market_key']),  # market
            Web3.to_checksum_address(token_config['collateral_token']),  # initialCollateralToken
            [],  # swapPath - empty array of addresses
            # Numbers section (flattened)
            size_delta,  # sizeDeltaUsd (30 decimals)
            collateral_amount_wei,  # initialCollateralDeltaAmount
            0,  # triggerPrice - 0 for market order
            acceptable_price,  # acceptablePrice - uint256 max for market price
            execution_fee_wei,  # executionFee
            0,  # callbackGasLimit
            0,  # minOutputAmount
            0,  # validFromTime - 0 for immediate execution
            # Other parameters
            2 if is_long else 3,  # orderType - 2=MarketIncrease, 3=MarketDecrease
            0,  # decreasePositionSwapType
            is_long,  # isLong
            False,  # shouldUnwrapNativeToken
            False,  # autoCancel - false for standard orders
            b'\x00' * 32  # referralCode
        )
        
        logger.info(f"   GMX V2 CreateOrder Parameters (Flattened):")
        logger.info(f"   - Receiver: {create_order_params[0]}")
        logger.info(f"   - Market: {create_order_params[4]}")
        logger.info(f"   - Initial Collateral Token: {create_order_params[5]}")
        logger.info(f"   - Size Delta USD: {create_order_params[7]}")
        logger.info(f"   - Collateral Amount: {create_order_params[8]} wei")
        logger.info(f"   - Execution Fee: {create_order_params[11]} wei")
        logger.info(f"   - Order Type: {create_order_params[15]}")
        logger.info(f"   - Is Long: {create_order_params[17]}")
        logger.info(f"   - Auto Cancel: {create_order_params[19]}")
        
        # GMX V2 ExchangeRouter createOrder function signature - flattened version with autoCancel
        function_signature = "createOrder((address,address,address,address,address,address,address[]),(uint256,uint256,uint256,uint256,uint256,uint256,uint256,uint256),uint8,uint8,bool,bool,bool,bytes32)"
        function_selector = Web3.keccak(text=function_signature)[:4]
        
        # Define the ABI types for the flattened CreateOrderParams struct
        param_types = [
            'address',   # receiver
            'address',   # cancellationReceiver
            'address',   # callbackContract
            'address',   # uiFeeReceiver
            'address',   # market
            'address',   # initialCollateralToken
            'address[]', # swapPath
            'uint256',   # sizeDeltaUsd
            'uint256',   # initialCollateralDeltaAmount
            'uint256',   # triggerPrice
            'uint256',   # acceptablePrice
            'uint256',   # executionFee
            'uint256',   # callbackGasLimit
            'uint256',   # minOutputAmount
            'uint256',   # validFromTime
            'uint8',     # orderType
            'uint8',     # decreasePositionSwapType
            'bool',      # isLong
            'bool',      # shouldUnwrapNativeToken
            'bool',      # autoCancel
            'bytes32'    # referralCode
        ]
        
        # Properly encode the struct using ABI encoding
        encoded_params = encode([f"({','.join(param_types)})"], [create_order_params])
        
        # Combine function selector with encoded parameters
        encoded_data = function_selector + encoded_params
        
        logger.info(f"✅ GMX createOrder data built with proper ABI encoding: {len(encoded_data)} bytes")
        logger.info(f"   Function selector: {function_selector.hex()}")
        logger.info(f"   Encoded params length: {len(encoded_params)} bytes")
        
        return encoded_data

    def _prepare_gmx_transaction_data(self, signal_type: str, token: str, position_size_usd: float, 
                                    leverage: int, is_long: bool) -> bytes:
        """Prepare transaction data for GMX V2 ExchangeRouter.createOrder call"""
        try:
            logger.info(f"🔧 Building GMX V2 createOrder transaction data for {signal_type} {token}")
            
            # Get token configuration
            token_config = self.supported_tokens.get(token)
            if not token_config:
                raise Exception(f"Token {token} not supported")
            
            # Calculate amounts
            from decimal import Decimal
            collateral_amount = position_size_usd / leverage
            collateral_amount_wei = int(Decimal(str(collateral_amount)) * Decimal(10**6))  # USDC has 6 decimals
            size_delta = int(Decimal(str(position_size_usd)) * Decimal(10**30))  # GMX uses 30 decimals for USD
            
            logger.info(f"   Market Key: {token_config['market_key']}")
            logger.info(f"   Index Token: {token_config['index_token']}")
            logger.info(f"   Collateral Token: {token_config['collateral_token']}")
            logger.info(f"   Collateral Amount: {collateral_amount} USDC ({collateral_amount_wei} wei)")
            logger.info(f"   Size Delta: {size_delta}")
            
            # Build the createOrder transaction data manually (NO SDK usage)
            gmx_tx_data = self._build_gmx_create_order_data(
                token_config=token_config,
                collateral_amount_wei=collateral_amount_wei,
                size_delta=size_delta,
                is_long=is_long,
                safe_address=self.safe_address
            )
            
            logger.info("✅ Successfully prepared GMX V2 createOrder transaction data!")
            return gmx_tx_data
                
        except Exception as e:
            logger.error(f"❌ Error preparing GMX transaction data: {e}")
            import traceback
            logger.error(f"❌ Traceback: {traceback.format_exc()}")
            raise
    
    def get_safe_transaction_status(self, safe_address: str, safe_tx_hash: str) -> Dict[str, Any]:
        """Get the status of a Safe transaction"""
        try:
            if safe_address != self.safe_address:
                safe_instance = Safe(safe_address, self.ethereum_client)
            else:
                safe_instance = self.safe_instance
            
            if not safe_instance:
                raise Exception("Safe instance not initialized")
            
            # Get transaction from Safe service
            try:
                SafeServiceClient = SAFE_IMPORTS.get('SafeServiceClient')
                if SafeServiceClient is None:
                    raise Exception("SafeServiceClient not available")
                from safe_eth.eth.ethereum_network import EthereumNetwork
                if self.safe_api_key:
                    service_client = SafeServiceClient(EthereumNetwork.ARBITRUM_ONE, api_key=self.safe_api_key)
                else:
                    service_client = SafeServiceClient(EthereumNetwork.ARBITRUM_ONE)
                multisig_tx, tx_hash = service_client.get_safe_transaction(safe_tx_hash)

                confirmations = multisig_tx.confirmations or []
                return {
                    'status': 'success',
                    'transaction': {
                        'safe_tx_hash': safe_tx_hash,
                        'is_executed': bool(multisig_tx.is_executed),
                        'confirmations_required': multisig_tx.confirmations_required,
                        'confirmations': len(confirmations),
                        'is_approved': len(confirmations) >= multisig_tx.confirmations_required,
                        'nonce': multisig_tx.nonce,
                        'execution_date': multisig_tx.execution_date.isoformat() if multisig_tx.execution_date else None
                    },
                    'timestamp': datetime.now().isoformat()
                }
            except Exception as e:
                return {
                    'status': 'error',
                    'error': f"Transaction not found or service error: {e}",
                    'timestamp': datetime.now().isoformat()
                }
                
        except Exception as e:
            logger.error(f"❌ Error getting Safe transaction status: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def execute_safe_transaction(self, safe_address: str, safe_tx_hash: str) -> Dict[str, Any]:
        """Execute a Safe transaction (if it has enough confirmations)"""
        try:
            if safe_address != self.safe_address:
                safe_instance = Safe(safe_address, self.ethereum_client)
            else:
                safe_instance = self.safe_instance
            
            if not safe_instance:
                raise Exception("Safe instance not initialized")
            
            # Get transaction from Safe service
            SafeServiceClient = SAFE_IMPORTS.get('SafeServiceClient')
            if SafeServiceClient is None:
                raise Exception("SafeServiceClient not available")
            from safe_eth.eth.ethereum_network import EthereumNetwork
            if self.safe_api_key:
                service_client = SafeServiceClient(EthereumNetwork.ARBITRUM_ONE, api_key=self.safe_api_key)
            else:
                service_client = SafeServiceClient(EthereumNetwork.ARBITRUM_ONE)
            multisig_tx, tx_hash = service_client.get_safe_transaction(safe_tx_hash)

            if not multisig_tx.is_approved:
                return {
                    'status': 'error',
                    'error': 'Transaction does not have enough confirmations',
                    'confirmations': len(multisig_tx.confirmations or []),
                    'required': multisig_tx.confirmations_required,
                    'timestamp': datetime.now().isoformat()
                }
            
            if multisig_tx.is_executed:
                return {
                    'status': 'success',
                    'message': 'Transaction already executed',
                    'execution_date': multisig_tx.execution_date.isoformat() if multisig_tx.execution_date else None,
                    'timestamp': datetime.now().isoformat()
                }
            
            # Execute the transaction
            ethereum_tx_hash = service_client.execute_transaction(safe_tx_hash)
            
            return {
                'status': 'success',
                'message': 'Transaction executed successfully',
                'safe_tx_hash': safe_tx_hash,
                'ethereum_tx_hash': ethereum_tx_hash.hex(),
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Error executing Safe transaction: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def validate_signal(self, signal_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validate incoming signal data"""
        errors = []
        
        # Required fields
        required_fields = ['Signal Message', 'Token Mentioned', 'Current Price']
        for field in required_fields:
            if field not in signal_data:
                errors.append(f"Missing required field: {field}")
        
        # Validate token
        token = signal_data.get('Token Mentioned', '').upper()
        if token and token not in self.supported_tokens:
            errors.append(f"Token {token} not supported on GMX")
        
        # Validate signal type
        signal_type = signal_data.get('Signal Message', '').lower()
        if signal_type and signal_type not in ['buy', 'sell', 'long', 'short']:
            errors.append(f"Invalid signal type: {signal_type}")
        
        # Validate prices
        current_price = signal_data.get('Current Price')
        if current_price and (not isinstance(current_price, (int, float)) or current_price <= 0):
            errors.append("Current price must be a positive number")
        
        return {
            'is_valid': len(errors) == 0,
            'errors': errors
        }
    
    def create_safe_transaction(self, signal_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a Safe transaction proposal for GMX trade"""
        try:
            # Extract signal parameters
            signal_type = signal_data.get('Signal Message', '').lower()
            token = signal_data.get('Token Mentioned', '').upper()
            current_price = signal_data.get('Current Price')
            tp1 = signal_data.get('TP1')
            tp2 = signal_data.get('TP2') 
            sl = signal_data.get('SL')
            safe_address = signal_data.get('safeAddress', self.safe_address)
            username = signal_data.get('username', 'api_user')
            
            if not safe_address:
                raise Exception("Safe address is required")
            
            # Map signal to GMX parameters
            is_long = signal_type in ['buy', 'long']
            token_info = self.supported_tokens.get(token, {})
            
            # Calculate position size (example: $100 USD)
            position_size_usd = 2.02
            leverage = 2  # 2x leverage
            collateral_amount = position_size_usd / leverage
            
            logger.info(f"📊 Creating {signal_type.upper()} position for {token}")
            logger.info(f"   Position Size: ${position_size_usd}")
            logger.info(f"   Collateral: ${collateral_amount} USDC")
            logger.info(f"   Leverage: {leverage}x")
            logger.info(f"   Current Price: ${current_price}")
            logger.info(f"   Targets: TP1=${tp1}, TP2=${tp2}")
            logger.info(f"   Stop Loss: ${sl}")
            
            # Create actual Safe transaction
            safe_tx_result = self._create_gmx_safe_transaction(
                safe_address=safe_address,
                signal_type=signal_type,
                token=token,
                position_size_usd=position_size_usd,
                leverage=leverage,
                is_long=is_long
            )
            
            return {
                'status': 'success',
                'signalId': f"gmx_{int(time.time())}_{username}",
                'tradingPair': {
                    'userId': username,
                    'tradeId': f"{token}_{signal_type}_{int(time.time())}",
                    'safeAddress': safe_address,
                    'networkKey': 'arbitrum',
                    'status': 'proposed'
                },
                'transaction': {
                    'safeTxHash': safe_tx_result.get('safe_tx_hash'),
                    'safeTxData': safe_tx_result.get('safe_tx_data'),
                    'to': safe_tx_result.get('to'),
                    'value': safe_tx_result.get('value'),
                    'data': safe_tx_result.get('data'),
                    'operation': safe_tx_result.get('operation'),
                    'nonce': safe_tx_result.get('nonce'),
                    'token': token,
                    'signal': signal_type,
                    'positionSize': position_size_usd,
                    'collateralAmount': collateral_amount,
                    'leverage': leverage,
                    'isLong': is_long,
                    'currentPrice': current_price,
                    'targets': [tp1, tp2] if tp1 and tp2 else [tp1] if tp1 else [],
                    'stopLoss': sl
                },
                'message': 'GMX trade proposed successfully via Safe. Awaiting multisig approval.',
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Error creating Safe transaction: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    
    def _create_gmx_only_transaction(self, signal_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create Safe transaction for GMX order only (assumes approval already exists)"""
        try:
            # Extract signal parameters
            signal_type = signal_data.get('Signal Message', '').lower()
            token = signal_data.get('Token Mentioned', '').upper()
            current_price = signal_data.get('Current Price')
            tp1 = signal_data.get('TP1')
            tp2 = signal_data.get('TP2') 
            sl = signal_data.get('SL')
            safe_address = signal_data.get('safeAddress', self.safe_address)
            username = signal_data.get('username', 'api_user')
            
            if not safe_address:
                raise Exception("Safe address is required")
            
            # Map signal to GMX parameters
            is_long = signal_type in ['buy', 'long']
            token_info = self.supported_tokens.get(token, {})
            
            # Calculate position size
            position_size_usd = 2.02
            leverage = 2  # 2x leverage
            collateral_amount = position_size_usd / leverage
            
            logger.info(f"📊 Creating GMX-ONLY {signal_type.upper()} position for {token}")
            logger.info(f"   Position Size: ${position_size_usd}")
            logger.info(f"   Collateral: ${collateral_amount} USDC")
            logger.info(f"   Leverage: {leverage}x")
            logger.info(f"   Current Price: ${current_price}")
            logger.info(f"   Targets: TP1=${tp1}, TP2=${tp2}")
            logger.info(f"   Stop Loss: ${sl}")
            
            # Initialize Safe instance
            Safe = SAFE_IMPORTS.get('Safe')
            if safe_address != self.safe_address:
                safe_instance = SAFE_IMPORTS['Safe'](safe_address, self.ethereum_client)
            else:
                safe_instance = self.safe_instance
            
            if not safe_instance:
                raise Exception("Safe instance not initialized")
            
            # Get GMX Exchange Router contract address
            gmx_exchange_router_address = self._get_gmx_router_address()
            
            # Prepare GMX transaction data
            gmx_tx_data = self._prepare_gmx_transaction_data(
                signal_type=signal_type,
                token=token,
                position_size_usd=position_size_usd,
                leverage=leverage,
                is_long=is_long
            )
            
            # GMX V2 requires ETH for execution fee (0.00001 ETH)
            from web3 import Web3
            execution_fee_wei = Web3.to_wei(0.00001, 'ether')
            
            # Create Safe transaction for GMX order only
            safe_tx = safe_instance.build_multisig_tx(
                to=gmx_exchange_router_address,
                value=execution_fee_wei,  # ETH needed for GMX execution fee
                data=gmx_tx_data,
                operation=0,  # CALL operation
                safe_tx_gas=0,  # Let Safe estimate
                base_gas=0,
                gas_price=0,
                gas_token=None,
                refund_receiver=None,
            )
            
            # Get transaction hash
            safe_tx_hash = safe_tx.safe_tx_hash.hex()
            
            # Sign the transaction if private key available
            signatures_hex = []
            if self.private_key:
                try:
                    logger.info(f"🔐 Signing GMX transaction hash: {safe_tx_hash}")
                    safe_tx.sign(self.private_key)
                    logger.info(f"✅ GMX transaction signed successfully")
                    signatures_hex.append("signed")
                except Exception as sign_err:
                    logger.error(f"❌ Could not sign GMX transaction: {sign_err}")
            
            # Propose transaction to Safe service
            try:
                SafeServiceClient = SAFE_IMPORTS.get('SafeServiceClient')
                if SafeServiceClient:
                    from safe_eth.eth.ethereum_network import EthereumNetwork
                    logger.info(f"🔗 Connecting to Safe service for GMX transaction")
                    
                    if self.safe_api_key:
                        service_client = SafeServiceClient(
                            EthereumNetwork.ARBITRUM_ONE, 
                            api_key=self.safe_api_key
                        )
                    else:
                        service_client = SafeServiceClient(EthereumNetwork.ARBITRUM_ONE)
                    
                    result = service_client.post_transaction(safe_tx)
                    logger.info(f"✅ GMX Safe transaction proposed successfully: {safe_tx_hash}")
                    logger.info(f"✅ Post result: {result}")
            except Exception as e:
                logger.warning(f"⚠️ Could not propose to Safe service: {e}")
                logger.info(f"💡 Transaction created locally with hash: {safe_tx_hash}")
            
            return {
                'status': 'success',
                'signalId': f"gmx_only_{int(time.time())}_{username}",
                'tradingPair': {
                    'userId': username,
                    'tradeId': f"{token}_{signal_type}_{int(time.time())}",
                    'safeAddress': safe_address,
                    'networkKey': 'arbitrum',
                    'status': 'proposed'
                },
                'transaction': {
                    'safeTxHash': safe_tx_hash,
                    'safeTxData': safe_tx.data.hex() if safe_tx.data else '0x',
                    'to': safe_tx.to,
                    'value': safe_tx.value,
                    'data': safe_tx.data.hex() if safe_tx.data else '0x',
                    'operation': safe_tx.operation,
                    'nonce': safe_tx.safe_nonce,
                    'token': token,
                    'signal': signal_type,
                    'positionSize': position_size_usd,
                    'collateralAmount': collateral_amount,
                    'leverage': leverage,
                    'isLong': is_long,
                    'currentPrice': current_price,
                    'targets': [tp1, tp2] if tp1 and tp2 else [tp1] if tp1 else [],
                    'stopLoss': sl,
                    'executionFee': f"{Web3.from_wei(execution_fee_wei, 'ether')} ETH"
                },
                'message': 'GMX order transaction created successfully! Ready for execution in Safe wallet.',
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Error creating GMX-only transaction: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }

    def execute_gmx_trade(self, signal_data: Dict[str, Any]) -> Dict[str, Any]:
        """Execute actual GMX trade (for when Safe transaction is approved)"""
        try:
            if not self.initialized:
                raise Exception("GMX trader not initialized")
            
            signal_type = signal_data.get('Signal Message', '').lower()
            token = signal_data.get('Token Mentioned', '').upper()
            is_long = signal_type in ['buy', 'long']
            
            logger.info(f"🚀 Executing GMX {signal_type.upper()} trade for {token}")
            
            if is_long:
                # Execute long position
                order = self.gmx_trader.place_long_position()
                logger.info("✅ Long position executed successfully")
            else:
                # Execute short position (would need to implement in GMXPythonTrader)
                logger.info("⚠️ Short positions not implemented yet")
                order = None
            
            return {
                'status': 'success',
                'execution': {
                    'token': token,
                    'signal': signal_type,
                    'isLong': is_long,
                    'order': str(order) if order else None
                },
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Error executing GMX trade: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }
    
    def get_positions(self) -> Dict[str, Any]:
        """Get current GMX positions"""
        try:
            if not self.initialized:
                return {
                    'status': 'error',
                    'error': 'GMX trader not initialized'
                }
            
            positions = self.gmx_trader.get_current_positions()
            return {
                'status': 'success',
                'positions': positions,
                'timestamp': datetime.now().isoformat()
            }
            
        except Exception as e:
            logger.error(f"❌ Error getting positions: {e}")
            return {
                'status': 'error',
                'error': str(e),
                'timestamp': datetime.now().isoformat()
            }

# Initialize API instance
gmx_api = GMXSafeAPI()

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'service': 'GMX Safe API',
        'version': '1.0.0',
        'timestamp': datetime.now().isoformat(),
        'initialized': gmx_api.initialized
    })

@app.route('/initialize', methods=['POST'])
def initialize():
    """Initialize the GMX trader"""
    try:
        success = gmx_api.initialize()
        if success:
            return jsonify({
                'status': 'success',
                'message': 'GMX Safe API initialized successfully',
                'timestamp': datetime.now().isoformat()
            })
        else:
            return jsonify({
                'status': 'error',
                'error': 'Failed to initialize GMX Safe API',
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
        
        # Create Safe transaction proposal
        result = gmx_api.create_safe_transaction(signal_data)
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"❌ Error processing signal: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/signal/execute', methods=['POST'])
def execute_signal():
    """Execute a trading signal (called after Safe approval)"""
    try:
        signal_data = request.get_json()
        
        if not signal_data:
            return jsonify({
                'status': 'error',
                'error': 'No signal data provided'
            }), 400
        
        # Execute the actual GMX trade
        result = gmx_api.execute_gmx_trade(signal_data)
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"❌ Error executing signal: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/positions', methods=['GET'])
def get_positions():
    """Get current GMX positions"""
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
        'tokens': gmx_api.supported_tokens,
        'timestamp': datetime.now().isoformat()
    })

@app.route('/safe/transaction/status', methods=['GET'])
def get_safe_transaction_status():
    """Get Safe transaction status"""
    try:
        safe_address = request.args.get('safeAddress')
        safe_tx_hash = request.args.get('safeTxHash')
        
        if not safe_address or not safe_tx_hash:
            return jsonify({
                'status': 'error',
                'error': 'safeAddress and safeTxHash parameters are required'
            }), 400
        
        result = gmx_api.get_safe_transaction_status(safe_address, safe_tx_hash)
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"❌ Error getting transaction status: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/safe/transaction/execute', methods=['POST'])
def execute_safe_transaction():
    """Execute Safe transaction"""
    try:
        data = request.get_json()
        
        if not data:
            return jsonify({
                'status': 'error',
                'error': 'Request body is required'
            }), 400
        
        safe_address = data.get('safeAddress')
        safe_tx_hash = data.get('safeTxHash')
        
        if not safe_address or not safe_tx_hash:
            return jsonify({
                'status': 'error',
                'error': 'safeAddress and safeTxHash are required'
            }), 400
        
        result = gmx_api.execute_safe_transaction(safe_address, safe_tx_hash)
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"❌ Error executing transaction: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/signal/gmx-only', methods=['POST'])
def create_gmx_order_only():
    """Create only GMX order transaction (assumes approval already exists)"""
    try:
        signal_data = request.get_json()
        
        if not signal_data:
            return jsonify({
                'status': 'error',
                'error': 'No signal data provided'
            }), 400
        
        logger.info(f"📡 Received GMX-only signal: {signal_data}")
        
        # Validate signal
        validation = gmx_api.validate_signal(signal_data)
        if not validation['is_valid']:
            return jsonify({
                'status': 'error',
                'error': 'Signal validation failed',
                'details': validation['errors']
            }), 400
        
        # Force create GMX order only (skip approval check)
        result = gmx_api._create_gmx_only_transaction(signal_data)
        
        return jsonify(result)
        
    except Exception as e:
        logger.error(f"❌ Error processing GMX-only signal: {e}")
        return jsonify({
            'status': 'error',
            'error': str(e),
            'timestamp': datetime.now().isoformat()
        }), 500

@app.route('/test/signal', methods=['POST'])
def test_signal():
    """Test endpoint for signal processing"""
    test_signal_data = {
        'Signal Message': 'buy',
        'Token Mentioned': 'BTC',
        'TP1': 45000,
        'TP2': 46000,
        'SL': 42000,
        'Current Price': 43000,
        'Max Exit Time': {'$date': datetime.now().isoformat()},
        'username': 'test_user',
        'safeAddress': request.json.get('safeAddress', '0x1234567890abcdef1234567890abcdef12345678')
    }
    
    logger.info("🧪 Processing test signal")
    result = gmx_api.create_safe_transaction(test_signal_data)
    
    return jsonify({
        **result,
        'testSignal': test_signal_data
    })

if __name__ == '__main__':
    # Initialize on startup if environment variables are available
    if os.getenv('WALLET_ADDRESS') and os.getenv('PRIVATE_KEY'):
        logger.info("🔧 Auto-initializing GMX Safe API...")
        gmx_api.initialize()
    else:
        logger.info("⚠️ Missing WALLET_ADDRESS or PRIVATE_KEY - manual initialization required")
    
    # Start the Flask server
    port = int(os.getenv('GMX_PYTHON_API_PORT', 5001))
    logger.info(f"🚀 Starting GMX Safe API on port {port}")
    app.run(host='0.0.0.0', port=port, debug=True)