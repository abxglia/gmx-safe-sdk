from utils import _set_paths

_set_paths()

from gmx_python_sdk.scripts.v2.order.order_argument_parser import (
    OrderArgumentParser
)
from gmx_python_sdk.scripts.v2.order.create_take_profit_order import TakeProfitOrder
from gmx_python_sdk.scripts.v2.gmx_utils import ConfigManager

# Initialize configuration
arbitrum_config_object = ConfigManager(chain='arbitrum')
arbitrum_config_object.set_config()

# Parameters for the take profit order
parameters = {
    "chain": 'arbitrum',

    # The market you want to trade on
    "index_token_symbol": "ETH",

    # Token to use as collateral
    "collateral_token_symbol": "USDC",

    # The token to start with (should match collateral for TP orders)
    "start_token_symbol": "USDC",

    # True for long, False for short
    "is_long": True,

    # Position size to close in USD (should match your existing position size)
    "size_delta_usd": 10,

    # Amount of collateral to withdraw (should match your position collateral)
    "initial_collateral_delta": 5,

    # Slippage tolerance as a decimal (0.5%)
    "slippage_percent": 0.005
}

# Parse the parameters
order_parameters = OrderArgumentParser(
    arbitrum_config_object,
    is_decrease=True  # Take profit is a decrease order
).process_parameters_dictionary(
    parameters
)

# Take profit trigger price (in USD)
# For long positions: should be above current market price
# For short positions: should be below current market price
take_profit_price = 3200.0  # Example: close long ETH position when price reaches $3200

print(f"Creating Take Profit order:")
print(f"  Trigger Price: ${take_profit_price}")
print(f"  Position: {'LONG' if parameters['is_long'] else 'SHORT'}")
print(f"  Size to close: ${parameters['size_delta_usd']}")

# Option 1: Create the take profit order directly with GMX SDK (original method)
print("\n=== Option 1: Direct GMX SDK Usage ===")
tp_order = TakeProfitOrder(
    trigger_price=take_profit_price,
    config=arbitrum_config_object,
    market_key=order_parameters['market_key'],
    collateral_address=order_parameters['start_token_address'],
    index_token_address=order_parameters['index_token_address'],
    is_long=order_parameters['is_long'],
    size_delta=order_parameters['size_delta'],
    initial_collateral_delta_amount=order_parameters['initial_collateral_delta'],
    slippage_percent=order_parameters['slippage_percent'],
    swap_path=[],  # No swap needed for closing
    debug_mode=True,  # Set to False for actual execution
    execution_buffer=1.5
)

print("✅ Take Profit order created successfully!")
print("📈 The order will execute automatically when ETH price reaches the trigger level")

# Option 2: Use Enhanced GMX API with auto-execution (NEW METHOD)
print("\n=== Option 2: Enhanced GMX API with Auto-Execution ===")
print("To use auto-execution with Safe wallet integration:")

example_code = '''
from services.enhanced_gmx_api import EnhancedGMXAPI

# Initialize the Enhanced GMX API
api = EnhancedGMXAPI()
api.initialize(safe_address="your_safe_address_here")

# Create and auto-execute take profit order
result = api.execute_take_profit_order(
    token="ETH",
    size_usd=10.0,                  # Size to close in USD
    trigger_price=3200.0,           # Trigger price in USD
    is_long=True,                   # True for long positions
    auto_execute=True,              # Enable auto-execution
    signal_id="optional_signal_id",
    username="your_username"
)

# Check result
if result['status'] == 'success':
    print("✅ Take Profit order created and executed!")
    if result.get('safe', {}).get('executed'):
        print("🎯 Order executed automatically!")
        print(f"Execution TX: {result['safe']['execution_tx_hash']}")
    else:
        print("📋 Order created, awaiting execution...")
        print(f"Safe TX Hash: {result['safe']['safeTxHash']}")
else:
    print(f"❌ Error: {result['error']}")
'''

print(example_code)
print("\n🚀 The Enhanced API provides:")
print("  • Automatic Safe wallet integration")
print("  • Database tracking")
print("  • Auto-execution of Safe transactions")
print("  • Error handling and recovery")
print("  • Position management")
