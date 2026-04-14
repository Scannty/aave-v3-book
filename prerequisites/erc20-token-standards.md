# ERC-20 Token Standards and Rebasing Tokens

Every asset in Aave V3 is an ERC-20 token. When you supply USDC, you receive aUSDC (an ERC-20). When you borrow DAI, the protocol mints a variable debt token (an ERC-20) to your address. Understanding the ERC-20 standard - and how some tokens bend its rules - is essential for following Aave's token mechanics.

-

## The Standard ERC-20 Interface

ERC-20 (Ethereum Request for Comments 20) defines a common interface for fungible tokens. Any contract that implements this interface can be treated as a "token" by wallets, DEXes, and other protocols.

```solidity
interface IERC20 {
    // Returns the total supply of tokens in existence
    function totalSupply() external view returns (uint256);

    // Returns the token balance of a specific account
    function balanceOf(address account) external view returns (uint256);

    // Transfers tokens from the caller to a recipient
    function transfer(address to, uint256 amount) external returns (bool);

    // Returns how much `spender` is allowed to spend on behalf of `owner`
    function allowance(address owner, address spender) external view returns (uint256);

    // Grants `spender` permission to spend up to `amount` of the caller's tokens
    function approve(address spender, uint256 amount) external returns (bool);

    // Transfers tokens from one address to another (requires prior approval)
    function transferFrom(address from, address to, uint256 amount) external returns (bool);

    // Events
    event Transfer(address indexed from, address indexed to, uint256 value);
    event Approval(address indexed owner, address indexed spender, uint256 value);
}
```

### The Approval Pattern

A key design pattern in ERC-20 is the **approve + transferFrom** flow:

1. User calls `token.approve(spender, amount)` to grant permission
2. The spender contract calls `token.transferFrom(user, recipient, amount)` to move the tokens

This two-step process is how users interact with DeFi protocols. When you supply USDC to Aave, you first approve the Pool contract to spend your USDC, then the Pool calls `transferFrom` to pull the tokens.

```solidity
// Step 1: User approves Aave Pool
usdc.approve(address(pool), 1000e6);

// Step 2: User calls supply, which internally does transferFrom
pool.supply(address(usdc), 1000e6, onBehalfOf, referralCode);
```

-

## Standard Token Implementation

A minimal ERC-20 stores balances in a mapping:

```solidity
contract SimpleToken is IERC20 {
    mapping(address => uint256) private _balances;
    mapping(address => mapping(address => uint256)) private _allowances;
    uint256 private _totalSupply;

    function balanceOf(address account) external view returns (uint256) {
        return _balances[account];
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        _balances[msg.sender] -= amount;
        _balances[to] += amount;
        emit Transfer(msg.sender, to, amount);
        return true;
    }

    // ... approve, transferFrom, etc.
}
```

The critical property: **balances only change when `transfer` or `transferFrom` is called**. If no one moves tokens, `balanceOf(account)` returns the same value forever.

This seems obvious, but it is exactly the property that rebasing tokens violate.

-

## What Are Rebasing Tokens?

A **rebasing token** is an ERC-20 where `balanceOf()` can return different values over time **even if no transfers occur**.

How is this possible? Instead of storing the actual balance, the contract stores a different internal value and computes the balance dynamically:

```solidity
contract RebasingToken is IERC20 {
    mapping(address => uint256) private _shares;
    uint256 private _totalShares;
    uint256 private _totalUnderlying;

    function balanceOf(address account) external view returns (uint256) {
        return (_shares[account] * _totalUnderlying) / _totalShares;
    }
}
```

When `_totalUnderlying` increases (e.g., because interest accrued), everyone's `balanceOf()` increases proportionally, without any `Transfer` events or explicit balance updates.

### Real-World Examples

- **stETH (Lido)**: Balances increase daily as Ethereum staking rewards accrue
- **aTokens (Aave)**: Balances increase over time as borrow interest accrues
- **AMPL (Ampleforth)**: Balances increase or decrease based on the token's target price

-

## Why Rebasing Matters for Aave

Aave V3's **aTokens** are rebasing tokens. When you deposit 1,000 USDC into Aave, you receive 1,000 aUSDC. Over time, as borrowers pay interest, your aUSDC balance grows - to 1,001, then 1,002, and so on - without you doing anything.

This is the core user experience of Aave: you deposit tokens and watch your balance increase.

### How aTokens Implement Rebasing

Internally, aTokens store a **scaled balance** rather than the actual balance:

```solidity
// Simplified aToken balanceOf
function balanceOf(address user) public view returns (uint256) {
    return scaledBalance[user].rayMul(pool.getReserveNormalizedIncome(asset));
}
```

- `scaledBalance` is the user's balance at the time of deposit, divided by the liquidity index
- `getReserveNormalizedIncome` returns the current liquidity index, which grows over time as interest accrues
- Multiplying the two gives the current balance including accumulated interest

The liquidity index is a global value that increases monotonically. All aToken holders benefit from this increase proportionally. No per-user updates are needed.

This design is covered in detail in Chapter 3 (Indexes and Scaled Balances) and Chapter 4 (aTokens).

-

## Challenges with Rebasing Tokens

Rebasing tokens introduce complications that standard ERC-20s do not have:

### Transfer Amount Mismatch

When transferring rebasing tokens, the amount received may differ from the amount sent due to rounding:

```solidity
// User sends 100 aUSDC
aToken.transfer(recipient, 100);

// Due to scaling/unscaling, recipient might receive 99.999999 or 100.000001
```

Aave handles this with careful rounding logic, but integrators must be aware of it.

### Snapshot Inconsistency

If a contract caches `balanceOf()` at time T1 and reads it again at T2, the values may differ. Contracts that store token balances as state variables (rather than reading them fresh) will have stale values for rebasing tokens.

### Event Gaps

Since balances change without transfers, `Transfer` events do not capture all balance changes. Off-chain indexers that track balances by summing transfer events will compute incorrect values for rebasing tokens.

-

## Non-Transferable Tokens: Debt Tokens

Aave V3 has another category of non-standard ERC-20s: **debt tokens**. These represent how much a user owes.

- **Variable Debt Tokens**: Track variable-rate borrows. Like aTokens, they rebase (balances grow as interest accrues). But unlike aTokens, they are **non-transferable**.
- **Stable Debt Tokens**: Track stable-rate borrows. Also non-transferable.

Why non-transferable? If debt tokens could be transferred, a borrower could send their debt to another address, effectively escaping their obligation. The protocol's accounting would break.

```solidity
// Debt tokens override transfer to always revert
function transfer(address, uint256) public virtual override returns (bool) {
    revert("DEBT_TOKEN_TRANSFER_NOT_ALLOWED");
}

function transferFrom(address, address, uint256) public virtual override returns (bool) {
    revert("DEBT_TOKEN_TRANSFER_NOT_ALLOWED");
}
```

Debt tokens still implement the ERC-20 interface so that `balanceOf()` works (wallets can display how much you owe), but the transfer functions revert unconditionally.

-

## ERC-20 Extensions You Will See in Aave

### EIP-2612: Permit

The standard approve-then-transferFrom pattern requires two transactions. EIP-2612 adds a `permit()` function that lets users sign an approval off-chain:

```solidity
function permit(
    address owner,
    address spender,
    uint256 value,
    uint256 deadline,
    uint8 v, bytes32 r, bytes32 s
) external;
```

The user signs a message authorizing the spender. Anyone can then submit that signature on-chain, combining approval and action into a single transaction. Aave V3's aTokens support `permit()`, enabling gas-efficient integrations.

### Supply and Borrow with Permit

Aave V3 exposes `supplyWithPermit()` and `repayWithPermit()` functions that combine the permit signature with the supply/repay action:

```solidity
pool.supplyWithPermit(
    asset,
    amount,
    onBehalfOf,
    referralCode,
    deadline,
    v, r, s
);
```

This saves the user one transaction compared to the traditional approve + supply flow.

-

## Token Decimals

ERC-20 tokens have a `decimals()` function that indicates how many decimal places the token uses:

| Token | Decimals | 1.0 token in raw units |
|-------|----------|----------------------|
| USDC | 6 | 1000000 |
| DAI | 18 | 1000000000000000000 |
| WBTC | 8 | 100000000 |
| ETH (WETH) | 18 | 1000000000000000000 |

All on-chain math operates on raw integers. There are no floating-point numbers in Solidity. When Aave V3 handles a deposit of "1000 USDC," the actual value in the contract is `1000 * 10^6 = 1,000,000,000`.

Mixing up decimals is a common source of bugs. When comparing values across different tokens (e.g., ETH collateral value vs. USDC debt), the protocol must normalize everything to a common precision. Aave V3 uses internal precision standards (ray = 10^27, wad = 10^18) for this purpose.

-

## Summary

| Concept | Key Point |
|---------|-----------|
| ERC-20 | Standard token interface: `balanceOf`, `transfer`, `approve`, `transferFrom` |
| Approve pattern | Two-step: approve then transferFrom. How users interact with Aave |
| Rebasing tokens | `balanceOf()` changes over time without transfers |
| aTokens | Rebasing ERC-20s that represent supplied assets + accrued interest |
| Debt tokens | Rebasing, non-transferable ERC-20s that represent borrow obligations |
| Permit (EIP-2612) | Off-chain approval signatures, saves a transaction |
| Decimals | Tokens have different decimal precisions; must normalize for comparison |

Understanding these token mechanics is foundational for Chapters 3 (Indexes and Scaled Balances), 4 (aTokens), and 5 (Debt Tokens), where we examine exactly how Aave V3 implements its token system.
