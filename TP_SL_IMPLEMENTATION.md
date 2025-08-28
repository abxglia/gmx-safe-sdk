# Take Profit & Stop Loss Implementation for GMX Python SDK

This implementation adds Take Profit (TP) and Stop Loss (SL) functionality to the GMX Python SDK, allowing you to create orders with automatic exit conditions without manual monitoring.

## Overview

The implementation includes three new order classes:

1. **`TakeProfitOrder`** - Closes positions when price reaches profitable levels
2. **`StopLossOrder`** - Closes positions when price reaches stop loss levels  
3. **`PositionWithTPSL`** - Creates a position with both TP and SL orders automatically

## Key Features

✅ **Automatic Execution** - Orders execute automatically when trigger prices are reached  
✅ **No Manual Monitoring** - Set and forget functionality  
✅ **Proper Validation** - Validates trigger prices make sense for position direction  
✅ **Slippage Protection** - Configurable slippage tolerance  
✅ **Debug Mode** - Test orders without actual execution  

## Order Types Used

| Order Class | GMX Order Type | Use Case |
|-------------|----------------|----------|
| `TakeProfitOrder` | `limit_decrease` (5) | Close at profitable price |
| `StopLossOrder` | `stop_loss_decrease` (6) | Close at loss-limiting price |

## Usage Examples

### 1. Individual Take Profit Order

```python
from gmx_python_sdk.scripts.v2.order.create_take_profit_order import TakeProfitOrder

# Create take profit order to close existing position
tp_order = TakeProfitOrder(
    trigger_price=3200.0,  # Close when ETH reaches $3200
    config=config,
    market_key=market_key,
    collateral_address=collateral_address,
    index_token_address=index_token_address,
    is_long=True,
    size_delta=position_size,
    initial_collateral_delta_amount=collateral_amount,
    slippage_percent=0.005,
    swap_path=[],
    debug_mode=False
)
```

### 2. Individual Stop Loss Order

```python
from gmx_python_sdk.scripts.v2.order.create_stop_loss_order import StopLossOrder

# Create stop loss order to limit losses
sl_order = StopLossOrder(
    trigger_price=2800.0,  # Close when ETH drops to $2800
    config=config,
    market_key=market_key,
    collateral_address=collateral_address,
    index_token_address=index_token_address,
    is_long=True,
    size_delta=position_size,
    initial_collateral_delta_amount=collateral_amount,
    slippage_percent=0.01,  # Allow more slippage for stop loss
    swap_path=[],
    debug_mode=False
)
```

### 3. Position with Automatic TP/SL

```python
from gmx_python_sdk.scripts.v2.order.create_position_with_tp_sl import PositionWithTPSL

# Create position with automatic TP and SL
position = PositionWithTPSL(
    config=config,
    market_key=market_key,
    collateral_address=collateral_address,
    index_token_address=index_token_address,
    is_long=True,
    size_delta=50,  # $50 position
    initial_collateral_delta_amount=25,  # $25 collateral (2x leverage)
    slippage_percent=0.003,
    swap_path=swap_path,
    take_profit_price=3200.0,  # +10% profit target
    stop_loss_price=2800.0,    # -5% stop loss
    debug_mode=False
)
```

## Price Validation Rules

The implementation includes automatic validation to ensure trigger prices make sense:

### For Long Positions:
- **Take Profit**: Must be ABOVE current market price ✅
- **Stop Loss**: Must be BELOW current market price ✅
- **Relationship**: Take Profit > Stop Loss ✅

### For Short Positions:
- **Take Profit**: Must be BELOW current market price ✅
- **Stop Loss**: Must be ABOVE current market price ✅
- **Relationship**: Take Profit < Stop Loss ✅

## Technical Implementation Details

### Trigger Price Handling

Unlike market orders which use `triggerPrice = 0`, TP/SL orders use specific trigger prices:

```python
# Convert USD price to proper decimals format
trigger_price_with_decimals = int(trigger_price * (10 ** decimals))

# Set in order arguments
arguments = (
    addresses_tuple,
    (
        size_delta,
        collateral_amount,
        trigger_price_with_decimals,  # Key difference from market orders
        acceptable_price,
        execution_fee,
        # ... other parameters
    ),
    order_type,  # limit_decrease (5) or stop_loss_decrease (6)
    # ... other parameters
)
```

### Slippage Handling

- **Take Profit**: Uses standard slippage tolerance
- **Stop Loss**: Uses 2x slippage tolerance for emergency exits

## Example Scripts

Run the provided example scripts to test the functionality:

```bash
# Test individual take profit order
python example_scripts/create_take_profit_order.py

# Test individual stop loss order  
python example_scripts/create_stop_loss_order.py

# Test position with both TP and SL
python example_scripts/create_position_with_tp_sl.py
```

## Error Handling

The implementation includes comprehensive error handling:

- **Invalid Trigger Prices**: Validates prices make sense for position direction
- **Price Relationship**: Ensures TP and SL prices have correct relationship
- **Market Data**: Handles missing or invalid market price data
- **Order Execution**: Proper error handling for failed order submissions

## Best Practices

1. **Test First**: Always use `debug_mode=True` to test orders before live execution
2. **Reasonable Slippage**: Use appropriate slippage tolerances (0.3-0.5% for TP, 1-2% for SL)
3. **Price Validation**: Double-check trigger prices before submitting
4. **Gas Considerations**: Account for execution fees when calculating profit targets
5. **Market Conditions**: Consider market volatility when setting trigger levels

## Limitations

- Only supports closing existing positions (decrease orders)
- Requires position to exist before creating TP/SL orders
- Cannot modify trigger prices after order creation (must cancel and recreate)
- Subject to GMX protocol limitations and fees

## Integration with Existing Code

This implementation is fully compatible with existing GMX Python SDK code:

- Extends the same base `Order` class
- Uses the same configuration and parameter patterns
- Works with existing order argument parsers
- Supports Safe wallet integration

## Future Enhancements

Potential improvements for future versions:

- **Trailing Stop Loss**: Dynamic stop loss that moves with favorable price action
- **Partial TP/SL**: Close portions of position at multiple price levels
- **OCO Orders**: One-Cancels-Other order pairs
- **Time-based Orders**: Orders that expire after certain time periods

---

**⚠️ Disclaimer**: This implementation is for educational and development purposes. Always test thoroughly before using with real funds. Trading involves risk of loss.
