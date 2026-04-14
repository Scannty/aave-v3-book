# Chapter 4: aTokens - Your Receipt for Lending

When you deposit money into a savings account, the bank gives you a statement showing your balance. In Aave V3, you get something better: an **aToken** - a live, tradeable receipt that sits in your wallet and whose balance grows every second.

aTokens are the core of the depositor experience. They answer a simple question: "How do I prove I deposited assets, and how do I see my interest?"

-

## The Economic Idea: A Receipt That Earns Interest

When you supply 1,000 USDC to Aave, you receive 1,000 aUSDC. This aUSDC is a standard ERC-20 token that lives in your Ethereum wallet. But unlike a normal token, your aUSDC balance **increases over time** as borrowers pay interest into the pool.

You do not need to claim anything. You do not need to stake, lock, or interact with the protocol. Your balance simply goes up, block by block, second by second.

The key design choice: **1 aToken is always worth approximately 1 of the underlying asset.** If you hold 1,050 aUSDC, you can redeem it for 1,050 USDC. The quantity of tokens in your wallet changes to reflect interest - not the price per token.

This is what makes aTokens intuitive. You do not need to check an exchange rate or do mental math. Your wallet balance *is* your position value.

-

## Rebasing: How Your Balance Grows Without Transfers

Most ERC-20 tokens have a fixed balance that only changes when someone sends you tokens or you send them away. aTokens break this rule. They are **rebasing tokens**, meaning the reported balance changes continuously even though no one is sending you anything.

### A Concrete Example

Alice deposits 1,000 USDC on January 1st. The USDC supply APY is 3.65% (about 0.01% per day for easy math).

| Date       | Alice's aUSDC Balance | What Changed?                   |
|----|--------|------------|
| Jan 1      | 1,000.00             | Initial deposit                  |
| Jan 2      | 1,000.10             | One day of interest              |
| Jan 31     | 1,003.00             | 30 days of interest              |
| Jul 1      | 1,018.25             | ~6 months of interest            |

No one sent Alice any tokens. No transactions appeared in her wallet history. The `balanceOf()` function simply returns a larger number each time it is called, because it is computing the answer on the fly.

This is the rebase: the token's supply and individual balances shift continuously without any per-user on-chain state change.

### Why This Matters

- **Cold wallets earn interest.** You can put aTokens on a hardware wallet, disconnect it for a year, and your balance will be higher when you check again.
- **No gas to claim.** Unlike some yield protocols that require periodic "harvest" transactions, aToken interest accrues automatically.
- **Real-time balances.** Integrators, dashboards, and wallets always see the current value - there is no stale balance problem.

-

## How It Works Under the Hood: Scaled Balances and the Liquidity Index

The rebasing magic comes from a simple multiplication. Aave does not actually update every depositor's balance in storage each second - that would be impossibly expensive. Instead, it uses two concepts from Chapter 3:

1. **Scaled balance**: What the contract actually stores for each user. This is your deposit divided by the liquidity index at the time you deposited.
2. **Liquidity index**: A global number that starts at 1.0 and grows over time as borrowers pay interest.

Every time you (or anyone) calls `balanceOf()`, the contract computes:

$$actualBalance = scaledBalance \times currentLiquidityIndex$$

That is the entire trick. The scaled balance is fixed (it only changes on deposit/withdraw/transfer). The liquidity index grows continuously. Multiply them together, and you get a balance that increases over time.

### Walking Through the Math

Alice deposits 1,000 USDC when the liquidity index is 1.05:

$$scaledBalance = \frac{1{,}000}{1.05} = 952.38$$

The contract stores 952.38 as Alice's scaled balance. Now time passes and the index grows:

| Liquidity Index | Alice's balanceOf()            | Interest Earned |
|------|-----------|-------|
| 1.05           | 952.38 × 1.05 = 1,000.00     | 0.00            |
| 1.06           | 952.38 × 1.06 = 1,009.52     | 9.52            |
| 1.08           | 952.38 × 1.08 = 1,028.57     | 28.57           |
| 1.10           | 952.38 × 1.10 = 1,047.62     | 47.62           |

The only code that makes this work is a short override of the standard `balanceOf` function:

```solidity
function balanceOf(address user) public view override returns (uint256) {
    return super.balanceOf(user).rayMul(
        POOL.getReserveNormalizedIncome(_underlyingAsset)
    );
}
```

`super.balanceOf(user)` returns the stored scaled balance. `getReserveNormalizedIncome` returns the current liquidity index, projected forward to this exact second. Multiply them, and you have the real balance. This is a `view` function - reading it costs no gas.

`totalSupply()` works the same way: it multiplies the total scaled supply by the index.

### The Scaled Balance Functions

For protocols that need the raw stored value (not the rebased one), aTokens expose:

| Function                | What It Returns                        | Changes On...         |
|--------|--------------|--------|
| `balanceOf(user)`      | Actual balance including interest      | Every second          |
| `scaledBalanceOf(user)` | Raw stored balance (no index applied) | Deposit, withdraw, transfer only |
| `totalSupply()`        | Total actual supply with interest      | Every second          |
| `scaledTotalSupply()`  | Raw total supply (no index applied)    | Deposit, withdraw, transfer only |

If you are building a protocol that integrates aTokens, the scaled versions give you stable values for snapshots and accounting.

-

## The Rebasing Trade-off

The rebasing design makes aTokens intuitive for users - your balance *is* your value, no exchange rate math needed. But it creates a subtlety for smart contract integrations: `balanceOf()` returns a different value between two calls even without any transfer. Any protocol integrating aTokens must account for this. Caching aToken balances is a common integration mistake.

For this reason, Aave also exposes `scaledBalanceOf()` - the raw stored balance that does not change between transactions. Integrators who need a stable reference point can use the scaled balance and apply the index themselves when needed.

-

## Treasury Revenue: How the Protocol Takes Its Cut

Aave is a protocol, not a charity. A portion of all interest paid by borrowers goes to the Aave treasury, funding development, grants, and reserves. This revenue is collected through the aToken minting mechanism.

### The Reserve Factor

Each asset in Aave has a **reserve factor** - a governance-set percentage (typically 10-20%) that determines the protocol's share of borrower interest.

$$\text{Interest paid by borrowers in one day} = \$1{,}000{,}000 \times 5\% \times \frac{1}{365} = \$136.99$$

$$\text{Treasury's share (20\% reserve factor)} = \$136.99 \times 20\% = \$27.40$$

This \$27.40 is recorded as aTokens owed to the treasury. The treasury is economically equivalent to another depositor - its aToken position also earns interest over time.

### Batch Minting for Gas Efficiency

Rather than minting aTokens to the treasury on every single user interaction (which would waste gas), the protocol accumulates the owed amount in a counter called `accruedToTreasury`. The actual aToken mint happens periodically in batches.

This is purely a gas optimization. The economic effect is the same: the treasury earns its share of all borrower interest, compounding over time.

### The Impact on Depositors

The reserve factor directly affects supply APY. If borrowers pay 5% interest and the reserve factor is 20%, depositors effectively receive the interest generated on 80% of the borrower payments (before adjusting for utilization). Higher reserve factors mean more protocol revenue but lower yields for suppliers.

-

## Minting and Burning: The Lifecycle of an aToken

aTokens cannot be freely created. Only the Pool contract can mint or burn them, and it does so as part of supply and withdraw operations.

### On Supply: Minting

When you deposit 1,000 USDC and the current liquidity index is 1.05:

1. The protocol computes the scaled amount: `1,000 / 1.05 = 952.38`
2. It mints 952.38 scaled aTokens to your address
3. Your `balanceOf()` immediately returns `952.38 × 1.05 = 1,000` - exactly what you deposited
4. If this is your first deposit of this asset, the protocol automatically enables it as collateral

The return value from `mint()` tells the Pool whether this is a first-time deposit, which triggers the auto-collateral logic.

### On Withdraw: Burning

When you withdraw 1,000 USDC and the index has grown to 1.10:

1. The protocol computes the scaled amount to burn: `1,000 / 1.10 = 909.09`
2. It burns 909.09 scaled aTokens from your address
3. The aToken contract transfers 1,000 USDC to you
4. If you withdrew everything, the protocol disables this asset as collateral

The aToken contract itself holds all the underlying assets - it is the vault. When you withdraw, the underlying tokens come directly from the aToken contract to you.

### The Lifecycle Visualized

```
SUPPLY:  You send 1,000 USDC → Protocol mints ~952 scaled aTokens
         Your balanceOf() reads 1,000 aUSDC immediately

         ... time passes, index grows from 1.05 to 1.10 ...

         Your balanceOf() now reads 1,047 aUSDC (no transactions occurred)

WITHDRAW: You request 1,047 USDC → Protocol burns ~952 scaled aTokens
          You receive 1,047 USDC in your wallet
```

-

## Transfers and Composability

aTokens are fully transferable ERC-20 tokens. You can send your aUSDC to another wallet, a multisig, a DAO treasury, or another DeFi protocol. The recipient immediately begins earning interest on the transferred position.

### How Transfers Work

When you transfer 100 aUSDC:

1. The protocol converts to scaled units: `100 / currentIndex` scaled tokens move
2. The recipient's `balanceOf()` reflects the transferred amount plus ongoing interest
3. The protocol calls `Pool.finalizeTransfer()` to validate the sender's health factor

### The Health Factor Safety Check

This is the critical constraint: **you cannot transfer aTokens if doing so would make your position liquidatable.** If you have borrowed against your aToken collateral, transferring too much away would leave your debt undercollateralized.

The protocol checks your health factor after the transfer. If it would drop below 1.0, the transaction reverts. This prevents borrowers from extracting collateral through transfers instead of withdrawals (which have the same check).

### Composability in DeFi

Because aTokens are standard ERC-20s, they can be:

- **Held in cold storage** - still earns interest, no interaction needed
- **Deposited into other protocols** - use aTokens as collateral elsewhere
- **Sent to multisigs or DAOs** - treasury management with built-in yield
- **Traded on DEXs** - though rebasing complicates AMM accounting

The rebasing behavior does create friction with some DeFi protocols. AMMs that cache token balances (like simple x*y=k designs) will miscount aToken reserves over time. Any integration must call `balanceOf()` fresh rather than relying on cached values.

-

## The Contract Hierarchy (Brief)

For those who want to trace the code, here is how the aToken inherits its behavior:

```
ERC20 (modified OpenZeppelin base)
  └── ScaledBalanceTokenBase
        - Stores scaled balances
        - Provides _mintScaled() and _burnScaled()
        └── IncentivizedERC20
              - Hooks into Aave's reward/incentives system
              - Notifies incentives controller on mint/burn/transfer
              └── AToken
                    - Overrides balanceOf() and totalSupply() with index math
                    - Implements mint(), burn(), transfer with health check
                    - Holds underlying assets (the vault)
                    - Handles treasury minting
```

The `IncentivizedERC20` layer is worth noting: every mint, burn, and transfer notifies an external incentives controller. This is how Aave distributes liquidity mining rewards without modifying the core token logic.

-

## Summary

aTokens are the depositor's interface to Aave V3. They wrap complex scaled-balance accounting into an intuitive ERC-20 that "just works" - your balance goes up, and you can transfer or redeem at any time.

**Key takeaways:**

- **aTokens are rebasing ERC-20s.** Your balance increases every second as borrowers pay interest. No claiming, staking, or transactions required.

- **1 aToken always equals approximately 1 underlying token.** The quantity changes to reflect interest, not the price. This makes aTokens intuitive: balance = value.

- **Under the hood, it is a single multiplication:** `actualBalance = scaledBalance × liquidityIndex`. The scaled balance is stored; the index grows globally.

- **The rebasing design prioritizes user experience** - your balance *is* your value. The trade-off is that integrating protocols must handle a changing `balanceOf()` between transactions.

- **The treasury earns revenue** by accumulating a share of borrower interest as aTokens. The reserve factor (typically 10-20%) determines the split.

- **Transfers include a health factor check.** You cannot send away aTokens that are backing active borrows, preventing collateral extraction.

- **The aToken contract is the vault.** It holds all underlying assets and only the Pool can authorize withdrawals.

In the next chapter, we examine the other side of the equation: **debt tokens**, which use the same scaled balance pattern to track what borrowers owe.
