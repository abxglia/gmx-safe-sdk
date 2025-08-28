#!/usr/bin/env python3
"""
Test script for the new TP/SL API endpoint
Demonstrates how to create positions with automatic Take Profit and Stop Loss
"""

import requests
import json
from datetime import datetime

# API Configuration
API_BASE_URL = "http://localhost:5001"  # Update this to your API URL
API_HEADERS = {
    'Content-Type': 'application/json'
}

def test_health_check():
    """Test if the API is running"""
    try:
        response = requests.get(f"{API_BASE_URL}/health", headers=API_HEADERS)
        if response.status_code == 200:
            print("✅ API is running")
            data = response.json()
            print(f"   Safe Address: {data.get('safe_address')}")
            print(f"   Initialized: {data.get('initialized')}")
            return True
        else:
            print(f"❌ API health check failed: {response.status_code}")
            return False
    except Exception as e:
        print(f"❌ Could not connect to API: {e}")
        return False

def test_create_position_with_tp_sl():
    """Test creating a position with TP and SL"""
    try:
        # Example: Long ETH position with 10% profit target and 5% stop loss
        current_eth_price = 3000  # Assume current ETH price (you would get this from market data)
        
        position_data = {
            "token": "ETH",
            "size_usd": 50.0,           # $50 position
            "leverage": 2,              # 2x leverage
            "is_long": True,            # Long position
            "take_profit_price": current_eth_price * 1.10,  # +10% profit target
            "stop_loss_price": current_eth_price * 0.95     # -5% stop loss
        }
        
        print("🎯 Testing position creation with TP/SL:")
        print(f"   Token: {position_data['token']}")
        print(f"   Position: {'LONG' if position_data['is_long'] else 'SHORT'}")
        print(f"   Size: ${position_data['size_usd']}")
        print(f"   Leverage: {position_data['leverage']}x")
        print(f"   Take Profit: ${position_data['take_profit_price']:.2f}")
        print(f"   Stop Loss: ${position_data['stop_loss_price']:.2f}")
        print()
        
        response = requests.post(
            f"{API_BASE_URL}/position/create-with-tp-sl",
            headers=API_HEADERS,
            json=position_data
        )
        
        if response.status_code == 200:
            result = response.json()
            print("✅ Position with TP/SL created successfully!")
            print(f"   Status: {result['status']}")
            print(f"   Message: {result.get('message', 'N/A')}")
            
            position_info = result.get('position', {})
            print(f"   Position Details:")
            print(f"     Token: {position_info.get('token')}")
            print(f"     Type: {position_info.get('type')}")
            print(f"     Size: ${position_info.get('size_usd')}")
            print(f"     Collateral: ${position_info.get('collateral_usd'):.2f}")
            print(f"     Leverage: {position_info.get('leverage')}x")
            print(f"     Take Profit: ${position_info.get('take_profit_price'):.2f}")
            print(f"     Stop Loss: ${position_info.get('stop_loss_price'):.2f}")
            
            orders_created = result.get('orders_created', {})
            print(f"   Orders Created:")
            print(f"     Main Position: {orders_created.get('main', False)}")
            print(f"     Take Profit: {orders_created.get('take_profit', False)}")
            print(f"     Stop Loss: {orders_created.get('stop_loss', False)}")
            
            print(f"   Note: {result.get('note', 'N/A')}")
            
            return True
            
        else:
            error_data = response.json()
            print(f"❌ Failed to create position: {response.status_code}")
            print(f"   Error: {error_data.get('error')}")
            return False
            
    except Exception as e:
        print(f"❌ Error testing position creation: {e}")
        return False

def test_invalid_price_validation():
    """Test that API properly validates TP/SL price relationships"""
    try:
        # Test invalid long position (TP below SL)
        invalid_long_data = {
            "token": "ETH",
            "size_usd": 10.0,
            "leverage": 2,
            "is_long": True,
            "take_profit_price": 2800.0,  # Invalid: TP below SL for long
            "stop_loss_price": 3200.0
        }
        
        print("🧪 Testing price validation (should fail):")
        print("   Long position with TP below SL...")
        
        response = requests.post(
            f"{API_BASE_URL}/position/create-with-tp-sl",
            headers=API_HEADERS,
            json=invalid_long_data
        )
        
        if response.status_code == 400:
            error_data = response.json()
            print(f"✅ Validation correctly rejected invalid prices")
            print(f"   Error: {error_data.get('error')}")
            return True
        else:
            print(f"❌ Validation should have failed but didn't")
            return False
            
    except Exception as e:
        print(f"❌ Error testing validation: {e}")
        return False

def main():
    """Run API endpoint tests"""
    print("🧪 Testing TP/SL API Endpoint")
    print("=" * 50)
    
    tests = [
        ("Health Check", test_health_check),
        ("Create Position with TP/SL", test_create_position_with_tp_sl),
        ("Price Validation", test_invalid_price_validation)
    ]
    
    results = []
    for test_name, test_func in tests:
        print(f"\n📋 {test_name}:")
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
        print("🎉 TP/SL API endpoint is working correctly!")
    else:
        print("⚠️ Some tests failed. Check the API implementation.")
    
    return passed == total

if __name__ == "__main__":
    # Example usage of the new endpoint
    print("📚 Example API Usage:")
    print()
    print("curl -X POST http://localhost:5001/position/create-with-tp-sl \\")
    print("  -H 'Content-Type: application/json' \\")
    print("  -d '{")
    print('    "token": "ETH",')
    print('    "size_usd": 50.0,')
    print('    "leverage": 2,')
    print('    "is_long": true,')
    print('    "take_profit_price": 3300.0,')
    print('    "stop_loss_price": 2850.0')
    print("  }'")
    print()
    
    # Run tests if API is available
    if input("Run tests? (y/n): ").lower() == 'y':
        main()
