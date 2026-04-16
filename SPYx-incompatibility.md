# Why Non-Wrapped SPYx Cannot Be Listed in an Aave V3 Fork

This note explains why the non-wrapped SPYx token is incompatible with an Aave V3–based lending protocol. The wrapped (non-rebasing / static-balance) version must be used instead.

## The Core Assumption Aave Makes

Aave V3 does not store user balances directly. For every reserve it stores a single **liquidity index** that accumulates supply-side interest, and for every user it stores a **scaled balance**:

$$scaledBalance = \frac{depositAmount}{liquidityIndex_{deposit}}$$

The "real" aToken balance is then computed on demand:

$$actualBalance = scaledBalance \times currentLiquidityIndex$$

This design gives Aave O(1) interest accrual — one storage write to the index implicitly updates every user.

The entire accounting system rests on **one assumption**: the aToken contract's balance of the underlying asset only changes when Aave itself mints, burns, transfers, borrows, or repays. All yield is supposed to come from *borrowers paying interest*, which is what drives the liquidity index upward.

## Why Non-Wrapped SPYx Breaks This

Non-wrapped SPYx is a **value-accruing / rebasing-style token**: the holder's balance (or the token's internal share-to-asset ratio) changes over time from yield that is external to Aave. When Aave's aToken contract holds SPYx, its underlying balance grows on its own — silently, outside any Aave transaction.

This conflicts with Aave's model in several concrete ways.

### 1. Yield Is Invisible to the Liquidity Index

The liquidity index only grows from interest paid by borrowers, applied inside `updateState()`. Yield that SPYx accrues natively never flows through the interest-rate model, so it never becomes part of the index.

Result: suppliers' aToken balances (`scaledBalance × index`) do **not** reflect the native SPYx yield at all. The yield exists on the aToken contract's books but cannot be withdrawn by anyone — it becomes stranded value or, worse, gets mis-attributed on the next interaction.

### 2. The Aave Invariant Breaks

Aave assumes:

$$\text{aToken.underlyingBalance} \geq \sum_{users}(scaledBalance_i) \times currentLiquidityIndex - \text{totalBorrowed}$$

With rebasing SPYx, the left side grows autonomously while the right side does not. The two sides drift apart. Treasury accounting, reserve-factor splits, and `getReserveNormalizedIncome()` all assume this invariant holds — once it drifts, every downstream calculation is subtly wrong.

### 3. Donations / Rebases Can Be Weaponized

Because extra underlying can appear on the aToken contract without a corresponding mint, an attacker (or even normal rebase mechanics) can inflate the contract's balance mid-transaction. This is exactly the class of "inflation / donation" attack that Aave's scaled-balance architecture is otherwise immune to. With a rebasing underlying, that immunity is lost.

### 4. Borrow-Side Accounting Also Breaks

Borrowers repay the same unit they borrowed. If 1 SPYx today represents more "value" than 1 SPYx at borrow time (because the token rebased up), the variable borrow index — which only tracks interest, not changes in the unit itself — under-measures the real debt. Borrowers effectively pocket the native yield on borrowed SPYx, and lenders lose it.

### 5. Liquidations Use a Stale Unit of Account

Health-factor and liquidation math are denominated in token units scaled by the oracle price. If the token unit itself silently appreciates, the oracle price must perfectly track rebases in real time, or positions will be liquidated (or fail to liquidate) at the wrong threshold. This is fragile even with a well-designed oracle and fatal without one.

## Why the Wrapped Version Is Safe

A properly wrapped SPYx (static balance, value accrues via an increasing share price internal to the wrapper) has a **constant balance per share**. The aToken contract's underlying balance only changes when Aave itself mints, burns, or transfers — exactly the condition Aave's accounting requires. Native yield is captured by an appreciating wrapper share price, which suppliers realize on unwrap, completely outside Aave's interest-rate machinery.

## Summary

Aave V3 is built on the assumption that the underlying token is a plain, non-rebasing ERC-20. The liquidity-index / scaled-balance architecture is what gives Aave its O(1) elegance, but it also means any external balance change to the aToken contract corrupts the system's invariants — silently, and with no way for the protocol to detect or reconcile it.

Listing non-wrapped SPYx would leak yield, break the supply/borrow invariant, expose the market to donation-style manipulation, and mis-price liquidations. Use the wrapped version.
