import json
import os
import time

from web3 import Web3

from .gmx_utils import (
    create_connection, base_dir, convert_to_checksum_address
)
from .safe_utils import build_safe_tx_payload, save_safe_tx_payload, propose_safe_transaction, get_safe_next_nonce, execute_safe_transaction


def check_if_approved(
        config,
        spender: str,
        token_to_approve: str,
        amount_of_tokens_to_spend: int,
        max_fee_per_gas,
        approve: bool,
        auto_execute: bool = False):
    """
    For a given chain, check if a given amount of tokens is approved for spend by a contract, and
    approve if needed with optional auto-execution for Safe transactions.

    Parameters
    ----------
    config : object
        Configuration object with chain details.
    spender : str
        Contract address of the requested spender.
    token_to_approve : str
        Contract address of token to spend.
    amount_of_tokens_to_spend : int
        Amount of tokens to spend in expanded decimals.
    max_fee_per_gas : int
        Maximum fee per gas for transactions.
    approve : bool
        Pass as True if we want to approve spend in case it is not already.
    auto_execute : bool
        Pass as True to automatically execute approval transactions in Safe mode.

    Returns
    -------
    dict
        Status information about the approval process.

    Raises
    ------
    Exception
        Insufficient balance or token not approved for spend.
    """

    connection = create_connection(config)

    if token_to_approve == "0x47904963fc8b2340414262125aF798B9655E58Cd":
        token_to_approve = "0x2f2a2543B76A4166549F7aaB2e75Bef0aefC5B0f"

    spender_checksum_address = convert_to_checksum_address(
        config, spender
    )

    # User wallet address will be taken from config file
    user_checksum_address = convert_to_checksum_address(
        config,
        config.user_wallet_address)

    token_checksum_address = convert_to_checksum_address(config, token_to_approve)

    token_contract_abi = json.load(open(os.path.join(
        base_dir,
        'gmx_python_sdk',
        'contracts',
        'token_approval.json'
    )))

    token_contract_obj = connection.eth.contract(address=token_to_approve,
                                                 abi=token_contract_abi)

    # TODO - for AVAX support this will need to incl WAVAX address
    if token_checksum_address == "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1":
        try:
            balance_of = connection.eth.getBalance(user_checksum_address)
        except AttributeError:
            balance_of = connection.eth.get_balance(user_checksum_address)
    else:
        balance_of = token_contract_obj.functions.balanceOf(user_checksum_address).call()

    if balance_of < amount_of_tokens_to_spend:
        raise Exception("Insufficient balance!")

    # Get current allowance
    amount_approved = token_contract_obj.functions.allowance(
        user_checksum_address,
        spender_checksum_address
    ).call()

    # Convert amounts to readable format for logging (assuming USDC with 6 decimals)
    amount_needed_readable = amount_of_tokens_to_spend / 10**6
    amount_approved_readable = amount_approved / 10**6
    
    print(f"🔍 Checking token approval...")
    print(f"   Token: {token_checksum_address}")
    print(f"   Spender: {spender_checksum_address}")
    print(f"   Amount needed: {amount_needed_readable:.6f} tokens ({amount_of_tokens_to_spend} wei)")
    print(f"   Current allowance: {amount_approved_readable:.6f} tokens ({amount_approved} wei)")

    # Check if approval is needed
    if amount_approved >= amount_of_tokens_to_spend:
        print(f"✅ Sufficient allowance exists! No approval needed.")
        return {
            'status': 'success',
            'approval_needed': False,
            'allowance_sufficient': True,
            'current_allowance': amount_approved,
            'required_amount': amount_of_tokens_to_spend,
            'message': 'Sufficient allowance already exists'
        }

    if not approve:
        raise Exception("Token not approved for spend, please allow first!")

    # Approval is needed - approve only the exact amount required
    exact_approval_readable = amount_of_tokens_to_spend / 10**6
    print(f'📝 Approving contract "{spender_checksum_address}" to spend {exact_approval_readable:.6f} tokens from {token_checksum_address}')
    print(f"   (Approving exact amount needed for this transaction)")

    # Safe mode - create and optionally execute approval transaction
    if getattr(config, 'use_safe_transactions', False):
        arguments = (spender_checksum_address, amount_of_tokens_to_spend)
        raw_txn = token_contract_obj.functions.approve(
            *arguments
        ).build_transaction({
            'value': 0,
            'chainId': config.chain_id,
            'gas': 400000,
            'maxFeePerGas': int(max_fee_per_gas),
            'maxPriorityFeePerGas': 0,
        })

        safe_payload = build_safe_tx_payload(
            config=config,
            to=token_checksum_address,
            value=0,
            data=raw_txn.get('data'),
            gas=int(raw_txn.get('gas', 0)),
            max_fee_per_gas=int(max_fee_per_gas),
            max_priority_fee_per_gas=0
        )
        filename = save_safe_tx_payload(safe_payload, prefix='approve')
        print(f"📄 Safe approval payload saved: {filename}")
        
        # Try to propose to Safe Transaction Service if API details are configured
        safe_api_url = getattr(config, 'safe_api_url', None)
        safe_api_key = getattr(config, 'safe_api_key', None)
        safe_tx_hash = None
        execution_result = None
        
        if safe_api_url:
            try:
                # Get next nonce using Safe SDK (no API key needed)
                nonce = get_safe_next_nonce(
                    safe_address=config.safe_address,
                    rpc_url=config.rpc,
                    safe_api_url=safe_api_url
                )
                
                # Propose approval transaction using Safe SDK
                proposal_result = propose_safe_transaction(
                    safe_address=config.safe_address,
                    to=token_checksum_address,
                    value="0",
                    data=raw_txn.get('data', '0x'),
                    operation=0,  # CALL
                    nonce=nonce,
                    safe_api_url=safe_api_url,
                    api_key=safe_api_key,
                    rpc_url=config.rpc,
                    private_key=config.private_key
                )
                
                if proposal_result.get('status') == 'success':
                    safe_tx_hash = proposal_result.get('safeTxHash')
                    print(f"✅ Approval proposed to Safe: {safe_tx_hash}")
                    
                    # Auto-execute if requested
                    if auto_execute and safe_tx_hash:
                        print(f"⏳ Waiting for transaction to be processed by Safe API...")
                        time.sleep(15)  # Wait for Safe Transaction Service to process the proposal
                        
                        print(f"🚀 Auto-executing approval transaction...")
                        execution_result = execute_safe_transaction(
                            safe_address=config.safe_address,
                            safe_tx_hash=safe_tx_hash,
                            rpc_url=config.rpc,
                            private_key=config.private_key,
                            safe_api_url=safe_api_url,
                            api_key=safe_api_key
                        )
                        
                        if execution_result.get('status') == 'success':
                            tx_hash = execution_result.get('txHash')
                            print(f"✅ Approval automatically executed! TX: {tx_hash}")
                            print("🎉 Token approval completed and ready for trading!")
                        else:
                            print(f"⚠️ Auto-execution failed: {execution_result.get('error')}")
                            print(f"💡 Please execute manually in Safe wallet: {safe_tx_hash}")
                    else:
                        print("🔗 View in Safe wallet and approve before creating orders")
                else:
                    print(f"⚠️ Could not propose approval to Safe API: {proposal_result.get('error')}")
                    print(f"💡 Use the saved payload manually: {filename}")
                    
            except Exception as e:
                print(f"⚠️ Safe API proposal failed: {str(e)}")
                print(f"💡 Use the saved payload manually: {filename}")
        else:
            print("💡 Submit this approval payload via your Safe before creating orders")

        return {
            'status': 'success',
            'approval_needed': True,
            'approval_proposed': safe_tx_hash is not None,
            'approval_executed': execution_result.get('status') == 'success' if execution_result else False,
            'safe_tx_hash': safe_tx_hash,
            'execution_tx_hash': execution_result.get('txHash') if execution_result else None,
            'approved_amount': amount_of_tokens_to_spend,
            'required_amount': amount_of_tokens_to_spend,
            'payload_file': filename,
            'message': 'Approval transaction created and processed'
        }
    
    # EOA mode - direct transaction
    else:
        nonce = connection.eth.get_transaction_count(user_checksum_address)

        arguments = spender_checksum_address, amount_of_tokens_to_spend
        raw_txn = token_contract_obj.functions.approve(
            *arguments
        ).build_transaction({
            'value': 0,
            'chainId': config.chain_id,
            'gas': 4000000,
            'maxFeePerGas': int(max_fee_per_gas),
            'maxPriorityFeePerGas': 0,
            'nonce': nonce})

        signed_txn = connection.eth.account.sign_transaction(raw_txn,
                                                             config.private_key)

        try:
            txn = signed_txn.rawTransaction
        except AttributeError:
            txn = signed_txn.raw_transaction

        tx_hash = connection.eth.send_raw_transaction(txn)

        print("✅ Approval transaction submitted!")
        print(f"🔗 Check status: https://arbiscan.io/tx/{tx_hash.hex()}")

        return {
            'status': 'success',
            'approval_needed': True,
            'approval_executed': True,
            'tx_hash': tx_hash.hex(),
            'approved_amount': amount_of_tokens_to_spend,
            'required_amount': amount_of_tokens_to_spend,
            'message': 'Approval transaction executed successfully'
        }


if __name__ == "__main__":

    pass
