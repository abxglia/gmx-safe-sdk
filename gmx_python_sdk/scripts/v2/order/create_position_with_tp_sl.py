from .create_increase_order import IncreaseOrder
from .create_take_profit_order import TakeProfitOrder
from .create_stop_loss_order import StopLossOrder
import logging


class PositionWithTPSL:
    """
    Create a position with automatic Take Profit and Stop Loss orders
    This eliminates the need for manual monitoring
    """

    def __init__(
        self, 
        config, 
        market_key: str, 
        collateral_address: str,
        index_token_address: str, 
        is_long: bool, 
        size_delta: float,
        initial_collateral_delta_amount: str, 
        slippage_percent: float,
        swap_path: list,
        take_profit_price: float,
        stop_loss_price: float,
        debug_mode: bool = False,
        execution_buffer: float = 1.3
    ) -> None:
        """
        Initialize Position with TP/SL
        
        Parameters
        ----------
        take_profit_price : float
            Price at which to take profit (in USD)
        stop_loss_price : float
            Price at which to stop loss (in USD)
        
        All other parameters are the same as base Order class
        """
        self.config = config
        self.market_key = market_key
        self.collateral_address = collateral_address
        self.index_token_address = index_token_address
        self.is_long = is_long
        self.size_delta = size_delta
        self.initial_collateral_delta_amount = initial_collateral_delta_amount
        self.slippage_percent = slippage_percent
        self.swap_path = swap_path
        self.take_profit_price = take_profit_price
        self.stop_loss_price = stop_loss_price
        self.debug_mode = debug_mode
        self.execution_buffer = execution_buffer
        
        self.log = logging.getLogger(__name__)
        
        # Validate TP and SL prices make sense relative to each other
        self._validate_tp_sl_prices()
        
        # Store order instances for reference
        self.main_order = None
        self.tp_order = None
        self.sl_order = None
        
        # Create all orders
        self._create_orders()

    def _validate_tp_sl_prices(self):
        """Validate that TP and SL prices make sense for the position direction"""
        if self.is_long:
            # For long positions: TP should be above SL
            if self.take_profit_price <= self.stop_loss_price:
                raise ValueError(f"For long positions, take profit price ({self.take_profit_price}) must be above stop loss price ({self.stop_loss_price})")
        else:
            # For short positions: TP should be below SL  
            if self.take_profit_price >= self.stop_loss_price:
                raise ValueError(f"For short positions, take profit price ({self.take_profit_price}) must be below stop loss price ({self.stop_loss_price})")

    def _create_orders(self):
        """Create the main position order followed by TP and SL orders"""
        try:
            self.log.info("Creating position with TP/SL orders...")
            self.log.info(f"Position: {'LONG' if self.is_long else 'SHORT'}")
            self.log.info(f"Size: {self.size_delta}")
            self.log.info(f"Take Profit: ${self.take_profit_price}")
            self.log.info(f"Stop Loss: ${self.stop_loss_price}")
            
            # Step 1: Create main position (increase order)
            self.log.info("Step 1: Creating main position...")
            self.main_order = IncreaseOrder(
                config=self.config,
                market_key=self.market_key,
                collateral_address=self.collateral_address,
                index_token_address=self.index_token_address,
                is_long=self.is_long,
                size_delta=self.size_delta,
                initial_collateral_delta_amount=self.initial_collateral_delta_amount,
                slippage_percent=self.slippage_percent,
                swap_path=self.swap_path,
                debug_mode=self.debug_mode,
                execution_buffer=self.execution_buffer
            )
            self.log.info("✅ Main position order created")
            
            # Step 2: Create Take Profit order
            self.log.info("Step 2: Creating Take Profit order...")
            self.tp_order = TakeProfitOrder(
                trigger_price=self.take_profit_price,
                config=self.config,
                market_key=self.market_key,
                collateral_address=self.collateral_address,
                index_token_address=self.index_token_address,
                is_long=self.is_long,
                size_delta=self.size_delta,  # Will be negated in TP order
                initial_collateral_delta_amount=self.initial_collateral_delta_amount,
                slippage_percent=self.slippage_percent,
                swap_path=self.swap_path,
                debug_mode=self.debug_mode,
                execution_buffer=self.execution_buffer
            )
            self.log.info("✅ Take Profit order created")
            
            # Step 3: Create Stop Loss order
            self.log.info("Step 3: Creating Stop Loss order...")
            self.sl_order = StopLossOrder(
                trigger_price=self.stop_loss_price,
                config=self.config,
                market_key=self.market_key,
                collateral_address=self.collateral_address,
                index_token_address=self.index_token_address,
                is_long=self.is_long,
                size_delta=self.size_delta,  # Will be negated in SL order
                initial_collateral_delta_amount=self.initial_collateral_delta_amount,
                slippage_percent=self.slippage_percent,
                swap_path=self.swap_path,
                debug_mode=self.debug_mode,
                execution_buffer=self.execution_buffer
            )
            self.log.info("✅ Stop Loss order created")
            
            self.log.info("🎉 Position with TP/SL successfully created!")
            self.log.info("📈 The position will automatically exit when price reaches TP or SL levels")
            
        except Exception as e:
            self.log.error(f"❌ Error creating position with TP/SL: {e}")
            raise

    def get_order_summary(self):
        """Get a summary of all created orders"""
        return {
            'position_type': 'LONG' if self.is_long else 'SHORT',
            'size_delta': self.size_delta,
            'take_profit_price': self.take_profit_price,
            'stop_loss_price': self.stop_loss_price,
            'main_order': self.main_order,
            'take_profit_order': self.tp_order,
            'stop_loss_order': self.sl_order,
            'orders_created': {
                'main': self.main_order is not None,
                'take_profit': self.tp_order is not None,
                'stop_loss': self.sl_order is not None
            }
        }
