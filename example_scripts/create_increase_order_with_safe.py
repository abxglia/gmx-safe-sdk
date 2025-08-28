from utils import _set_paths

_set_paths()

import os

from gmx_python_sdk.scripts.v2.order.order_argument_parser import (
    OrderArgumentParser
)
from gmx_python_sdk.scripts.v2.order.create_increase_order import IncreaseOrder

from gmx_python_sdk.scripts.v2.gmx_utils import ConfigManager


# Read Safe settings from env
SAFE_ADDRESS = os.getenv('SAFE_ADDRESS')
RPC_URL = os.getenv('RPC_URL', 'https://arb1.arbitrum.io/rpc')
CHAIN_ID = int(os.getenv('CHAIN_ID', 42161))
PRIVATE_KEY = os.getenv('PRIVATE_KEY')


arbitrum_config_object = ConfigManager(chain='arbitrum')
arbitrum_config_object.set_rpc(RPC_URL)
arbitrum_config_object.set_chain_id(CHAIN_ID)
arbitrum_config_object.set_private_key(PRIVATE_KEY or '')

# Enable Safe mode: reads/balances use the Safe; transactions produce Safe payloads
arbitrum_config_object.enable_safe_transactions(SAFE_ADDRESS)

parameters = {
    "chain": 'arbitrum',
    "index_token_symbol": "GMX",
    "collateral_token_symbol": "GMX",
    "start_token_symbol": "USDC",
    "is_long": True,
    "size_delta_usd": 5,
    "leverage": 2,
    "slippage_percent": 0.003
}


order_parameters = OrderArgumentParser(
    arbitrum_config_object,
    is_increase=True
).process_parameters_dictionary(
    parameters
)

order = IncreaseOrder(
    config=arbitrum_config_object,
    market_key=order_parameters['market_key'],
    collateral_address=order_parameters['start_token_address'],
    index_token_address=order_parameters['index_token_address'],
    is_long=order_parameters['is_long'],
    size_delta=order_parameters['size_delta'],
    initial_collateral_delta_amount=(
        order_parameters['initial_collateral_delta']
    ),
    slippage_percent=order_parameters['slippage_percent'],
    swap_path=order_parameters['swap_path'],
    debug_mode=False,
    execution_buffer=1.3
)

print("If Safe mode is enabled, a Safe transaction payload should have been saved in data_store.")


