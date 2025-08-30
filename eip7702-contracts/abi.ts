export const EIP7702DelegationManagerABI = [
    {
        "type": "constructor",
        "inputs": [],
        "stateMutability": "nonpayable"
    },
    {
        "type": "function",
        "name": "createDelegation",
        "inputs": [
            { "name": "delegate", "type": "address" },
            { "name": "asset", "type": "address" },
            { "name": "amount", "type": "uint256" },
            { "name": "duration", "type": "uint256" }
        ],
        "outputs": [],
        "stateMutability": "payable"
    },
    {
        "type": "function",
        "name": "revokeDelegation",
        "inputs": [
            { "name": "delegationId", "type": "uint256" }
        ],
        "outputs": [],
        "stateMutability": "nonpayable"
    },
    {
        "type": "function",
        "name": "processExpiredDelegation",
        "inputs": [
            { "name": "delegationId", "type": "uint256" }
        ],
        "outputs": [],
        "stateMutability": "nonpayable"
    },
    {
        "type": "function",
        "name": "withdrawDelegatedETH",
        "inputs": [
            { "name": "delegationId", "type": "uint256" },
            { "name": "amount", "type": "uint256" }
        ],
        "outputs": [],
        "stateMutability": "nonpayable"
    },
    {
        "type": "function",
        "name": "transferDelegatedTokens",
        "inputs": [
            { "name": "delegationId", "type": "uint256" },
            { "name": "to", "type": "address" },
            { "name": "amount", "type": "uint256" }
        ],
        "outputs": [],
        "stateMutability": "nonpayable"
    },
    {
        "type": "function",
        "name": "getAvailableDelegatedAmount",
        "inputs": [
            { "name": "delegationId", "type": "uint256" }
        ],
        "outputs": [
            { "name": "availableAmount", "type": "uint256" }
        ],
        "stateMutability": "view"
    },
    {
        "type": "function",
        "name": "getDelegation",
        "inputs": [
            { "name": "delegationId", "type": "uint256" }
        ],
        "outputs": [
            {
                "type": "tuple",
                "components": [
                    { "name": "delegator", "type": "address" },
                    { "name": "delegate", "type": "address" },
                    { "name": "asset", "type": "address" },
                    { "name": "amount", "type": "uint256" },
                    { "name": "startTime", "type": "uint256" },
                    { "name": "endTime", "type": "uint256" },
                    { "name": "isActive", "type": "bool" },
                    { "name": "isRevoked", "type": "bool" }
                ]
            }
        ],
        "stateMutability": "view"
    },
    {
        "type": "function",
        "name": "getDelegationStatus",
        "inputs": [
            { "name": "delegationId", "type": "uint256" }
        ],
        "outputs": [
            { "name": "isActive", "type": "bool" },
            { "name": "timeLeft", "type": "uint256" }
        ],
        "stateMutability": "view"
    },
    {
        "type": "function",
        "name": "getUserDelegations",
        "inputs": [
            { "name": "user", "type": "address" }
        ],
        "outputs": [
            { "name": "", "type": "uint256[]" }
        ],
        "stateMutability": "view"
    },
    {
        "type": "function",
        "name": "getReceivedDelegations",
        "inputs": [
            { "name": "delegate", "type": "address" }
        ],
        "outputs": [
            { "name": "", "type": "uint256[]" }
        ],
        "stateMutability": "view"
    },
    {
        "type": "function",
        "name": "grantDelegationAuthority",
        "inputs": [
            { "name": "authorizedCode", "type": "address" }
        ],
        "outputs": [],
        "stateMutability": "nonpayable"
    },
    {
        "type": "function",
        "name": "revokeDelegationAuthority",
        "inputs": [],
        "outputs": [],
        "stateMutability": "nonpayable"
    },
    {
        "type": "event",
        "name": "DelegationCreated",
        "inputs": [
            { "name": "delegationId", "type": "uint256", "indexed": true },
            { "name": "delegator", "type": "address", "indexed": true },
            { "name": "delegate", "type": "address", "indexed": true },
            { "name": "asset", "type": "address", "indexed": false },
            { "name": "amount", "type": "uint256", "indexed": false },
            { "name": "startTime", "type": "uint256", "indexed": false },
            { "name": "endTime", "type": "uint256", "indexed": false }
        ]
    },
    {
        "type": "event",
        "name": "DelegationRevoked",
        "inputs": [
            { "name": "delegationId", "type": "uint256", "indexed": true },
            { "name": "delegator", "type": "address", "indexed": true },
            { "name": "delegate", "type": "address", "indexed": true }
        ]
    },
    {
        "type": "event",
        "name": "DelegationExpired",
        "inputs": [
            { "name": "delegationId", "type": "uint256", "indexed": true },
            { "name": "delegator", "type": "address", "indexed": true },
            { "name": "delegate", "type": "address", "indexed": true }
        ]
    },
    {
        "type": "event",
        "name": "DelegatedETHWithdrawn",
        "inputs": [
            { "name": "delegationId", "type": "uint256", "indexed": true },
            { "name": "delegator", "type": "address", "indexed": true },
            { "name": "delegate", "type": "address", "indexed": true },
            { "name": "amount", "type": "uint256", "indexed": false }
        ]
    },
    {
        "type": "event",
        "name": "DelegatedTokensTransferred",
        "inputs": [
            { "name": "delegationId", "type": "uint256", "indexed": true },
            { "name": "delegator", "type": "address", "indexed": true },
            { "name": "delegate", "type": "address", "indexed": true },
            { "name": "to", "type": "address", "indexed": false },
            { "name": "amount", "type": "uint256", "indexed": false }
        ]
    }
] as const;


export const MockERC20ABI = [
    {
        "type": "function",
        "name": "balanceOf",
        "inputs": [{ "name": "account", "type": "address" }],
        "outputs": [{ "name": "", "type": "uint256" }],
        "stateMutability": "view"
    },
    {
        "type": "function",
        "name": "approve",
        "inputs": [
            { "name": "spender", "type": "address" },
            { "name": "amount", "type": "uint256" }
        ],
        "outputs": [{ "name": "", "type": "bool" }],
        "stateMutability": "nonpayable"
    },
    {
        "type": "function",
        "name": "transfer",
        "inputs": [
            { "name": "to", "type": "address" },
            { "name": "amount", "type": "uint256" }
        ],
        "outputs": [{ "name": "", "type": "bool" }],
        "stateMutability": "nonpayable"
    },
    {
        "type": "function",
        "name": "allowance",
        "inputs": [
            { "name": "owner", "type": "address" },
            { "name": "spender", "type": "address" }
        ],
        "outputs": [{ "name": "", "type": "uint256" }],
        "stateMutability": "view"
    },
    {
        "type": "function",
        "name": "decimals",
        "inputs": [],
        "outputs": [{ "name": "", "type": "uint8" }],
        "stateMutability": "view"
    },
    {
        "type": "function",
        "name": "symbol",
        "inputs": [],
        "outputs": [{ "name": "", "type": "string" }],
        "stateMutability": "view"
    },
    {
        "type": "function",
        "name": "name",
        "inputs": [],
        "outputs": [{ "name": "", "type": "string" }],
        "stateMutability": "view"
    },
    {
        "type": "function",
        "name": "faucet",
        "inputs": [{ "name": "amount", "type": "uint256" }],
        "outputs": [],
        "stateMutability": "nonpayable"
    }
] as const;

// USDC uses the same ERC20 interface as MockERC20
export const USDCABI = MockERC20ABI;