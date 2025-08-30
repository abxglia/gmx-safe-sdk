// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

/**
 * @title EIP7702DelegationManager
 * @dev Implements EIP-7702 delegation functionality with time-based asset delegation
 * Users can delegate their assets for specific time periods with automatic expiration
 */
contract EIP7702DelegationManager is Ownable, ReentrancyGuard {
    using SafeERC20 for IERC20;

    struct Delegation {
        address delegator;      // Original asset owner
        address delegate;       // Address receiving delegation
        address asset;          // Asset contract address (address(0) for ETH)
        uint256 amount;         // Amount delegated
        uint256 startTime;      // When delegation starts
        uint256 endTime;        // When delegation expires
        bool isActive;          // Whether delegation is active
        bool isRevoked;         // Whether delegation was manually revoked
    }

    struct DelegationAuthority {
        address authorizedCode;  // EIP-7702 authorized code address
        uint256 nonce;          // Nonce for replay protection
        bool isActive;          // Whether authority is active
    }

    // Mapping from delegation ID to delegation details
    mapping(uint256 => Delegation) public delegations;
    
    // Mapping from user address to their delegation authority
    mapping(address => DelegationAuthority) public delegationAuthorities;
    
    // Mapping from delegator to list of their delegation IDs
    mapping(address => uint256[]) public userDelegations;
    
    // Mapping from delegate to list of delegation IDs they received
    mapping(address => uint256[]) public receivedDelegations;

    uint256 public nextDelegationId = 1;
    uint256 public maxDelegationDuration = 365 days; // 1 year max
    uint256 public minDelegationDuration = 1 hours;  // 1 hour min

    // Events
    event DelegationCreated(
        uint256 indexed delegationId,
        address indexed delegator,
        address indexed delegate,
        address asset,
        uint256 amount,
        uint256 startTime,
        uint256 endTime
    );

    event DelegationRevoked(
        uint256 indexed delegationId,
        address indexed delegator,
        address indexed delegate
    );

    event DelegationExpired(
        uint256 indexed delegationId,
        address indexed delegator,
        address indexed delegate
    );

    event DelegatedETHWithdrawn(
        uint256 indexed delegationId,
        address indexed delegator,
        address indexed delegate,
        uint256 amount
    );

    event DelegatedTokensTransferred(
        uint256 indexed delegationId,
        address indexed delegator,
        address indexed delegate,
        address to,
        uint256 amount
    );

    event AuthorityGranted(
        address indexed user,
        address indexed authorizedCode,
        uint256 nonce
    );

    event AuthorityRevoked(
        address indexed user,
        address indexed authorizedCode
    );

    constructor() Ownable(msg.sender) {}

    /**
     * @dev Grant delegation authority using EIP-7702
     * @param authorizedCode The code address to authorize for delegations
     */
    function grantDelegationAuthority(address authorizedCode) external {
        require(authorizedCode != address(0), "Invalid authorized code");
        
        delegationAuthorities[msg.sender] = DelegationAuthority({
            authorizedCode: authorizedCode,
            nonce: delegationAuthorities[msg.sender].nonce + 1,
            isActive: true
        });

        emit AuthorityGranted(msg.sender, authorizedCode, delegationAuthorities[msg.sender].nonce);
    }

    /**
     * @dev Revoke delegation authority
     */
    function revokeDelegationAuthority() external {
        require(delegationAuthorities[msg.sender].isActive, "No active authority");
        
        address authorizedCode = delegationAuthorities[msg.sender].authorizedCode;
        delegationAuthorities[msg.sender].isActive = false;

        emit AuthorityRevoked(msg.sender, authorizedCode);
    }

    /**
     * @dev Create a new time-based delegation
     * @param delegate Address to delegate assets to
     * @param asset Asset contract address (address(0) for ETH)
     * @param amount Amount to delegate
     * @param duration Duration of delegation in seconds
     */
    function createDelegation(
        address delegate,
        address asset,
        uint256 amount,
        uint256 duration
    ) external payable nonReentrant {
        require(delegate != address(0), "Invalid delegate");
        require(delegate != msg.sender, "Cannot delegate to self");
        require(amount > 0, "Amount must be greater than 0");
        require(duration >= minDelegationDuration, "Duration too short");
        require(duration <= maxDelegationDuration, "Duration too long");

        uint256 startTime = block.timestamp;
        uint256 endTime = startTime + duration;

        // Handle ETH delegation
        if (asset == address(0)) {
            require(msg.value == amount, "ETH amount mismatch");
        } else {
            // Handle ERC20 delegation
            require(msg.value == 0, "No ETH should be sent for ERC20");
            IERC20(asset).safeTransferFrom(msg.sender, address(this), amount);
        }

        uint256 delegationId = nextDelegationId++;

        delegations[delegationId] = Delegation({
            delegator: msg.sender,
            delegate: delegate,
            asset: asset,
            amount: amount,
            startTime: startTime,
            endTime: endTime,
            isActive: true,
            isRevoked: false
        });

        userDelegations[msg.sender].push(delegationId);
        receivedDelegations[delegate].push(delegationId);

        emit DelegationCreated(
            delegationId,
            msg.sender,
            delegate,
            asset,
            amount,
            startTime,
            endTime
        );
    }

    /**
     * @dev Manually revoke an active delegation before expiration
     * @param delegationId ID of the delegation to revoke
     */
    function revokeDelegation(uint256 delegationId) external nonReentrant {
        Delegation storage delegation = delegations[delegationId];
        
        require(delegation.delegator == msg.sender, "Not the delegator");
        require(delegation.isActive, "Delegation not active");
        require(!delegation.isRevoked, "Already revoked");
        require(block.timestamp < delegation.endTime, "Already expired");

        delegation.isActive = false;
        delegation.isRevoked = true;

        // Return assets to delegator
        _returnAssets(delegation);

        emit DelegationRevoked(delegationId, delegation.delegator, delegation.delegate);
    }

    /**
     * @dev Process expired delegations and return assets
     * @param delegationId ID of the delegation to process
     */
    function processExpiredDelegation(uint256 delegationId) external nonReentrant {
        Delegation storage delegation = delegations[delegationId];
        
        require(delegation.isActive, "Delegation not active");
        require(block.timestamp >= delegation.endTime, "Not yet expired");

        delegation.isActive = false;

        // Return assets to delegator
        _returnAssets(delegation);

        emit DelegationExpired(delegationId, delegation.delegator, delegation.delegate);
    }

    /**
     * @dev Allow delegate to withdraw delegated ETH during active delegation
     * @param delegationId ID of the delegation to withdraw from
     * @param amount Amount of ETH to withdraw
     */
    function withdrawDelegatedETH(uint256 delegationId, uint256 amount) external nonReentrant {
        Delegation storage delegation = delegations[delegationId];
        
        require(delegation.delegate == msg.sender, "Not the delegate");
        require(delegation.isActive, "Delegation not active");
        require(!delegation.isRevoked, "Delegation revoked");
        require(block.timestamp < delegation.endTime, "Delegation expired");
        require(delegation.asset == address(0), "Not ETH delegation");
        require(amount > 0, "Amount must be greater than 0");
        require(amount <= delegation.amount, "Insufficient delegated amount");

        // Reduce the delegated amount
        delegation.amount -= amount;
        
        // If all amount is withdrawn, mark as inactive
        if (delegation.amount == 0) {
            delegation.isActive = false;
        }

        // Transfer ETH to delegate
        (bool success, ) = msg.sender.call{value: amount}("");
        require(success, "ETH transfer failed");

        emit DelegatedETHWithdrawn(delegationId, delegation.delegator, msg.sender, amount);
    }

    /**
     * @dev Allow delegate to transfer delegated ERC20 tokens
     * @param delegationId ID of the delegation
     * @param to Address to transfer tokens to
     * @param amount Amount of tokens to transfer
     */
    function transferDelegatedTokens(uint256 delegationId, address to, uint256 amount) external nonReentrant {
        Delegation storage delegation = delegations[delegationId];
        
        require(delegation.delegate == msg.sender, "Not the delegate");
        require(delegation.isActive, "Delegation not active");
        require(!delegation.isRevoked, "Delegation revoked");
        require(block.timestamp < delegation.endTime, "Delegation expired");
        require(delegation.asset != address(0), "Not token delegation");
        require(to != address(0), "Invalid recipient");
        require(amount > 0, "Amount must be greater than 0");
        require(amount <= delegation.amount, "Insufficient delegated amount");

        // Reduce the delegated amount
        delegation.amount -= amount;
        
        // If all amount is transferred, mark as inactive
        if (delegation.amount == 0) {
            delegation.isActive = false;
        }

        // Transfer tokens to specified address
        IERC20(delegation.asset).safeTransfer(to, amount);

        emit DelegatedTokensTransferred(delegationId, delegation.delegator, msg.sender, to, amount);
    }

    /**
     * @dev Get available amount for delegate to use
     * @param delegationId ID of the delegation
     * @return availableAmount Amount available for delegate to use
     */
    function getAvailableDelegatedAmount(uint256 delegationId) external view returns (uint256) {
        Delegation memory delegation = delegations[delegationId];
        
        if (!delegation.isActive || 
            delegation.isRevoked || 
            block.timestamp >= delegation.endTime) {
            return 0;
        }
        
        return delegation.amount;
    }

    /**
     * @dev Internal function to return assets to delegator
     * @param delegation The delegation struct containing asset details
     */
    function _returnAssets(Delegation memory delegation) internal {
        if (delegation.asset == address(0)) {
            // Return ETH
            (bool success, ) = delegation.delegator.call{value: delegation.amount}("");
            require(success, "ETH transfer failed");
        } else {
            // Return ERC20 tokens
            IERC20(delegation.asset).safeTransfer(delegation.delegator, delegation.amount);
        }
    }

    /**
     * @dev Check if a delegation is currently active
     * @param delegationId ID of the delegation to check
     * @return isActive Whether the delegation is active
     * @return timeLeft Seconds remaining until expiration (0 if expired)
     */
    function getDelegationStatus(uint256 delegationId) 
        external 
        view 
        returns (bool isActive, uint256 timeLeft) 
    {
        Delegation memory delegation = delegations[delegationId];
        
        if (!delegation.isActive || delegation.isRevoked) {
            return (false, 0);
        }

        if (block.timestamp >= delegation.endTime) {
            return (false, 0);
        }

        return (true, delegation.endTime - block.timestamp);
    }

    /**
     * @dev Get user's delegation IDs
     * @param user Address of the user
     * @return delegationIds Array of delegation IDs created by the user
     */
    function getUserDelegations(address user) external view returns (uint256[] memory) {
        return userDelegations[user];
    }

    /**
     * @dev Get delegation IDs received by a delegate
     * @param delegate Address of the delegate
     * @return delegationIds Array of delegation IDs received by the delegate
     */
    function getReceivedDelegations(address delegate) external view returns (uint256[] memory) {
        return receivedDelegations[delegate];
    }

    /**
     * @dev Get delegation details
     * @param delegationId ID of the delegation
     * @return delegation The delegation struct
     */
    function getDelegation(uint256 delegationId) external view returns (Delegation memory) {
        return delegations[delegationId];
    }

    /**
     * @dev Update delegation duration limits (only owner)
     * @param newMinDuration New minimum delegation duration
     * @param newMaxDuration New maximum delegation duration
     */
    function updateDurationLimits(uint256 newMinDuration, uint256 newMaxDuration) external onlyOwner {
        require(newMinDuration > 0, "Min duration must be positive");
        require(newMaxDuration > newMinDuration, "Max must be greater than min");
        
        minDelegationDuration = newMinDuration;
        maxDelegationDuration = newMaxDuration;
    }

    /**
     * @dev Emergency function to process multiple expired delegations
     * @param delegationIds Array of delegation IDs to process
     */
    function batchProcessExpired(uint256[] calldata delegationIds) external {
        for (uint256 i = 0; i < delegationIds.length; i++) {
            Delegation storage delegation = delegations[delegationIds[i]];
            
            if (delegation.isActive && 
                block.timestamp >= delegation.endTime && 
                !delegation.isRevoked) {
                
                delegation.isActive = false;
                _returnAssets(delegation);
                
                emit DelegationExpired(
                    delegationIds[i], 
                    delegation.delegator, 
                    delegation.delegate
                );
            }
        }
    }

    // Allow contract to receive ETH
    receive() external payable {}
}