from .order import Order
from ..gas_utils import get_gas_limits
from ..gmx_utils import get_datastore_contract, order_type as order_types
import numpy as np


class StopLossOrder(Order):
    """
    Create a Stop Loss order to close a position when price reaches stop level
    Extends base Order class
    """

    def __init__(self, trigger_price: float, *args: list, **kwargs: dict) -> None:
        """
        Initialize Stop Loss Order
        
        Parameters
        ----------
        trigger_price : float
            The price at which to execute the stop loss (in USD)
        *args, **kwargs : 
            All other parameters from base Order class
        """
        # Store trigger price before calling parent constructor
        self.trigger_price = trigger_price
        
        # Call parent constructor without triggering order creation
        super().__init__(*args, **kwargs)
        
        # Create the stop loss order
        self.order_builder(is_stop_loss=True)

    def determine_gas_limits(self):
        """Set gas limits for decrease order type"""
        datastore = get_datastore_contract(self.config)
        self._gas_limits = get_gas_limits(datastore)
        self._gas_limits_order_type = self._gas_limits["decrease_order"]

    def order_builder(self, is_open=False, is_close=False, is_swap=False, is_stop_loss=False):
        """
        Create Stop Loss Order
        Override the base order_builder to handle stop loss logic
        """
        if not is_stop_loss:
            # Call parent method for non-SL orders
            return super().order_builder(is_open, is_close, is_swap)

        # Stop loss specific logic
        self.determine_gas_limits()
        gas_price = self._connection.eth.gas_price
        
        from ..gas_utils import get_execution_fee
        execution_fee = int(
            get_execution_fee(
                self._gas_limits,
                self._gas_limits_order_type,
                gas_price
            )
        )

        execution_fee = int(execution_fee * self.execution_buffer)

        from ..get.get_markets import Markets
        from ..get.get_oracle_prices import OraclePrices
        from ..gmx_utils import (
            contract_map, PRECISION, get_execution_price_and_price_impact,
            decrease_position_swap_type as decrease_position_swap_types,
            convert_to_checksum_address
        )
        from hexbytes import HexBytes
        from web3 import Web3

        markets = Markets(self.config).info
        initial_collateral_delta_amount = self.initial_collateral_delta_amount
        prices = OraclePrices(chain=self.config.chain).get_recent_prices()
        
        # For stop loss, we're always decreasing position size (negative)
        size_delta_price_price_impact = self.size_delta * -1

        callback_gas_limit = 0
        min_output_amount = 0

        # Stop Loss uses stop_loss_decrease order type
        order_type = order_types['stop_loss_decrease']

        decrease_position_swap_type = decrease_position_swap_types['no_swap']
        should_unwrap_native_token = True
        referral_code = HexBytes(
            "0x0000000000000000000000000000000000000000000000000000000000000000"
        )
        
        user_wallet_address = self.config.user_wallet_address
        eth_zero_address = "0x0000000000000000000000000000000000000000"
        ui_ref_address = "0x0000000000000000000000000000000000000000"
        
        try:
            gmx_market_address = Web3.to_checksum_address(self.market_key)
        except AttributeError:
            gmx_market_address = Web3.toChecksumAddress(self.market_key)

        # Get current market price for validation
        decimals = markets[self.market_key]['market_metadata']['decimals']
        current_price = np.median([
            float(prices[self.index_token_address]['maxPriceFull']),
            float(prices[self.index_token_address]['minPriceFull'])
        ])

        # Convert trigger price to the correct format (with proper decimals)
        trigger_price_with_decimals = int(self.trigger_price * (10 ** decimals))
        
        # Validate trigger price makes sense for stop loss
        current_price_usd = current_price * 10 ** (decimals - PRECISION)
        if self.is_long:
            # For long positions, stop loss should be below current price
            if self.trigger_price >= current_price_usd:
                raise ValueError(f"Stop loss price {self.trigger_price} should be below current price {current_price_usd:.4f} for long positions")
        else:
            # For short positions, stop loss should be above current price  
            if self.trigger_price <= current_price_usd:
                raise ValueError(f"Stop loss price {self.trigger_price} should be above current price {current_price_usd:.4f} for short positions")

        self.log.info(f"Creating Stop Loss order:")
        self.log.info(f"  Current price: ${current_price_usd:.4f}")
        self.log.info(f"  Trigger price: ${self.trigger_price:.4f}")
        self.log.info(f"  Position: {'LONG' if self.is_long else 'SHORT'}")
        self.log.info(f"  Size delta: {self.size_delta}")

        # For stop loss, acceptable price should allow more slippage as it's emergency exit
        slippage_multiplier = 2.0  # Allow 2x normal slippage for stop loss
        if self.is_long:
            # Long SL: selling at lower price, so acceptable price should be even lower
            acceptable_price = int(trigger_price_with_decimals * (1 - self.slippage_percent * slippage_multiplier))
        else:
            # Short SL: buying to close at higher price, so acceptable price should be even higher
            acceptable_price = int(trigger_price_with_decimals * (1 + self.slippage_percent * slippage_multiplier))

        user_wallet_address = convert_to_checksum_address(self.config, user_wallet_address)
        cancellation_receiver = user_wallet_address
        eth_zero_address = convert_to_checksum_address(self.config, eth_zero_address)
        ui_ref_address = convert_to_checksum_address(self.config, ui_ref_address)
        collateral_address = convert_to_checksum_address(self.config, self.collateral_address)

        auto_cancel = self.auto_cancel

        # Build order arguments with trigger price
        arguments = (
            (
                user_wallet_address,           # receiver
                cancellation_receiver,         # cancellationReceiver  
                eth_zero_address,             # callbackContract
                ui_ref_address,               # uiFeeReceiver
                gmx_market_address,           # market
                collateral_address,           # initialCollateralToken
                self.swap_path                # swapPath
            ),
            (
                self.size_delta,                    # sizeDeltaUsd (negative for decrease)
                self.initial_collateral_delta_amount, # initialCollateralDeltaAmount
                trigger_price_with_decimals,        # triggerPrice - THIS IS THE KEY CHANGE
                acceptable_price,                   # acceptablePrice
                execution_fee,                      # executionFee
                callback_gas_limit,                 # callbackGasLimit
                int(min_output_amount),            # minOutputAmount
                0                                  # validFromTime
            ),
            order_type,                      # orderType (stop_loss_decrease = 6)
            decrease_position_swap_type,     # decreasePositionSwapType
            self.is_long,                   # isLong
            should_unwrap_native_token,     # shouldUnwrapNativeToken
            auto_cancel,                    # autoCancel
            referral_code                   # referralCode
        )

        # Build multicall transaction
        value_amount = execution_fee
        multicall_args = [
            HexBytes(self._send_wnt(value_amount)),
            HexBytes(self._create_order(arguments))
        ]

        self._submit_transaction(
            user_wallet_address, value_amount, multicall_args, self._gas_limits
        )
