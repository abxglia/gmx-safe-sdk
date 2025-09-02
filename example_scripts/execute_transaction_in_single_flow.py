#!/usr/bin/env python3
"""
Example script demonstrating auto-execution of Safe transactions in a single flow.
This script shows how to propose and execute transactions in one API call.
"""

import os
import json
import requests
import dotenv

dotenv.load_dotenv()

def main():
    # Configuration
    api_url = os.getenv('GMX_API_URL', 'http://localhost:5001')
    safe_address = os.getenv('SAFE_ADDRESS') or os.getenv('GMX_SAFE_ADDRESS')
    
    if not safe_address:
        print('❌ SAFE_ADDRESS environment variable is required')
        return
    
    print(f"🔧 Using Safe address: {safe_address}")
    print(f"🌐 API URL: {api_url}")
    
    # Example 1: Buy order with auto-execution
    print("\n📈 Example 1: Buy order with auto-execution")
    buy_data = {
        'token': 'BTC',
        'size_usd': 1.01,
        'leverage': 1,
        'safeAddress': safe_address,
        'autoExecute': True  # This will execute the transaction immediately after proposing
    }
    
    try:
        response = requests.post(f"{api_url}/buy", json=buy_data, timeout=60)
        result = response.json()
        
        print("Buy order result:")
        print(json.dumps(result, indent=2))
        
        if result.get('status') == 'success':
            if result.get('execution', {}).get('status') == 'success':
                print("✅ Transaction proposed and executed successfully!")
            else:
                print("⚠️ Transaction proposed but execution failed")
        else:
            print("❌ Buy order failed")
            
    except Exception as e:
        print(f"❌ Error making buy request: {e}")
    
    # Example 2: Signal processing with auto-execution
    print("\n📡 Example 2: Signal processing with auto-execution")
    signal_data = {
        'Signal Message': 'buy',
        'Token Mentioned': 'ETH',
        'safeAddress': safe_address,
        'autoExecute': True,  # This will execute the transaction immediately after proposing
        'username': 'example_user'
    }
    
    try:
        response = requests.post(f"{api_url}/signal/process", json=signal_data, timeout=60)
        result = response.json()
        
        print("Signal processing result:")
        print(json.dumps(result, indent=2))
        
        if result.get('status') == 'success':
            if result.get('execution', {}).get('status') == 'success':
                print("✅ Signal processed and transaction executed successfully!")
            else:
                print("⚠️ Signal processed but execution failed")
        else:
            print("❌ Signal processing failed")
            
    except Exception as e:
        print(f"❌ Error processing signal: {e}")
    
    # Example 3: Position with TP/SL and auto-execution
    print("\n🎯 Example 3: Position with TP/SL and auto-execution")
    tp_sl_data = {
        'Signal Message': 'buy',
        'Token Mentioned': 'BTC',
        'TP1': 108900,
        'TP2': 108950,
        'SL': 108200,
        'Current Price': 108550,
        'Max Exit Time': '2025-09-27T11:20:29.000Z',
        'username': 'example_user',
        'safeAddress': safe_address,
        'autoExecute': True  # This will execute ALL transactions (main + TP + SL)
    }
    
    try:
        response = requests.post(f"{api_url}/position/create-with-tp-sl", json=tp_sl_data, timeout=60)
        result = response.json()
        
        print("TP/SL position result:")
        print(json.dumps(result, indent=2))
        
        if result.get('status') == 'success':
            execution_status = result.get('execution', {}).get('status')
            if execution_status == 'success':
                print("✅ All transactions (main + TP + SL) executed successfully!")
            elif execution_status == 'partial_success':
                executed_count = result.get('execution', {}).get('executed_count', 0)
                total_count = result.get('execution', {}).get('total_count', 0)
                print(f"⚠️ Partial success: {executed_count}/{total_count} transactions executed")
            else:
                print("❌ All transactions failed to execute")
        else:
            print("❌ TP/SL position creation failed")
            
    except Exception as e:
        print(f"❌ Error creating TP/SL position: {e}")
    
    # Example 4: Execute a specific Safe transaction
    print("\n🚀 Example 4: Execute a specific Safe transaction")
    
    # First, list pending transactions to get a safe_tx_hash
    try:
        response = requests.get(f"{api_url}/safe/pending?safeAddress={safe_address}&limit=1")
        pending_result = response.json()
        
        if pending_result.get('status') == 'success' and pending_result.get('count', 0) > 0:
            first_tx = pending_result['results'][0]
            safe_tx_hash = first_tx['safeTxHash']
            
            print(f"Found pending transaction: {safe_tx_hash}")
            
            # Execute the transaction
            execute_data = {
                'safeTxHash': safe_tx_hash,
                'safeAddress': safe_address
            }
            
            response = requests.post(f"{api_url}/safe/execute", json=execute_data, timeout=60)
            result = response.json()
            
            print("Execute transaction result:")
            print(json.dumps(result, indent=2))
            
            if result.get('status') == 'success':
                print("✅ Transaction executed successfully!")
            else:
                print("❌ Transaction execution failed")
        else:
            print("No pending transactions found")
            
    except Exception as e:
        print(f"❌ Error executing transaction: {e}")

if __name__ == '__main__':
    main()
