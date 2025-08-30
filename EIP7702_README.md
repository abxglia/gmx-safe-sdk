# EIP7702 Delegation-based GMX Safe API

This API integrates EIP7702 delegation contracts with GMX V2 trading functionality, allowing you to trade using delegated funds that have been temporarily entrusted to your address.

## 🚀 Features

- **EIP7702 Delegation Integration**: Automatically checks and uses delegated funds for trading
- **GMX V2 Trading**: Full support for long/short positions with leverage
- **Safe Transaction Support**: Optional integration with Safe transaction service
- **Database Tracking**: MongoDB integration for position and transaction history
- **Real-time Delegation Status**: Monitor delegated funds and time remaining
- **Signal Processing**: Automated trading based on external signals
- **Clean Code Architecture**: Follows 9 Clean Code Principles for maintainability

## 📋 Prerequisites

- Python 3.8+
- MongoDB instance (optional but recommended)
- Access to Arbitrum RPC endpoint
- EIP7702 delegation already set up (you've been delegated funds)
- Private key for the delegated address

## 🛠️ Installation

1. **Clone the repository**:
```bash
git clone <repository-url>
cd gmx_python_sdk
```

2. **Install dependencies**:
```bash
pip install -r requirements_database.txt
```

3. **Set up environment variables**:
Create a `.env` file with the following variables:

```bash
# Required
DELEGATE_ADDRESS=0xYourDelegatedAddress
PRIVATE_KEY=your_private_key_here
EIP7702_DELEGATION_MANAGER_ADDRESS=0xDelegationManagerContractAddress
RPC_URL=https://arb1.arbitrum.io/rpc

# Optional
MONGODB_CONNECTION_STRING=mongodb://localhost:27017/
SAFE_API_URL=https://safe-transaction.arbitrum.safe.global
SAFE_TRANSACTION_SERVICE_API_KEY=your_safe_api_key
GMX_EIP7702_API_PORT=5002
```

## 🏗️ Architecture

### Core Components

1. **EIP7702DelegationManager**: Manages interaction with EIP7702 delegation contracts
2. **EIP7702GMXAPI**: Main API class integrating delegation with GMX trading
3. **Database Integration**: MongoDB tracking for positions and transactions
4. **Safe Integration**: Optional Safe transaction service support

### Key Classes

```python
class EIP7702DelegationManager:
    """Manages EIP7702 delegation interactions and fund tracking"""
    
    def get_active_delegations(self, delegate_address: str) -> List[Dict[str, Any]]
    def get_total_delegated_funds(self, delegate_address: str) -> Dict[str, int]
    def can_use_delegated_funds(self, delegate_address: str, required_amount: int, asset: str) -> bool

class EIP7702GMXAPI:
    """Enhanced GMX API with EIP7702 delegation support"""
    
    def execute_buy_order_with_delegation(self, token: str, size_usd: float, leverage: int = 2, **kwargs)
    def execute_sell_order_with_delegation(self, token: str, size_usd: float = None, **kwargs)
    def get_delegation_summary(self) -> Dict[str, Any]
    def process_signal_with_delegation(self, signal_data: Dict[str, Any]) -> Dict[str, Any]
```

## 🚀 Usage

### 1. Start the API Server

```bash
python gmx_eip7702_api.py
```

The server will start on port 5002 (or the port specified in `GMX_EIP7702_API_PORT`).

### 2. Initialize the API

```bash
curl -X POST http://localhost:5002/initialize
```

### 3. Check Delegation Status

```bash
curl http://localhost:5002/delegations/summary
```

Response example:
```json
{
  "status": "success",
  "delegate_address": "0xYourAddress",
  "total_delegations": 2,
  "total_funds": {
    "0xaf88d065e77c8cC2239327C5EDb3A432268e5831": 1000000
  },
  "active_delegations": [
    {
      "delegation_id": 1,
      "delegator": "0xDelegatorAddress",
      "delegate": "0xYourAddress",
      "asset": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
      "amount": 1000000,
      "time_left_hours": 23.5
    }
  ],
  "time_metrics": {
    "total_time_remaining_seconds": 84600,
    "average_time_remaining_seconds": 42300,
    "average_time_remaining_hours": 11.75
  }
}
```

### 4. Execute Buy Order

```bash
curl -X POST http://localhost:5002/buy \
  -H "Content-Type: application/json" \
  -d '{
    "token": "BTC",
    "size_usd": 2.02,
    "leverage": 1
  }'
```

### 5. Execute Sell Order

```bash
curl -X POST http://localhost:5002/sell \
  -H "Content-Type: application/json" \
  -d '{
    "token": "BTC",
    "size_usd": 1.0
  }'
```

### 6. Process Trading Signal

```bash
curl -X POST http://localhost:5002/signal/process \
  -H "Content-Type: application/json" \
  -d '{
    "Signal Message": "buy",
    "Token Mentioned": "BTC",
    "username": "trader1"
  }'
```

## 🔧 API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/health` | GET | Health check and status |
| `/initialize` | POST | Initialize the API |
| `/delegations/summary` | GET | Get delegation status and funds |
| `/buy` | POST | Execute buy order with delegated funds |
| `/sell` | POST | Execute sell order with delegated funds |
| `/signal/process` | POST | Process trading signal automatically |

## 📊 Database Schema

The API automatically tracks:

- **Positions**: Open and closed trading positions
- **Transactions**: All GMX and Safe transactions
- **Signals**: Trading signals and their processing status
- **Delegations**: Delegation history and status

## 🔒 Security Features

- **Private Key Protection**: Never expose private keys in code
- **Rate Limiting**: Configurable API rate limiting
- **CORS Protection**: Configurable cross-origin resource sharing
- **Input Validation**: Comprehensive input validation and sanitization

## 🧪 Testing

### Test Delegation Status
```bash
# Check if API is running
curl http://localhost:5002/health

# Get delegation summary
curl http://localhost:5002/delegations/summary
```

### Test Trading
```bash
# Test buy order
curl -X POST http://localhost:5002/buy \
  -H "Content-Type: application/json" \
  -d '{"token": "ETH", "size_usd": 1.0, "leverage": 1}'

# Test sell order
curl -X POST http://localhost:5002/sell \
  -H "Content-Type: application/json" \
  -d '{"token": "ETH", "size_usd": 0.5}'
```

## 🚨 Important Notes

1. **Delegation Expiry**: Always check delegation expiry times before trading
2. **Fund Availability**: Verify sufficient delegated funds before placing orders
3. **Private Key Security**: Keep your private key secure and never commit it to version control
4. **Network Fees**: Consider gas fees when calculating position sizes
5. **Slippage**: Default slippage is 0.5% - adjust based on market conditions

## 🔍 Troubleshooting

### Common Issues

1. **"Delegation manager not initialized"**
   - Check `EIP7702_DELEGATION_MANAGER_ADDRESS` environment variable
   - Verify the contract address is correct

2. **"Insufficient delegated funds"**
   - Check delegation status with `/delegations/summary`
   - Verify delegation hasn't expired
   - Check if funds were already used

3. **"API not initialized"**
   - Call `/initialize` endpoint first
   - Check environment variables are set correctly

4. **Database connection issues**
   - Verify MongoDB is running
   - Check connection string in environment variables
   - API will continue without database if connection fails

### Debug Mode

Enable debug mode by setting `debug: true` in the configuration or setting the environment variable:

```bash
export FLASK_DEBUG=1
```

## 📈 Monitoring

The API provides comprehensive logging and monitoring:

- **Health Checks**: Automatic health monitoring
- **Transaction Tracking**: Full transaction history
- **Position Monitoring**: Real-time position status
- **Delegation Status**: Fund availability and expiry tracking

## 🤝 Contributing

1. Follow the 9 Clean Code Principles
2. Add comprehensive error handling
3. Include proper logging
4. Write unit tests for new features
5. Update documentation

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🆘 Support

For issues and questions:

1. Check the troubleshooting section
2. Review the logs for error details
3. Verify environment variable configuration
4. Check delegation contract status on-chain

## 🔮 Future Enhancements

- **Multi-chain Support**: Extend to other networks
- **Advanced Order Types**: Stop-loss, take-profit orders
- **Portfolio Management**: Multi-token position management
- **Risk Management**: Automated position sizing and risk controls
- **WebSocket Support**: Real-time updates and notifications
