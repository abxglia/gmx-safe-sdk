from utils import _set_paths

_set_paths()

from gmx_python_sdk.scripts.v2.order.order_argument_parser import (
    OrderArgumentParser
)
from gmx_python_sdk.scripts.v2.order.create_position_with_tp_sl import PositionWithTPSL
from gmx_python_sdk.scripts.v2.gmx_utils import ConfigManager

# Initialize configuration
arbitrum_config_object = ConfigManager(chain='arbitrum')
arbitrum_config_object.set_config()

# Parameters for the main position
parameters = {
    "chain": 'arbitrum',

    # The market you want to trade on
    "index_token_symbol": "ETH",

    # Token to use as collateral
    "collateral_token_symbol": "USDC",

    # The token to start with
    "start_token_symbol": "USDC",

    # True for long, False for short
    "is_long": True,

    # Position size in USD
    "size_delta_usd": 50,

    # Leverage (will calculate collateral needed)
    "leverage": 2,

    # Slippage tolerance as a decimal (0.3%)
    "slippage_percent": 0.003
}

# Parse the parameters for the main position
order_parameters = OrderArgumentParser(
    arbitrum_config_object,
    is_increase=True  # This is for opening a position
).process_parameters_dictionary(
    parameters
)

# Define Take Profit and Stop Loss prices
# Current ETH price assumption: ~$3000
current_eth_price = 3000  # You should get this from the market
take_profit_price = current_eth_price * 1.10  # 10% profit target
stop_loss_price = current_eth_price * 0.95    # 5% stop loss

print(f"Creating position with automatic TP/SL:")
print(f"  Asset: ETH")
print(f"  Position: {'LONG' if parameters['is_long'] else 'SHORT'}")
print(f"  Size: ${parameters['size_delta_usd']}")
print(f"  Leverage: {parameters['leverage']}x")
print(f"  Take Profit: ${take_profit_price:.2f} (+10%)")
print(f"  Stop Loss: ${stop_loss_price:.2f} (-5%)")
print(f"  Slippage: {parameters['slippage_percent'] * 100:.1f}%")
print()

# Create position with TP and SL
position_with_tp_sl = PositionWithTPSL(
    config=arbitrum_config_object,
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
    debug_mode=True,  # Set to False for actual execution
    execution_buffer=1.3
)

# Get order summary
summary = position_with_tp_sl.get_order_summary()

print("🎉 Position with TP/SL created successfully!")
print("\n📊 Order Summary:")
print(f"  Position Type: {summary['position_type']}")
print(f"  Size Delta: {summary['size_delta']}")
print(f"  Take Profit: ${summary['take_profit_price']:.2f}")
print(f"  Stop Loss: ${summary['stop_loss_price']:.2f}")
print(f"  Orders Created:")
print(f"    ✅ Main Position: {summary['orders_created']['main']}")
print(f"    ✅ Take Profit: {summary['orders_created']['take_profit']}")
print(f"    ✅ Stop Loss: {summary['orders_created']['stop_loss']}")
print()
print("📈 Your position will automatically exit when price reaches TP or SL levels!")
print("🔄 No manual monitoring required!")
