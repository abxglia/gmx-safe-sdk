#!/usr/bin/env python3
"""
Test script for EIP7702 GMX API
Demonstrates the core functionality and provides examples for testing
"""

import requests
import json
import time
from typing import Dict, Any

class EIP7702APITester:
    """Test client for the EIP7702 GMX API"""
    
    def __init__(self, base_url: str = "http://localhost:5002"):
        self.base_url = base_url
        self.session = requests.Session()
    
    def test_health_check(self) -> Dict[str, Any]:
        """Test the health check endpoint"""
        print("🔍 Testing health check...")
        try:
            response = self.session.get(f"{self.base_url}/health")
            result = response.json()
            print(f"✅ Health check: {result}")
            return result
        except Exception as e:
            print(f"❌ Health check failed: {e}")
            return {"status": "error", "error": str(e)}
    
    def test_initialization(self) -> Dict[str, Any]:
        """Test API initialization"""
        print("🔧 Testing API initialization...")
        try:
            response = self.session.post(f"{self.base_url}/initialize")
            result = response.json()
            print(f"✅ Initialization: {result}")
            return result
        except Exception as e:
            print(f"❌ Initialization failed: {e}")
            return {"status": "error", "error": str(e)}
    
    def test_delegation_summary(self) -> Dict[str, Any]:
        """Test delegation summary endpoint"""
        print("💰 Testing delegation summary...")
        try:
            response = self.session.get(f"{self.base_url}/delegations/summary")
            result = response.json()
            print(f"✅ Delegation summary: {result}")
            return result
        except Exception as e:
            print(f"❌ Delegation summary failed: {e}")
            return {"status": "error", "error": str(e)}
    
    def test_buy_order(self, token: str = "BTC", size_usd: float = 1.0, leverage: int = 1) -> Dict[str, Any]:
        """Test buy order execution"""
        print(f"📈 Testing buy order for {token}...")
        try:
            payload = {
                "token": token,
                "size_usd": size_usd,
                "leverage": leverage
            }
            response = self.session.post(
                f"{self.base_url}/buy",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            result = response.json()
            print(f"✅ Buy order: {result}")
            return result
        except Exception as e:
            print(f"❌ Buy order failed: {e}")
            return {"status": "error", "error": str(e)}
    
    def test_sell_order(self, token: str = "BTC", size_usd: float = None) -> Dict[str, Any]:
        """Test sell order execution"""
        print(f"📉 Testing sell order for {token}...")
        try:
            payload = {"token": token}
            if size_usd is not None:
                payload["size_usd"] = size_usd
            
            response = self.session.post(
                f"{self.base_url}/sell",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            result = response.json()
            print(f"✅ Sell order: {result}")
            return result
        except Exception as e:
            print(f"❌ Sell order failed: {e}")
            return {"status": "error", "error": str(e)}
    
    def test_signal_processing(self, signal_type: str = "buy", token: str = "BTC") -> Dict[str, Any]:
        """Test signal processing"""
        print(f"📡 Testing signal processing: {signal_type} {token}...")
        try:
            payload = {
                "Signal Message": signal_type,
                "Token Mentioned": token,
                "username": "test_user"
            }
            response = self.session.post(
                f"{self.base_url}/signal/process",
                json=payload,
                headers={"Content-Type": "application/json"}
            )
            result = response.json()
            print(f"✅ Signal processing: {result}")
            return result
        except Exception as e:
            print(f"❌ Signal processing failed: {e}")
            return {"status": "error", "error": str(e)}
    
    def run_full_test_suite(self) -> Dict[str, Any]:
        """Run the complete test suite"""
        print("🚀 Starting EIP7702 API Test Suite")
        print("=" * 50)
        
        test_results = {}
        
        # Test 1: Health Check
        test_results["health_check"] = self.test_health_check()
        time.sleep(1)
        
        # Test 2: Initialization
        test_results["initialization"] = self.test_initialization()
        time.sleep(1)
        
        # Test 3: Delegation Summary
        test_results["delegation_summary"] = self.test_delegation_summary()
        time.sleep(1)
        
        # Test 4: Buy Order
        test_results["buy_order"] = self.test_buy_order("BTC", 1.0, 1)
        time.sleep(1)
        
        # Test 5: Sell Order (partial)
        test_results["sell_order_partial"] = self.test_sell_order("BTC", 0.5)
        time.sleep(1)
        
        # Test 6: Signal Processing
        test_results["signal_processing"] = self.test_signal_processing("buy", "ETH")
        time.sleep(1)
        
        # Test 7: Final Delegation Summary
        test_results["final_delegation_summary"] = self.test_delegation_summary()
        
        print("\n" + "=" * 50)
        print("📊 Test Suite Results Summary")
        print("=" * 50)
        
        for test_name, result in test_results.items():
            status = result.get("status", "unknown")
            status_emoji = "✅" if status == "success" else "❌"
            print(f"{status_emoji} {test_name}: {status}")
        
        return test_results

def main():
    """Main function to run the test suite"""
    print("🧪 EIP7702 GMX API Test Suite")
    print("Make sure the API server is running on localhost:5002")
    print()
    
    # Check if server is accessible
    try:
        response = requests.get("http://localhost:5002/health", timeout=5)
        print("✅ API server is accessible")
    except requests.exceptions.RequestException:
        print("❌ API server is not accessible. Please start the server first.")
        print("Run: python gmx_eip7702_api.py")
        return
    
    # Run tests
    tester = EIP7702APITester()
    results = tester.run_full_test_suite()
    
    # Save results to file
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    filename = f"eip7702_test_results_{timestamp}.json"
    
    with open(filename, 'w') as f:
        json.dump(results, f, indent=2)
    
    print(f"\n💾 Test results saved to: {filename}")

if __name__ == "__main__":
    main()
