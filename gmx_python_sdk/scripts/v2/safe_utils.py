import json
import os
import requests
from datetime import datetime
from typing import Optional, Dict, Any, List

from .gmx_utils import base_dir

try:
    from safe_eth.safe import Safe
    from safe_eth.eth import EthereumClient
    from safe_eth.safe.api import TransactionServiceApi
    SAFE_SDK_AVAILABLE = True
except ImportError:
    SAFE_SDK_AVAILABLE = False

# Database integration
try:
    from .database.transaction_tracker import transaction_tracker
    from .database.mongo_models import TransactionStatus, PositionStatus, OrderType
    DATABASE_AVAILABLE = True
except ImportError:
    DATABASE_AVAILABLE = False


def build_safe_tx_payload(
    config,
    to: str,
    value: int,
    data: Optional[bytes | str],
    gas: int = 0,
    max_fee_per_gas: int = 0,
    max_priority_fee_per_gas: int = 0,
) -> Dict[str, Any]:
    """
    Create a minimal Safe transaction payload suitable for the Safe Transaction Service
    or Transaction Builder. Gas fields are intentionally set to 0 so the service can
    estimate and fill them.
    """

    # Normalize data to hex string
    if isinstance(data, bytes):
        data_hex = '0x' + data.hex()
    else:
        data_hex = data or '0x'

    safe_address = getattr(config, 'safe_address', None) or getattr(config, 'user_wallet_address', None)

    payload = {
        "chainId": config.chain_id,
        "safeAddress": safe_address,
        "to": to,
        "value": str(value),
        "data": data_hex,
        "operation": 0,  # CALL
        # Gas fields left as 0 for service estimation
        "safeTxGas": 0,
        "baseGas": 0,
        "gasPrice": 0,
        "gasToken": "0x0000000000000000000000000000000000000000",
        "refundReceiver": "0x0000000000000000000000000000000000000000",
        # Clients can set nonce if needed; otherwise, service will assign next nonce
        "nonce": None,
        # Provide hints for clients
        "meta": {
            "createdBy": "gmx_python_sdk",
            "intendedSender": safe_address,
            "maxFeePerGasHint": int(max_fee_per_gas) if max_fee_per_gas else 0,
            "maxPriorityFeePerGasHint": int(max_priority_fee_per_gas) if max_priority_fee_per_gas else 0,
        }
    }

    return payload


def save_safe_tx_payload(payload: Dict[str, Any], prefix: str) -> str:
    """
    Save Safe payload JSON to data_store directory and return filepath.
    """
    timestamp = datetime.utcnow().strftime('%Y%m%d_%H%M%S')
    filename = f"{prefix}_safe_tx_{timestamp}.json"
    folder = os.path.join(base_dir, 'gmx_python_sdk', 'data_store')
    os.makedirs(folder, exist_ok=True)
    filepath = os.path.join(folder, filename)
    with open(filepath, 'w') as f:
        json.dump(payload, f, indent=2)
    return filepath


def propose_safe_transaction_sdk(
    safe_address: str,
    to: str,
    value: int,
    data: str,
    rpc_url: str,
    private_key: Optional[str] = None,
    operation: int = 0,
    safe_api_url: Optional[str] = None
) -> Dict[str, Any]:
    """
    Propose a transaction using the official Safe SDK (safe-eth-py).
    This is the recommended approach and doesn't require API keys.
    """
    try:
        if not SAFE_SDK_AVAILABLE:
            return {
                'status': 'error',
                'error': 'Safe SDK not available',
                'suggestion': 'pip install safe-eth-py'
            }
        
        # Initialize Ethereum client
        ethereum_client = EthereumClient(rpc_url)
        
        # Initialize Safe instance
        safe = Safe(safe_address, ethereum_client)
        
        # Build the multisig transaction
        safe_tx = safe.build_multisig_tx(
            to=to,
            value=value,
            data=bytes.fromhex(data.replace('0x', '')) if data and data != '0x' else b'',
            operation=operation,
            safe_tx_gas=0,  # Let Safe estimate
            base_gas=0,
            gas_price=0,
            gas_token=None,
            refund_receiver=None
        )
        
        # Sign the transaction if private key is provided
        if private_key:
            safe_tx.sign(private_key)
        
        # Get the Safe transaction hash
        safe_tx_hash = safe_tx.safe_tx_hash.hex()
        
        # Try to post to Safe Transaction Service using the working approach
        try:
            if safe_api_url:
                # Use the supported TransactionServiceApi (available in your environment)
                from safe_eth.safe.api.transaction_service_api import TransactionServiceApi
                from safe_eth.eth.ethereum_network import EthereumNetwork
                
                # Get API key from environment if available
                import os
                safe_api_key = os.getenv('SAFE_TRANSACTION_SERVICE_API_KEY')
                
                # Initialize TransactionServiceApi with optional API key
                if safe_api_key:
                    service_client = TransactionServiceApi(
                        EthereumNetwork.ARBITRUM_ONE,
                        api_key=safe_api_key,
                        ethereum_client=ethereum_client
                    )
                else:
                    service_client = TransactionServiceApi(
                        EthereumNetwork.ARBITRUM_ONE,
                        ethereum_client=ethereum_client
                    )
                
                # Post transaction using the working method
                result = service_client.post_transaction(safe_tx)
                
                return {
                    'status': 'success',
                    'safeTxHash': safe_tx_hash,
                    'nonce': safe_tx.safe_nonce,
                    'url': f"{safe_api_url.rstrip('/')}/api/v1/safes/{safe_address}/multisig-transactions/{safe_tx_hash}/",
                    'safe_ui_url': f"https://app.safe.global/transactions/queue?safe=arb1:{safe_address}",
                    'message': 'Transaction proposed successfully using Safe SDK - check Safe UI',
                    'post_result': str(result)
                }
            else:
                # No transaction service - return transaction hash for manual import
                return {
                    'status': 'success',
                    'safeTxHash': safe_tx_hash,
                    'nonce': safe_tx.safe_nonce,
                    'safe_ui_url': f"https://app.safe.global/transactions/queue?safe=arb1:{safe_address}",
                    'message': 'Transaction built successfully (no transaction service configured)',
                    'suggestion': 'Import the safeTxHash manually in Safe UI or use a transaction service'
                }
                
        except Exception as service_error:
            # If transaction service fails, still return success with transaction hash
            return {
                'status': 'success',
                'safeTxHash': safe_tx_hash,
                'nonce': safe_tx.safe_nonce,
                'safe_ui_url': f"https://app.safe.global/transactions/queue?safe=arb1:{safe_address}",
                'message': 'Transaction built successfully, but could not post to transaction service',
                'service_error': str(service_error),
                'suggestion': 'Import the safeTxHash manually in Safe UI or check your SAFE_TRANSACTION_SERVICE_API_KEY'
            }
            
    except Exception as e:
        return {
            'status': 'error',
            'error': f'Safe SDK error: {str(e)}',
            'suggestion': 'Check Safe address, RPC URL, and transaction parameters'
        }


def propose_safe_transaction(
    safe_address: str,
    to: str,
    value: str,
    data: str,
    operation: int = 0,
    safe_tx_gas: int = 0,
    base_gas: int = 0,
    gas_price: str = "0",
    gas_token: Optional[str] = None,
    refund_receiver: Optional[str] = None,
    nonce: Optional[int] = None,
    safe_api_url: Optional[str] = None,
    api_key: Optional[str] = None,
    rpc_url: Optional[str] = None,
    private_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Propose a transaction - tries Safe SDK first, falls back to direct API.
    """
    # Try Safe SDK approach first (recommended)
    if rpc_url and SAFE_SDK_AVAILABLE:
        return propose_safe_transaction_sdk(
            safe_address=safe_address,
            to=to,
            value=int(value),
            data=data,
            rpc_url=rpc_url,
            private_key=private_key,
            operation=operation,
            safe_api_url=safe_api_url
        )
    
    # # Fallback to direct API approach (legacy)
    # try:
    #     if not safe_api_url:
    #         return {
    #             'status': 'error',
    #             'error': 'SAFE_API_URL not provided and Safe SDK not available'
    #         }
            
    #     # Construct API endpoint
    #     api_endpoint = f"{safe_api_url.rstrip('/')}/api/v1/safes/{safe_address}/multisig-transactions/"
        
    #     # Prepare transaction payload
    #     transaction_data = {
    #         "to": to,
    #         "value": str(value),
    #         "data": data,
    #         "operation": operation,
    #         "safeTxGas": safe_tx_gas,
    #         "baseGas": base_gas,
    #         "gasPrice": str(gas_price),
    #         "gasToken": gas_token,
    #         "refundReceiver": refund_receiver,
    #         "nonce": nonce,
    #         "origin": "gmx_python_sdk"
    #     }
        
    #     # Remove None values
    #     transaction_data = {k: v for k, v in transaction_data.items() if v is not None}
        
    #     # Set up headers - try without API key first
    #     headers = {'Content-Type': 'application/json'}
        
    #     # Make API request without API key first
    #     response = requests.post(
    #         api_endpoint,
    #         json=transaction_data,
    #         headers=headers,
    #         timeout=30
    #     )
        
    #     if response.status_code == 201:
    #         result = response.json()
    #         safe_tx_hash = result.get('safeTxHash')
            
    #         return {
    #             'status': 'success',
    #             'safeTxHash': safe_tx_hash,
    #             'nonce': result.get('nonce'),
    #             'url': f"{safe_api_url.rstrip('/')}/api/v1/safes/{safe_address}/multisig-transactions/{safe_tx_hash}/",
    #             'message': 'Transaction proposed successfully to Safe (direct API)'
    #         }
    #     else:
    #         return {
    #             'status': 'error',
    #             'error': f'Safe API request failed: {response.status_code}',
    #             'details': response.text[:500],
    #             'suggestion': 'Install safe-eth-py for better compatibility: pip install safe-eth-py'
    #         }
            
    # except Exception as e:
    #     return {
    #         'status': 'error',
    #         'error': f'API error: {str(e)}',
    #         'suggestion': 'Install safe-eth-py for better compatibility: pip install safe-eth-py'
    #     }


def get_safe_next_nonce(safe_address: str, rpc_url: str, safe_api_url: Optional[str] = None) -> int:
    """
    Get the next available nonce for a Safe wallet using Safe SDK (like working implementation).
    No API key needed - uses Safe SDK's retrieve_nonce() method directly.
    """
    try:
        if not SAFE_SDK_AVAILABLE:
            print(f"⚠️ Safe SDK not available, falling back to 0 nonce")
            return 0
        
        # Initialize Safe SDK like working implementation does
        ethereum_client = EthereumClient(rpc_url)
        safe = Safe(safe_address, ethereum_client)
        
        # Use Safe SDK's built-in nonce retrieval (no API call needed)
        nonce = safe.retrieve_nonce()
        return nonce
            
    except Exception as e:
        print(f"⚠️ Safe SDK nonce error: {e}")
        # Fallback to 0 if any error occurs
        return 0


def test_safe_api_connection(safe_address: str, safe_api_url: str, api_key: Optional[str] = None) -> Dict[str, Any]:
    """
    Test connection to Safe Transaction Service API and diagnose issues.
    Some Safe APIs may require authentication depending on the service provider.
    """
    try:
        # Test basic Safe info endpoint first
        api_endpoint = f"{safe_api_url.rstrip('/')}/api/v1/safes/{safe_address}/"
        
        # Use API key if provided (like working implementation)
        headers = {'Content-Type': 'application/json'}
        if api_key:
            headers['Authorization'] = f'Token {api_key}'
        
        print(f"🔍 Testing Safe API connection...")
        print(f"   URL: {api_endpoint}")
        print(f"   API Key: {'Provided' if api_key else 'Not provided'}")
        print(f"   Headers: {headers}")
        
        response = requests.get(api_endpoint, headers=headers, timeout=10)
        
        print(f"   Response Status: {response.status_code}")
        print(f"   Response Headers: {dict(response.headers)}")
        
        if response.status_code == 200:
            safe_info = response.json()
            return {
                'status': 'success',
                'safe_info': safe_info,
                'nonce': safe_info.get('nonce', 0),
                'owners': safe_info.get('owners', []),
                'threshold': safe_info.get('threshold', 0)
            }
        elif response.status_code == 404:
            return {
                'status': 'error',
                'error': 'Safe not found',
                'details': 'Check that the Safe address is correct and exists on this network'
            }
        elif response.status_code == 403:
            return {
                'status': 'error',
                'error': 'Access forbidden - this may be a private or restricted Safe API',
                'details': 'Most Safe Transaction Service APIs are public and do not require authentication',
                'suggestion': 'Check if you are using the correct Safe Transaction Service URL for your network'
            }
        else:
            return {
                'status': 'error',
                'error': f'API request failed: {response.status_code}',
                'details': response.text[:500]
            }
            
    except requests.exceptions.RequestException as e:
        return {
            'status': 'error',
            'error': f'Network error: {str(e)}',
            'details': 'Check your internet connection and Safe API URL'
        }
    except Exception as e:
        return {
            'status': 'error',
            'error': f'Unexpected error: {str(e)}'
        }


# def confirm_safe_transaction(
#     safe_address: str,
#     safe_tx_hash: str,
#     rpc_url: str,
#     private_key: str,
#     safe_api_url: Optional[str] = None,
#     api_key: Optional[str] = None
# ) -> Dict[str, Any]:
#     """
#     Post a confirmation (signature) for a Safe transaction hash using the Safe SDK
#     and Transaction Service API. Returns status and details.
#     """
#     try:
#         if not SAFE_SDK_AVAILABLE:
#             return {
#                 'status': 'error',
#                 'error': 'Safe SDK not available',
#                 'suggestion': 'pip install safe-eth-py'
#             }

#         ethereum_client = EthereumClient(rpc_url)
#         safe = Safe(safe_address, ethereum_client)

#         # First, get the transaction from the service to build a proper SafeTx
#         if not safe_api_url:
#             return {
#                 'status': 'error',
#                 'error': 'safe_api_url is required to fetch transaction data for confirmation'
#             }

#         # Get the transaction from service
#         try:
#             from safe_eth.safe.api import TransactionServiceApi
#             from safe_eth.eth.ethereum_network import EthereumNetwork
            
#             # Initialize TransactionServiceApi with EthereumClient
#             api_service = TransactionServiceApi(EthereumNetwork.ARBITRUM_ONE, ethereum_client=ethereum_client)
#             multisig_tx, _ = api_service.get_safe_transaction(safe_tx_hash)
            
#             # Sign the transaction using the correct method
#             safe_tx = safe.build_multisig_tx(
#                 to=multisig_tx.to,
#                 value=multisig_tx.value,
#                 data=multisig_tx.data,
#                 operation=multisig_tx.operation.value if hasattr(multisig_tx.operation, 'value') else multisig_tx.operation,
#                 safe_tx_gas=multisig_tx.safe_tx_gas,
#                 base_gas=multisig_tx.base_gas,
#                 gas_price=multisig_tx.gas_price,
#                 gas_token=multisig_tx.gas_token,
#                 refund_receiver=multisig_tx.refund_receiver,
#                 safe_nonce=multisig_tx.safe_nonce
#             )
            
#             # Sign the SafeTx transaction we built
#             safe_tx.sign(private_key)
            
#             # Extract the signature from the SafeTx
#             if safe_tx.signatures:
#                 # Get the last signature (the one we just added)
#                 signature = safe_tx.signatures[-1]
#                 if hasattr(signature, 'signature'):
#                     signature_hex = signature.signature.hex() if hasattr(signature.signature, 'hex') else str(signature.signature)
#                 else:
#                     signature_hex = str(signature)
#             else:
#                 return {
#                     'status': 'error',
#                     'error': 'Failed to create signature',
#                     'suggestion': 'Check private key and transaction parameters'
#                 }
            
#             # Return success with signature (posting to service is not needed for execution)
#             return {
#                 'status': 'success',
#                 'message': 'Transaction signed successfully - signature ready for execution',
#                 'signature': signature_hex,
#                 'safe_tx_hash': safe_tx_hash,
#                 'suggestion': 'Signature created - you can now execute the transaction'
#             }
                
#         except Exception as e:
#             return {
#                 'status': 'error',
#                 'error': f'Failed to fetch transaction or create signature: {str(e)}',
#                 'suggestion': 'Check that safe_tx_hash exists and is valid'
#             }

#     except Exception as e:
#         return {
#             'status': 'error',
#             'error': str(e)
#         }


def execute_safe_transaction(
    safe_address: str,
    safe_tx_hash: str,
    rpc_url: str,
    private_key: str,
    safe_api_url: Optional[str] = None,
    api_key: Optional[str] = None
) -> Dict[str, Any]:
    """
    Attempt to execute a Safe transaction on-chain using the Safe SDK.
    Requires that the transaction has enough confirmations to meet threshold.
    Includes database logging for transaction tracking.
    """
    try:
        if not SAFE_SDK_AVAILABLE:
            return {
                'status': 'error',
                'error': 'Safe SDK not available',
                'suggestion': 'pip install safe-eth-py'
            }

        # Log transaction attempt to database
        if DATABASE_AVAILABLE:
            transaction_tracker.update_safe_transaction(
                safe_tx_hash=safe_tx_hash,
                status=TransactionStatus.CONFIRMED
            )

        ethereum_client = EthereumClient(rpc_url)
        safe = Safe(safe_address, ethereum_client)

        # Fetch tx from service
        if not safe_api_url:
            return {
                'status': 'error',
                'error': 'safe_api_url is required to fetch transaction data for execution'
            }
            
        try:
            from safe_eth.safe.api import TransactionServiceApi
            from safe_eth.eth.ethereum_network import EthereumNetwork
            
            # Initialize TransactionServiceApi with EthereumClient
            api_service = TransactionServiceApi(EthereumNetwork.ARBITRUM_ONE, ethereum_client=ethereum_client)
            multisig_tx, _ = api_service.get_safe_transaction(safe_tx_hash)
            
        except Exception as e:
            # Log failure to database
            if DATABASE_AVAILABLE:
                transaction_tracker.update_safe_transaction(
                    safe_tx_hash=safe_tx_hash,
                    status=TransactionStatus.FAILED
                )
            return {
                'status': 'error',
                'error': f'Failed to fetch transaction from service: {str(e)}'
            }

        if multisig_tx is None:
            if DATABASE_AVAILABLE:
                transaction_tracker.update_safe_transaction(
                    safe_tx_hash=safe_tx_hash,
                    status=TransactionStatus.FAILED
                )
            return {
                'status': 'error',
                'error': 'Transaction not found on service'
            }

        # Build the SafeTx for execution
        try:
            safe_tx = safe.build_multisig_tx(
                to=multisig_tx.to,
                value=multisig_tx.value,
                data=multisig_tx.data,
                operation=multisig_tx.operation.value if hasattr(multisig_tx.operation, 'value') else multisig_tx.operation,
                safe_tx_gas=multisig_tx.safe_tx_gas,
                base_gas=multisig_tx.base_gas,
                gas_price=multisig_tx.gas_price,
                gas_token=multisig_tx.gas_token,
                refund_receiver=multisig_tx.refund_receiver,
                safe_nonce=multisig_tx.safe_nonce
            )
            
            # Get existing confirmations from the API service
            try:
                confirmations = api_service.get_transaction_confirmations(safe_tx_hash)
                # Add existing signatures to SafeTx
                for confirmation in confirmations:
                    if hasattr(confirmation, 'signature') and confirmation.signature:
                        try:
                            # Import the signature into SafeTx
                            safe_tx.signatures.append(confirmation.signature)
                        except Exception:
                            pass
            except Exception:
                # If getting confirmations fails, continue without them
                pass
            
            # Add our signature if not already present
            from web3 import Account
            signer_account = Account.from_key(private_key)
            signer_address = signer_account.address.lower()
            
            # Check if we've already signed
            already_signed = False
            for sig in safe_tx.signatures:
                try:
                    if hasattr(sig, 'owner') and sig.owner.lower() == signer_address.lower():
                        already_signed = True
                        break
                except Exception:
                    continue
            
            if not already_signed:
                safe_tx.sign(private_key)
            
            # Attempt execution using the correct Safe SDK method
            tx_result = safe_tx.execute(private_key)
            tx_hash = tx_result.tx_hash if hasattr(tx_result, 'tx_hash') else tx_result
            tx_hash_str = tx_hash.hex() if hasattr(tx_hash, 'hex') else str(tx_hash)
            
            # Log successful execution to database
            if DATABASE_AVAILABLE:
                transaction_tracker.update_safe_transaction(
                    safe_tx_hash=safe_tx_hash,
                    status=TransactionStatus.EXECUTED,
                    execution_tx_hash=tx_hash_str,
                    execution_timestamp=datetime.now()
                )
            
            return {
                'status': 'success',
                'txHash': tx_hash_str,
                'message': 'Transaction executed successfully'
            }
            
        except Exception as e:
            # Log execution failure to database
            if DATABASE_AVAILABLE:
                transaction_tracker.update_safe_transaction(
                    safe_tx_hash=safe_tx_hash,
                    status=TransactionStatus.FAILED
                )
            return {
                'status': 'error',
                'error': f'Execution failed: {str(e)}',
                'hint': 'Ensure threshold confirmations are met and signer has ETH for gas'
            }

    except Exception as e:
        # Log general failure to database
        if DATABASE_AVAILABLE:
            transaction_tracker.update_safe_transaction(
                safe_tx_hash=safe_tx_hash,
                status=TransactionStatus.FAILED
            )
        return {
            'status': 'error',
            'error': str(e)
        }

def list_safe_pending_transactions(
    safe_address: str,
    safe_api_url: str,
    api_key: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> Dict[str, Any]:
    """
    Fetch queued/pending Safe transactions from the Safe Transaction Service.

    Returns a dict with a concise list of transactions including:
    - safeTxHash, nonce, isExecuted, isSuccessful, confirmationsRequired, confirmationsCount, to, value, dataSize
    """
    try:
        if not safe_api_url:
            return {
                'status': 'error',
                'error': 'SAFE_API_URL not provided'
            }

        base = safe_api_url.rstrip('/')
        # Queued includes both next and queued (unexecuted) txs
        endpoint = f"{base}/api/v1/safes/{safe_address}/multisig-transactions/"

        headers = {'Content-Type': 'application/json'}
        if api_key:
            headers['Authorization'] = f'Token {api_key}'

        params = {
            'executed': False,
            'limit': limit,
            'offset': offset,
            # Safe service supports ordering by nonce desc/asc in many deployments
            'ordering': 'nonce'
        }

        def _do_request(hdrs: Dict[str, str]):
            return requests.get(endpoint, headers=hdrs, params=params, timeout=20)

        # Try without auth first (many services are public)
        method_used = 'no_auth'
        used_headers = {'Content-Type': 'application/json'}
        response = _do_request(used_headers)

        # # If forbidden/unauthorized and api_key exists, try common header variants
        # if response.status_code in (401, 403) and api_key:
        #     # Token <key>
        #     response = _do_request(headers)
        #     method_used = 'Authorization: Token'
        #     used_headers = dict(headers)
        #     if response.status_code in (401, 403):
        #         # Bearer <key>
        #         bearer_headers = {'Content-Type': 'application/json', 'Authorization': f'Bearer {api_key}'}
        #         response = _do_request(bearer_headers)
        #         method_used = 'Authorization: Bearer'
        #         used_headers = dict(bearer_headers)
        #     if response.status_code in (401, 403):
        #         # X-Api-Key: <key>
        #         x_key_headers = {'Content-Type': 'application/json', 'X-Api-Key': api_key}
        #         response = _do_request(x_key_headers)
        #         method_used = 'X-Api-Key'
        #         used_headers = dict(x_key_headers)

        # if response.status_code != 200:
        #     return {
        #         'status': 'error',
        #         'error': f'API request failed: {response.status_code}',
        #         'details': response.text[:500],
        #         'requestUrl': endpoint,
        #         'authTried': method_used
        #     }

        data = response.json() or {}
        results: List[Dict[str, Any]] = data.get('results', data if isinstance(data, list) else [])

        simplified: List[Dict[str, Any]] = []
        for item in results:
            confirmations = item.get('confirmations', []) or []
            simplified.append({
                'safeTxHash': item.get('safeTxHash') or item.get('safe_tx_hash'),
                'nonce': item.get('nonce'),
                'isExecuted': item.get('isExecuted', False),
                'isSuccessful': item.get('isSuccessful'),
                'confirmationsRequired': item.get('confirmationsRequired') or item.get('confirmations_required'),
                'confirmationsCount': len(confirmations),
                'to': item.get('to'),
                'value': item.get('value'),
                'dataSize': len(item.get('data') or '')
            })

        return {
            'status': 'success',
            'count': len(simplified),
            'results': simplified,
            'raw': data,
            # 'requestUrl': endpoint,
            # 'authUsed': method_used
        }
    except requests.exceptions.RequestException as e:
        return {
            'status': 'error',
            'error': f'Network error: {str(e)}'
        }
    except Exception as e:
        return {
            'status': 'error',
            'error': str(e)
        }

