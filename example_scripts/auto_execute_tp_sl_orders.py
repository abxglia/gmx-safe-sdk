#!/usr/bin/env python3
"""
Complete example demonstrating auto-execution of Take Profit and Stop Loss orders
using the Enhanced GMX API with Safe wallet integration.

This example shows how to:
1. Initialize the Enhanced GMX API
2. Create Take Profit orders with auto-execution
3. Create Stop Loss orders with auto-execution
4. Handle execution results and error cases
"""

import sys
import os
from dotenv import load_dotenv

# Add the project root to the path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

# Load environment variables
load_dotenv()

from services.enhanced_gmx_api import EnhancedGMXAPI

def demonstrate_auto_execution():
    """Demonstrate the auto-execution functionality for TP/SL orders"""
    
    # Configuration
    SAFE_ADDRESS = os.getenv('SAFE_ADDRESS')
    TOKEN = "ETH"
    SIZE_USD = 10.0
    TAKE_PROFIT_PRICE = 3200.0  # Close long position when ETH reaches $3200
    STOP_LOSS_PRICE = 2800.0    # Close long position when ETH drops to $2800
    IS_LONG = True
    
    print("🚀 Enhanced GMX API - Auto-Execute TP/SL Orders Demo")
    print("=" * 60)
    
    if not SAFE_ADDRESS:
        print("❌ Error: SAFE_ADDRESS environment variable not set")
        print("Please set your Safe wallet address in the .env file")
        return False
    
    try:
        # Initialize the Enhanced GMX API
        print("🔧 Initializing Enhanced GMX API...")
        api = EnhancedGMXAPI()
        
        if not api.initialize(safe_address=SAFE_ADDRESS):
            print("❌ Failed to initialize Enhanced GMX API")
            return False
        
        print(f"✅ API initialized successfully")
        print(f"📍 Safe Address: {SAFE_ADDRESS}")
        
        # Demo 1: Create Take Profit Order with Auto-Execution
        print(f"\n📈 Creating Take Profit Order...")
        print(f"   Token: {TOKEN}")
        print(f"   Size: ${SIZE_USD}")
        print(f"   Trigger Price: ${TAKE_PROFIT_PRICE}")
        print(f"   Position: {'LONG' if IS_LONG else 'SHORT'}")
        print(f"   Auto-Execute: True")
        
        tp_result = api.execute_take_profit_order(
            token=TOKEN,
            size_usd=SIZE_USD,
            trigger_price=TAKE_PROFIT_PRICE,
            is_long=IS_LONG,
            auto_execute=True,  # Enable auto-execution
            signal_id="demo_tp_001",
            username="demo_user"
        )
        
        print_order_result("Take Profit", tp_result)
        
        # Demo 2: Create Stop Loss Order with Auto-Execution
        print(f"\n🛡️ Creating Stop Loss Order...")
        print(f"   Token: {TOKEN}")
        print(f"   Size: ${SIZE_USD}")
        print(f"   Trigger Price: ${STOP_LOSS_PRICE}")
        print(f"   Position: {'LONG' if IS_LONG else 'SHORT'}")
        print(f"   Auto-Execute: True")
        
        sl_result = api.execute_stop_loss_order(
            token=TOKEN,
            size_usd=SIZE_USD,
            trigger_price=STOP_LOSS_PRICE,
            is_long=IS_LONG,
            auto_execute=True,  # Enable auto-execution
            signal_id="demo_sl_001",
            username="demo_user"
        )
        
        print_order_result("Stop Loss", sl_result)
        
        # Demo 3: Create orders without auto-execution for comparison
        print(f"\n📋 Creating orders WITHOUT auto-execution for comparison...")
        
        tp_result_manual = api.execute_take_profit_order(
            token=TOKEN,
            size_usd=SIZE_USD,
            trigger_price=TAKE_PROFIT_PRICE + 50,  # Different price
            is_long=IS_LONG,
            auto_execute=False,  # No auto-execution
            signal_id="demo_tp_manual",
            username="demo_user"
        )
        
        print_order_result("Take Profit (Manual)", tp_result_manual)
        
        # Summary
        print("\n" + "=" * 60)
        print("📊 Summary:")
        print("✅ Auto-execution allows orders to be submitted AND executed in one call")
        print("📋 Manual execution creates orders that must be executed separately")
        print("🔄 You can execute manual orders later using:")
        print("    api.execute_safe_transaction(safe_tx_hash)")
        
        return True
        
    except Exception as e:
        print(f"❌ Error during demo: {e}")
        return False

def print_order_result(order_type: str, result: dict):
    """Print formatted order result"""
    print(f"\n{order_type} Result:")
    
    if result.get('status') == 'success':
        print(f"   ✅ Status: Success")
        print(f"   📍 Position ID: {result.get('position_id', 'N/A')}")
        
        safe_info = result.get('safe', {})
        if safe_info.get('safeTxHash'):
            print(f"   🔗 Safe TX Hash: {safe_info['safeTxHash']}")
            
            if safe_info.get('executed'):
                print(f"   🎯 Execution: SUCCESS")
                print(f"   🔗 Execution TX: {safe_info.get('execution_tx_hash', 'N/A')}")
                print(f"   💬 Message: {safe_info.get('execution_message', 'Order executed')}")
            else:
                print(f"   ⏳ Execution: PENDING")
                if safe_info.get('execution_error'):
                    print(f"   ⚠️ Execution Error: {safe_info['execution_error']}")
        else:
            print(f"   ⚠️ No Safe transaction created")
    else:
        print(f"   ❌ Status: Error")
        print(f"   💬 Error: {result.get('error', 'Unknown error')}")

def show_usage_examples():
    """Show additional usage examples"""
    print("\n" + "=" * 60)
    print("📚 Additional Usage Examples:")
    
    examples = [
        {
            "title": "Basic TP Order with Auto-Execution",
            "code": """
api.execute_take_profit_order(
    token="BTC",
    size_usd=50.0,
    trigger_price=75000.0,
    is_long=True,
    auto_execute=True
)
"""
        },
        {
            "title": "SL Order for Short Position",
            "code": """
api.execute_stop_loss_order(
    token="ETH",
    size_usd=25.0,
    trigger_price=3500.0,  # Stop above current price for shorts
    is_long=False,         # Short position
    auto_execute=True
)
"""
        },
        {
            "title": "Manual Execution Later",
            "code": """
# Create order without auto-execution
result = api.execute_take_profit_order(
    token="ETH",
    size_usd=10.0,
    trigger_price=3200.0,
    auto_execute=False  # Create but don't execute
)

# Execute later manually
if result['status'] == 'success':
    safe_tx_hash = result['safe']['safeTxHash']
    execution_result = api.execute_safe_transaction(safe_tx_hash)
"""
        }
    ]
    
    for i, example in enumerate(examples, 1):
        print(f"\n{i}. {example['title']}:")
        print(example['code'])

def main():
    """Main function"""
    print("This demo shows auto-execution of TP/SL orders.")
    print("Make sure you have:")
    print("1. SAFE_ADDRESS set in your .env file")
    print("2. PRIVATE_KEY for a Safe owner account")
    print("3. RPC_URL for Arbitrum")
    print("4. SAFE_API_URL and SAFE_TRANSACTION_SERVICE_API_KEY")
    print("\nPress Enter to continue or Ctrl+C to exit...")
    
    try:
        input()
    except KeyboardInterrupt:
        print("\n👋 Demo cancelled by user")
        return
    
    # Run the demonstration
    success = demonstrate_auto_execution()
    
    if success:
        show_usage_examples()
        print("\n🎉 Demo completed successfully!")
        print("Check your Safe wallet for the pending/executed transactions.")
    else:
        print("\n❌ Demo failed. Please check your configuration and try again.")

if __name__ == "__main__":
    main()
