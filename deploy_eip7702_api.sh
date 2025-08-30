#!/bin/bash

# EIP7702 GMX API Deployment Script
# This script sets up the environment and dependencies for the EIP7702 API

set -e  # Exit on any error

echo "🚀 Starting EIP7702 GMX API Deployment"
echo "======================================"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print colored output
print_status() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

print_success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

print_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Check if Python is installed
print_status "Checking Python installation..."
if command -v python3 &> /dev/null; then
    PYTHON_CMD="python3"
    print_success "Python 3 found: $(python3 --version)"
elif command -v python &> /dev/null; then
    PYTHON_CMD="python"
    print_success "Python found: $(python --version)"
else
    print_error "Python is not installed. Please install Python 3.8+ first."
    exit 1
fi

# Check Python version
PYTHON_VERSION=$($PYTHON_CMD -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)

if [ "$PYTHON_MAJOR" -lt 3 ] || ([ "$PYTHON_MAJOR" -eq 3 ] && [ "$PYTHON_MINOR" -lt 8 ]); then
    print_error "Python 3.8+ is required. Current version: $PYTHON_VERSION"
    exit 1
fi

print_success "Python version $PYTHON_VERSION is compatible"

# Check if pip is installed
print_status "Checking pip installation..."
if ! command -v pip3 &> /dev/null && ! command -v pip &> /dev/null; then
    print_error "pip is not installed. Please install pip first."
    exit 1
fi

# Create virtual environment if it doesn't exist
if [ ! -d "venv" ]; then
    print_status "Creating virtual environment..."
    $PYTHON_CMD -m venv venv
    print_success "Virtual environment created"
else
    print_status "Virtual environment already exists"
fi

# Activate virtual environment
print_status "Activating virtual environment..."
source venv/bin/activate
print_success "Virtual environment activated"

# Upgrade pip
print_status "Upgrading pip..."
pip install --upgrade pip
print_success "pip upgraded"

# Install dependencies
print_status "Installing dependencies..."
if [ -f "requirements_database.txt" ]; then
    pip install -r requirements_database.txt
    print_success "Dependencies installed from requirements_database.txt"
else
    print_warning "requirements_database.txt not found, installing basic requirements..."
    pip install flask flask-cors python-dotenv web3 requests
    print_success "Basic dependencies installed"
fi

# Create logs directory
if [ ! -d "logs" ]; then
    print_status "Creating logs directory..."
    mkdir -p logs
    print_success "Logs directory created"
fi

# Check if .env file exists
if [ ! -f ".env" ]; then
    print_warning ".env file not found. Creating template..."
    cat > .env << EOF
# EIP7702 GMX API Environment Variables
# Required variables - fill these in with your actual values

# Your address that has received delegation (the delegate)
DELEGATE_ADDRESS=0x0000000000000000000000000000000000000000

# Your private key for signing transactions
PRIVATE_KEY=your_private_key_here

# Address of the EIP7702 Delegation Manager contract
EIP7702_DELEGATION_MANAGER_ADDRESS=0x0000000000000000000000000000000000000000

# RPC endpoint for Arbitrum
RPC_URL=https://arb1.arbitrum.io/rpc

# MongoDB connection string (optional)
MONGODB_CONNECTION_STRING=mongodb://localhost:27017/

# Safe transaction service API URL (optional)
SAFE_API_URL=https://safe-transaction.arbitrum.safe.global

# Safe transaction service API key (optional)
SAFE_TRANSACTION_SERVICE_API_KEY=your_safe_api_key_here

# API server port (default: 5002)
GMX_EIP7702_API_PORT=5002
EOF
    print_success ".env template created"
    print_warning "Please edit .env file with your actual values before running the API"
else
    print_success ".env file already exists"
fi

# Check required environment variables
print_status "Checking required environment variables..."
source .env

MISSING_VARS=()

if [ "$DELEGATE_ADDRESS" = "0x0000000000000000000000000000000000000000" ]; then
    MISSING_VARS+=("DELEGATE_ADDRESS")
fi

if [ "$PRIVATE_KEY" = "your_private_key_here" ]; then
    MISSING_VARS+=("PRIVATE_KEY")
fi

if [ "$EIP7702_DELEGATION_MANAGER_ADDRESS" = "0x0000000000000000000000000000000000000000" ]; then
    MISSING_VARS+=("EIP7702_DELEGATION_MANAGER_ADDRESS")
fi

if [ ${#MISSING_VARS[@]} -gt 0 ]; then
    print_warning "The following required environment variables need to be set:"
    for var in "${MISSING_VARS[@]}"; do
        echo "  - $var"
    done
    echo ""
    print_warning "Please edit the .env file with your actual values"
else
    print_success "All required environment variables are set"
fi

# Create startup script
print_status "Creating startup script..."
cat > start_eip7702_api.sh << 'EOF'
#!/bin/bash

# EIP7702 GMX API Startup Script

echo "🚀 Starting EIP7702 GMX API..."

# Activate virtual environment
source venv/bin/activate

# Check if .env file exists
if [ ! -f ".env" ]; then
    echo "❌ .env file not found. Please create it first."
    exit 1
fi

# Load environment variables
export $(cat .env | grep -v '^#' | xargs)

# Check required variables
if [ "$DELEGATE_ADDRESS" = "0x0000000000000000000000000000000000000000" ]; then
    echo "❌ DELEGATE_ADDRESS not set in .env file"
    exit 1
fi

if [ "$PRIVATE_KEY" = "your_private_key_here" ]; then
    echo "❌ PRIVATE_KEY not set in .env file"
    exit 1
fi

if [ "$EIP7702_DELEGATION_MANAGER_ADDRESS" = "0x0000000000000000000000000000000000000000" ]; then
    echo "❌ EIP7702_DELEGATION_MANAGER_ADDRESS not set in .env file"
    exit 1
fi

echo "✅ Environment variables loaded"
echo "🔍 Delegate Address: $DELEGATE_ADDRESS"
echo "🔍 Delegation Manager: $EIP7702_DELEGATION_MANAGER_ADDRESS"
echo "🌐 RPC URL: $RPC_URL"
echo "🚀 Starting API on port ${GMX_EIP7702_API_PORT:-5002}..."

# Start the API
python gmx_eip7702_api.py
EOF

chmod +x start_eip7702_api.sh
print_success "Startup script created: start_eip7702_api.sh"

# Create test script
print_status "Creating test script..."
cat > test_eip7702_api.sh << 'EOF'
#!/bin/bash

# EIP7702 GMX API Test Script

echo "🧪 Testing EIP7702 GMX API..."

# Activate virtual environment
source venv/bin/activate

# Check if API is running
if ! curl -s http://localhost:5002/health > /dev/null; then
    echo "❌ API is not running. Please start it first with: ./start_eip7702_api.sh"
    exit 1
fi

echo "✅ API is running, starting tests..."

# Run the test suite
python test_eip7702_api.py

echo "✅ Tests completed"
EOF

chmod +x test_eip7702_api.sh
print_success "Test script created: test_eip7702_api.sh"

# Print deployment summary
echo ""
echo "======================================"
echo "🎉 EIP7702 GMX API Deployment Complete!"
echo "======================================"
echo ""
echo "📁 Files created:"
echo "  - .env (environment variables template)"
echo "  - start_eip7702_api.sh (startup script)"
echo "  - test_eip7702_api.sh (test script)"
echo "  - logs/ (logs directory)"
echo ""
echo "🚀 Next steps:"
echo "  1. Edit .env file with your actual values"
echo "  2. Start the API: ./start_eip7702_api.sh"
echo "  3. Test the API: ./test_eip7702_api.sh"
echo ""
echo "📚 Documentation:"
echo "  - README: EIP7702_README.md"
echo "  - Configuration: eip7702_config.yaml"
echo "  - Main API: gmx_eip7702_api.py"
echo ""
echo "⚠️  Important:"
echo "  - Never commit your .env file to version control"
echo "  - Keep your private key secure"
echo "  - Verify delegation contract addresses"
echo ""

print_success "Deployment completed successfully!"
