// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/// @title SampleEscrow — a deliberately simple escrow used as the inspection
/// target for EscrowScout's demo on Base Sepolia (testnet only).
/// Design choices EscrowScout is expected to detect:
///  - release needs the buyer OR the arbiter (not the seller alone)
///  - the buyer can refund after the deadline if nothing was released
///  - no admin key, no upgradeability, no sweep function
contract SampleEscrow {
    address public buyer;
    address public seller;
    address public arbiter;
    uint256 public deadline;
    bool public released;
    bool public refunded;

    event Funded(address indexed from, uint256 amount);
    event Released(address indexed to, uint256 amount);
    event Refunded(address indexed to, uint256 amount);

    constructor(address _seller, address _arbiter, uint256 _durationSeconds) payable {
        buyer = msg.sender;
        seller = _seller;
        arbiter = _arbiter;
        deadline = block.timestamp + _durationSeconds;
        if (msg.value > 0) emit Funded(msg.sender, msg.value);
    }

    function fund() external payable {
        require(!released && !refunded, "escrow closed");
        emit Funded(msg.sender, msg.value);
    }

    /// @notice Release to the seller. Only the buyer or the arbiter may call.
    function release() external {
        require(msg.sender == buyer || msg.sender == arbiter, "not authorised");
        require(!released && !refunded, "escrow closed");
        released = true;
        uint256 amount = address(this).balance;
        (bool ok, ) = seller.call{value: amount}("");
        require(ok, "transfer failed");
        emit Released(seller, amount);
    }

    /// @notice Refund the buyer after the deadline if funds were not released.
    function refundAfterDeadline() external {
        require(msg.sender == buyer, "buyer only");
        require(block.timestamp >= deadline, "deadline not reached");
        require(!released && !refunded, "escrow closed");
        refunded = true;
        uint256 amount = address(this).balance;
        (bool ok, ) = buyer.call{value: amount}("");
        require(ok, "transfer failed");
        emit Refunded(buyer, amount);
    }
}
