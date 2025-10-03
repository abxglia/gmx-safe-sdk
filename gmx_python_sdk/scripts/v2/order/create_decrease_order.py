from .order import Order
from ..gas_utils import get_gas_limits, get_execution_fee
from ..gmx_utils import (
    get_datastore_contract, order_type as order_types,
    decrease_position_swap_type as decrease_position_swap_types,
    convert_to_checksum_address, PRECISION
)
from ..get.get_markets import Markets
from ..get.get_oracle_prices import OraclePrices
from hexbytes import HexBytes
from web3 import Web3
import numpy as np


class DecreaseOrder(Order):
    """
    Create a market order to close/decrease a position
    Extends base Order class
    """

    def __init__(self, *args: list, **kwargs: dict) -> None:
        super().__init__(
            *args, **kwargs
        )

        # Create the close order using custom implementation
        self.order_builder(is_decrease=True)

    def determine_gas_limits(self):
        datastore = get_datastore_contract(self.config)
        self._gas_limits = get_gas_limits(datastore)
        self._gas_limits_order_type = self._gas_limits["decrease_order"]

    def order_builder(self, is_open=False, is_close=False, is_swap=False, is_decrease=False):
        """
        Create Decrease/Close Order
        Override the base order_builder to handle decrease logic properly for Safe transactions
        """
        if not is_decrease:
            # Call parent method for non-decrease orders
            return super().order_builder(is_open, is_close, is_swap)

        # Decrease/close order specific logic
        self.determine_gas_limits()
        gas_price = self._connection.eth.gas_price
        
        execution_fee = int(
            get_execution_fee(
                self._gas_limits,
                self._gas_limits_order_type,
                gas_price
            )
        )

        execution_fee = int(execution_fee * self.execution_buffer)

        markets = Markets(self.config).info
        initial_collateral_delta_amount = self.initial_collateral_delta_amount
        prices = OraclePrices(chain=self.config.chain).get_recent_prices()
        
        # For decrease orders, size delta should be negative (but we use abs() in arguments)
        size_delta_for_calculations = self.size_delta

        callback_gas_limit = 0
        min_output_amount = 0

        # Market decrease for closing positions
        order_type = order_types['market_decrease']

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

        # Get current market price and calculate acceptable price
        decimals = markets[self.market_key]['market_metadata']['decimals']
        price = np.median([
            float(prices[self.index_token_address]['maxPriceFull']),
            float(prices[self.index_token_address]['minPriceFull'])
        ])

        self.log.info(f"Mark Price: ${price * 10 ** (decimals - PRECISION):.4f}")

        # Calculate acceptable price with slippage
        # For closing a long position, we're selling, so acceptable price should be lower
        # For closing a short position, we're buying, so acceptable price should be higher
        if self.is_long:
            # Long close: selling, so acceptable price should be below current
            acceptable_price = int(price * (1 - self.slippage_percent))
        else:
            # Short close: buying, so acceptable price should be above current
            acceptable_price = int(price * (1 + self.slippage_percent))

        self.log.info(f"Acceptable price: ${acceptable_price * 10 ** (decimals - PRECISION):.4f}")

        user_wallet_address = convert_to_checksum_address(self.config, user_wallet_address)
        cancellation_receiver = user_wallet_address
        eth_zero_address = convert_to_checksum_address(self.config, eth_zero_address)
        ui_ref_address = convert_to_checksum_address(self.config, ui_ref_address)
        collateral_address = convert_to_checksum_address(self.config, self.collateral_address)

        auto_cancel = self.auto_cancel

        # Build order arguments
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
                abs(int(self.size_delta)),                    # sizeDeltaUsd
                abs(int(self.initial_collateral_delta_amount)), # initialCollateralDeltaAmount
                0,                                             # triggerPrice (0 for market order)
                abs(int(acceptable_price)),                   # acceptablePrice
                abs(int(execution_fee)),                      # executionFee
                abs(int(callback_gas_limit)),                 # callbackGasLimit
                abs(int(min_output_amount)),                  # minOutputAmount
                0                                             # validFromTime
            ),
            order_type,                      # orderType (market_decrease = 4)
            decrease_position_swap_type,     # decreasePositionSwapType
            self.is_long,                   # isLong
            should_unwrap_native_token,     # shouldUnwrapNativeToken
            auto_cancel,                    # autoCancel
            referral_code,                  # referralCode
            []                              # validFromTimes (empty bytes32 array)
        )

        # Build multicall transaction - only send execution fee for decrease orders
        value_amount = execution_fee
        multicall_args = [
            HexBytes(self._send_wnt(value_amount)),
            HexBytes(self._create_order(arguments))
        ]

        self.log.info("🎯 About to call _submit_transaction for DecreaseOrder")
        self.log.info(f"🔍 Final check - use_safe_transactions: {getattr(self.config, 'use_safe_transactions', 'NOT SET')}")

        self._submit_transaction(
            user_wallet_address, value_amount, multicall_args, self._gas_limits
        )
