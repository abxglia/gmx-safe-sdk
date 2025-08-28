#!/usr/bin/env python3

import sys
import os

# Add the SDK to the path
sys.path.append(os.path.join(os.path.dirname(__file__), 'gmx_python_sdk'))

from gmx_python_sdk.scripts.v2.gmx_utils import ConfigManager, get_tokens_address_dict
from gmx_python_sdk.scripts.v2.get.get_markets import Markets
import json


def get_all_tokens_and_markets(chain='arbitrum'):
    """
    Get all tokens and their market information using GMX Python SDK
    
    Parameters:
    -----------
    chain : str
        The chain to query ('arbitrum' or 'avalanche')
        
    Returns:
    --------
    dict : Complete token and market information
    """
    
    print(f"Fetching token and market data for {chain}...")
    
    # Initialize config
    config = ConfigManager(chain=chain)
    config.set_config()
    
    # Get all tokens available on the chain
    print("Getting token addresses...")
    tokens_dict = get_tokens_address_dict(chain)
    
    # Get all markets
    print("Getting market information...")
    markets = Markets(config)
    markets_info = markets.get_available_markets()
    
    # Combine the information
    result = {
        'chain': chain,
        'tokens': tokens_dict,
        'markets': markets_info,
        'summary': {
            'total_tokens': len(tokens_dict),
            'total_markets': len(markets_info)
        }
    }
    
    # Print summary
    print(f"\nSummary for {chain.upper()}:")
    print(f"Total tokens: {len(tokens_dict)}")
    print(f"Total markets: {len(markets_info)}")
    
    # Print market details
    print(f"\nMarket Details:")
    print("-" * 120)
    print(f"{'Market Key':<45} {'Symbol':<15} {'Index Token':<45} {'Long Token':<45} {'Short Token':<45}")
    print("-" * 120)
    
    for market_key, market_info in markets_info.items():
        symbol = market_info.get('market_symbol', 'N/A')
        index_token = market_info.get('index_token_address', 'N/A')
        long_token = market_info.get('long_token_address', 'N/A') 
        short_token = market_info.get('short_token_address', 'N/A')
        
        print(f"{market_key:<45} {symbol:<15} {index_token:<45} {long_token:<45} {short_token:<45}")
    
    return result


def save_to_file(data, filename):
    """Save data to JSON file"""
    with open(filename, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"\nData saved to {filename}")


if __name__ == "__main__":
    # You can change the chain here ('arbitrum' or 'avalanche')
    chain = 'arbitrum'
    
    try:
        # Get all token and market data
        data = get_all_tokens_and_markets(chain)
        
        # Optionally save to file
        filename = f"{chain}_tokens_and_markets.json"
        save_to_file(data, filename)
        
        # # Also try avalanche if arbitrum works
        # print(f"\n{'='*60}")
        # print("Now fetching data for Avalanche...")
        # print(f"{'='*60}")
        
        # avalanche_data = get_all_tokens_and_markets('avalanche')
        # avalanche_filename = "avalanche_tokens_and_markets.json"
        # save_to_file(avalanche_data, avalanche_filename)
        
    except Exception as e:
        print(f"Error: {e}")
        print("Make sure you have:")
        print("1. Installed the gmx_python_sdk package")
        print("2. Set up your configuration properly")
        print("3. Have an active internet connection")