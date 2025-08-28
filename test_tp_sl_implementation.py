#!/usr/bin/env python3
"""
Test script for Take Profit and Stop Loss implementation
Validates that the new classes can be imported and basic functionality works
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(__file__), 'gmx_python_sdk'))

def test_imports():
    """Test that all new classes can be imported successfully"""
    try:
        from gmx_python_sdk.scripts.v2.order.create_take_profit_order import TakeProfitOrder
        from gmx_python_sdk.scripts.v2.order.create_stop_loss_order import StopLossOrder  
        from gmx_python_sdk.scripts.v2.order.create_position_with_tp_sl import PositionWithTPSL
        print("✅ All TP/SL classes imported successfully")
        return True
    except ImportError as e:
        print(f"❌ Import error: {e}")
        return False

def test_price_validation():
    """Test price validation logic"""
    try:
        from gmx_python_sdk.scripts.v2.order.create_position_with_tp_sl import PositionWithTPSL
        
        # Test valid long position prices
        try:
            # Mock config object
            class MockConfig:
                def __init__(self):
                    self.chain = 'arbitrum'
                    self.user_wallet_address = '0x1234567890123456789012345678901234567890'
                    
            # This should validate correctly for long positions  
            position = PositionWithTPSL.__new__(PositionWithTPSL)
            position.take_profit_price = 3200
            position.stop_loss_price = 2800
            position.is_long = True
            position._validate_tp_sl_prices()
            print("✅ Long position price validation passed")
            
        except ValueError:
            print("❌ Long position price validation failed")
            return False
            
        # Test valid short position prices
        try:
            position = PositionWithTPSL.__new__(PositionWithTPSL)
            position.take_profit_price = 2800
            position.stop_loss_price = 3200
            position.is_long = False
            position._validate_tp_sl_prices()
            print("✅ Short position price validation passed")
            
        except ValueError:
            print("❌ Short position price validation failed")
            return False
            
        # Test invalid prices (should raise error)
        try:
            position = PositionWithTPSL.__new__(PositionWithTPSL)
            position.take_profit_price = 2800  # Invalid: TP below SL for long
            position.stop_loss_price = 3200
            position.is_long = True
            position._validate_tp_sl_prices()
            print("❌ Invalid price validation should have failed")
            return False
            
        except ValueError:
            print("✅ Invalid price validation correctly rejected")
            
        return True
        
    except Exception as e:
        print(f"❌ Price validation test error: {e}")
        return False

def test_order_types():
    """Test that order types are correctly defined"""
    try:
        from gmx_python_sdk.scripts.v2.gmx_utils import order_type
        
        required_order_types = [
            'limit_decrease',
            'stop_loss_decrease'
        ]
        
        for order_type_name in required_order_types:
            if order_type_name in order_type:
                print(f"✅ Order type '{order_type_name}' found: {order_type[order_type_name]}")
            else:
                print(f"❌ Order type '{order_type_name}' not found")
                return False
                
        return True
        
    except Exception as e:
        print(f"❌ Order type test error: {e}")
        return False

def main():
    """Run all tests"""
    print("🧪 Testing Take Profit & Stop Loss Implementation")
    print("=" * 50)
    
    tests = [
        ("Import Test", test_imports),
        ("Price Validation Test", test_price_validation), 
        ("Order Types Test", test_order_types)
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n📋 Running {test_name}...")
        result = test_func()
        results.append(result)
        print(f"Result: {'PASS' if result else 'FAIL'}")
    
    print("\n" + "=" * 50)
    print("🎯 Test Summary:")
    
    passed = sum(results)
    total = len(results)
    
    for i, (test_name, _) in enumerate(tests):
        status = "✅ PASS" if results[i] else "❌ FAIL"
        print(f"  {test_name}: {status}")
    
    print(f"\nOverall: {passed}/{total} tests passed")
    
    if passed == total:
        print("🎉 All tests passed! TP/SL implementation is ready to use.")
        return True
    else:
        print("⚠️ Some tests failed. Please check the implementation.")
        return False

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
