# Chapter 5: Debt Tokens --- Tracking What You Owe

If aTokens are a receipt for what the protocol owes *you*, debt tokens are the opposite: they represent what *you* owe the protocol. When you borrow from Aave V3, you do not just receive tokens and a database entry. You receive debt tokens --- on-chain tokens that track your growing obligation.

This chapter covers what debt tokens represent economically, why they cannot be transferred, the difference between variable and stable debt, why stable rates are being phased out, and how borrow delegation works.

---

## The Economic Idea: An IOU That Grows

When you borrow 1,000 USDC from Aave at a variable rate, the protocol mints 1,000 variable debt tokens to your address. These tokens represent your debt. Just like aTokens, their `balanceOf()` changes over time --- but in this case, your balance goes **up** as interest accrues, reflecting a growing obligation rather than growing wealth.

| Day   | Your Debt Token Balance | What It Means                      |
|-------|------------------------|------------------------------------|
| Day 0 | 1,000.00 vdUSDC       | You borrowed 1,000 USDC            |
| Day 30| 1,004.11 vdUSDC       | 30 days of interest at ~5% APR     |
| Day 90| 1,012.33 vdUSDC       | 90 days of interest                |
| Day 365| 1,050.00 vdUSDC      | One year of interest               |

When you repay, debt tokens are burned. Pay back 500 USDC, and 500 debt tokens disappear. Pay back everything, and your debt token balance goes to zero.

The lifecycle is straightforward:

```
Borrow:  Protocol mints debt tokens to you → you receive the borrowed assets
Repay:   You return assets to the protocol → debt tokens are burned
```

Debt tokens serve three practical purposes:

1. **On-chain accounting** --- anyone can call `balanceOf()` to see exactly how much a user owes, including accrued interest, at any moment.
2. **Off-chain indexing** --- Transfer events on mint and burn let subgraphs and block explorers track borrowing activity.
3. **Integration surface** --- other contracts can read debt positions through a familiar ERC-20 interface.

---

## Why Debt Tokens Are Non-Transferable

This is one of the most important design decisions in the protocol. Debt tokens implement the ERC-20 interface, but `transfer()`, `transferFrom()`, and `approve()` always revert.

### The Problem with Transferable Debt

Imagine if debt tokens *were* transferable. A malicious user could:

1. Deposit collateral (say, 2 ETH worth \$4,000)
2. Borrow 2,000 USDC against it
3. Transfer the 2,000 debt tokens to a random address --- a wallet with no collateral
4. Walk away with the 2,000 USDC, free and clear

The recipient of the debt tokens has no collateral backing the position. No one can liquidate them effectively. The protocol is now holding 2 ETH of collateral against... nothing, while 2,000 USDC of debt is assigned to an empty wallet. The protocol is instantly insolvent.

### The Solution

By making debt tokens non-transferable, Aave ensures that the borrower who created the debt is always the one responsible for it. The collateral-to-debt linkage is preserved at all times. The only way to create debt is through the Pool contract, which enforces collateral requirements. The only way to remove debt is to repay it.

The ERC-20 interface is still implemented (rather than using a custom interface) because `balanceOf()`, `totalSupply()`, and Transfer events are useful for reading and tracking. Only the mutation functions --- transfer, transferFrom, approve --- are blocked.

---

## Variable Debt Tokens: The Standard Path

Variable debt tokens use the same scaled balance mechanism as aTokens, but with the **variable borrow index** instead of the liquidity index.

### How the Balance Is Computed

The pattern is identical to aTokens:

$$actualDebt = scaledDebtBalance \times currentVariableBorrowIndex$$

When you borrow 1,000 USDC and the variable borrow index is 1.02:

$$scaledDebt = \frac{1{,}000}{1.02} = 980.39$$

The contract stores 980.39 as your scaled debt balance. As interest accrues, the variable borrow index grows:

| Variable Borrow Index | Your balanceOf()              | Interest Owed |
|----------------------|------------------------------|---------------|
| 1.02                 | 980.39 × 1.02 = 1,000.00    | 0.00          |
| 1.04                 | 980.39 × 1.04 = 1,019.61    | 19.61         |
| 1.06                 | 980.39 × 1.06 = 1,039.22    | 39.22         |
| 1.08                 | 980.39 × 1.08 = 1,058.82    | 58.82         |

The code is short and mirrors the aToken exactly:

```solidity
function balanceOf(address user) public view override returns (uint256) {
    uint256 scaledBalance = super.balanceOf(user);
    if (scaledBalance == 0) {
        return 0;
    }
    return scaledBalance.rayMul(
        POOL.getReserveNormalizedVariableDebt(_underlyingAsset)
    );
}
```

One technical difference from the supply side: the variable borrow index uses **compound interest** rather than linear interest. Borrow rates are typically higher than supply rates, so compounding matters more. Over a year at 5%, the difference between linear and compound is small, but over longer periods or at higher rates, compounding produces meaningfully larger debt --- which is the conservative (protocol-safe) choice.

### Quick Reference

| Function                | Returns                          | Changes Every Second? |
|------------------------|----------------------------------|----------------------|
| `balanceOf(user)`      | Actual debt with accrued interest | Yes                  |
| `scaledBalanceOf(user)` | Raw stored scaled balance        | No (only on borrow/repay) |
| `totalSupply()`        | Total variable debt, all users   | Yes                  |
| `scaledTotalSupply()`  | Raw total scaled debt            | No (only on borrow/repay) |

The `totalSupply()` of the variable debt token, multiplied by the current index, gives the total variable debt across all borrowers. This is one of the most important numbers in the protocol --- it feeds directly into utilization calculations and interest rate determination.

---

## Stable Debt Tokens: The Locked-Rate Alternative

While variable debt tokens share a single global index (like aTokens), stable debt tokens take a fundamentally different approach: each borrower **locks in their own interest rate** at the time they borrow.

### The Economic Idea

Variable rates float with market conditions. If utilization spikes, your borrow rate could jump from 3% to 15% overnight. Some borrowers want predictability --- they would rather pay a known rate, even if it is somewhat higher, than face rate volatility.

Stable borrowing in Aave attempts to provide this. When you borrow at the stable rate, you lock in the current stable rate. Your debt compounds at that fixed rate regardless of what happens to utilization or variable rates.

### How It Differs from Variable Debt

The key difference is in how `balanceOf()` works:

- **Variable debt**: `scaledBalance × globalVariableBorrowIndex` --- everyone shares one index
- **Stable debt**: `principal × (1 + userRate)^timeSinceLastUpdate` --- each user has their own rate and timestamp

Because each user can have a different rate, the contract stores the principal (not a scaled balance) and the user's personal rate. It then computes compound interest individually for each user when `balanceOf()` is called.

### The Average Stable Rate

Since every stable borrower can have a different rate, the protocol must track a **weighted average stable rate** across all stable borrowers. This average feeds into the interest rate model --- the total interest generated by stable borrowers affects overall utilization and rate calculations.

When a new stable borrow occurs, the average is recalculated:

$$newAverage = \frac{oldAverage \times oldTotalDebt + newRate \times newBorrowAmount}{newTotalDebt}$$

### Rate Blending on Additional Borrows

If a user already has stable debt and borrows more, their personal rate is blended. Suppose you borrowed 1,000 USDC at 4% and now borrow another 500 USDC at 6%:

$$newRate = \frac{4\% \times 1{,}000 + 6\% \times 500}{1{,}500} = 4.67\%$$

Your entire stable debt position now compounds at 4.67%.

### Rebalancing: The Safety Valve

Stable rates create a risk: if market rates rise dramatically, stable borrowers continue paying their low locked-in rate. The protocol earns less interest than it needs, potentially squeezing depositor yields.

Aave addresses this with **rebalancing**. Anyone can call `rebalanceStableBorrowRate()` on the Pool contract to force a user's stable rate to update to the current market rate. This is permissible when:

- The user's locked rate is significantly below the current stable rate, **or**
- Utilization is extremely high and the protocol needs rates to adjust

Rebalancing is a blunt instrument --- it removes the stability guarantee. In practice, the conditions for triggering a rebalance have been set conservatively, and most stable borrowers are not affected during normal market conditions.

---

## Why Stable Rates Are Being Deprecated

Despite the conceptual appeal of predictable borrowing costs, stable rates have been a persistent source of complexity and risk in Aave. Here is why they are being phased out:

### 1. Low Adoption

Most borrowers choose variable rates because they are typically lower. The stable rate premium (often 1--3% above variable) has not justified the complexity for most users. On many Aave markets, stable debt represents less than 5% of total borrows.

### 2. Gaming Risk

Sophisticated users found ways to exploit the rebalancing mechanism. By carefully timing borrows and repayments around utilization changes, it was possible to lock in favorable stable rates and avoid rebalancing. Several governance proposals addressed specific edge cases, but each fix added complexity.

### 3. Complexity Cost

Stable debt requires per-user rate storage, weighted average tracking, rate blending on additional borrows, and rebalancing logic. This adds gas cost to every interaction, code surface area for bugs, and cognitive overhead for auditors and integrators --- all for a feature used by a small minority of borrowers.

### 4. Governance Attack Surface

The rebalancing conditions are parameters that governance must set correctly. Too aggressive, and stable borrows lose their stability promise. Too conservative, and the protocol takes on rate risk. Getting this right across many assets and market conditions has proven difficult.

### Current Status

Newer Aave V3 deployments on most chains have stable borrowing **disabled** at the configuration level. The contracts are deployed, but `stableBorrowingEnabled` is set to `false`, preventing new stable borrows. Existing stable positions can still be repaid or rebalanced, but no new ones can be created.

Aave V4 does not include stable rate borrowing at all, confirming that the feature has been fully deprecated for future development.

---

## Variable vs Stable: The Comparison

| Property                    | Variable Debt                          | Stable Debt                          |
|----------------------------|----------------------------------------|--------------------------------------|
| Rate                        | Floats with utilization                | Locked at borrow time                |
| Rate risk                   | Borrower bears it                      | Protocol bears it (partially)        |
| Balance computation         | `scaledBalance × globalIndex`          | `principal × (1+rate)^time`          |
| Storage per user            | Scaled balance + last index            | Principal + personal rate + timestamp |
| Gas cost for balanceOf()    | Cheaper (one multiplication)           | More expensive (compound interest calc) |
| Adoption                    | ~95%+ of all borrows                   | <5%, declining                       |
| Status                      | Active everywhere                      | Disabled on most new deployments     |
| In Aave V4?                 | Yes                                    | No                                   |

For practical purposes, **variable debt is Aave's debt model**. Stable debt is legacy functionality.

---

## Borrow Delegation: Letting Someone Else Borrow Against Your Collateral

Both debt token types support **borrow delegation** --- a powerful primitive that allows one user to authorize another to borrow against the first user's collateral.

### How It Works

1. **Alice** has 10,000 USDC of collateral in Aave but does not want to borrow herself.
2. Alice calls `approveDelegation(bob, 5000)` on the variable debt token for USDC, granting Bob permission to create up to 5,000 USDC of debt against her collateral.
3. **Bob** calls `borrow()` with `onBehalfOf = Alice`.
4. The protocol checks Bob's delegation allowance from Alice.
5. Debt tokens are minted to **Alice's address** (Alice holds the debt).
6. The borrowed USDC is sent to **Bob's address** (Bob gets the funds).
7. Bob's allowance from Alice is decreased by the borrowed amount.

### The Key Distinction

Delegation controls who can **create** debt. It does not transfer existing debt. Alice's debt tokens never move to Bob. Alice is always the one responsible for the debt, and Alice's collateral backs it. If Alice's health factor drops too low, *Alice* gets liquidated.

### Use Cases

- **Credit delegation**: Users with excess collateral can earn fees by delegating borrowing power, often in exchange for off-chain agreements.
- **Protocol integrations**: Smart contracts can borrow on behalf of users in more complex strategies.
- **Undercollateralized lending**: Combined with off-chain agreements (legal contracts, reputation systems), delegation enables lending where the borrower does not post collateral themselves --- the delegator's collateral covers it.

Delegation does not change the fundamental invariant: every unit of debt in Aave is backed by collateral. It just allows the collateral provider and the fund recipient to be different addresses.

---

## Mint and Burn: The Mechanics (Brief)

When a borrow happens, the Pool calls `VariableDebtToken.mint()`, which stores `borrowAmount / currentIndex` as scaled debt. When a repayment happens, the Pool calls `burn()`, which removes `repayAmount / currentIndex` in scaled terms.

Both operations also compute a `balanceIncrease` --- the interest that accrued on the user's existing debt since their last interaction. This is emitted in events for off-chain tracking but does not require separate storage. The index handles it automatically.

Events use **actual** (non-scaled) amounts. A borrow of 1,000 USDC emits a Transfer event for 1,000 tokens, even though the stored scaled value might be 952.38. This keeps block explorers and indexers showing correct human-readable values.

### How Total Debt Drives the Protocol

The total scaled supply of the variable debt token, multiplied by the current variable borrow index, gives the **total variable debt** across all borrowers:

$$totalVariableDebt = scaledTotalSupply \times variableBorrowIndex$$

This number is central to everything:

- **Utilization**: `totalDebt / (availableLiquidity + totalDebt)` --- which determines interest rates
- **Treasury accrual**: The growth in total debt between updates equals the interest generated by borrowers
- **Solvency**: Total aToken claims (depositor money) must always be backed by underlying assets plus outstanding debt

Every mint increases scaled total supply. Every burn decreases it. The index handles the interest math in between.

---

## Summary

Debt tokens complete the dual-sided accounting of Aave V3. Where aTokens track what depositors are owed, debt tokens track what borrowers owe.

**Key takeaways:**

- **Debt tokens are IOUs that grow.** Your debt token balance increases over time as interest accrues --- the same rebasing mechanism as aTokens, but on the liability side.

- **Debt tokens are non-transferable.** This is non-negotiable. If debt could be transferred, borrowers could dump obligations on empty wallets and walk away with borrowed funds. The collateral-to-debt linkage must be preserved.

- **Variable debt uses the same scaled balance pattern as aTokens:** `balanceOf() = scaledBalance × variableBorrowIndex`. It is simple, gas-efficient, and handles all borrowers with a single global index.

- **Stable debt locks in per-user rates**, computing `principal × (1 + rate)^time` individually. It is more complex, more expensive, and largely unused.

- **Stable rates are being deprecated** due to low adoption, gaming risks, governance complexity, and the fact that most borrowers prefer cheaper variable rates.

- **Borrow delegation** lets one user authorize another to borrow against their collateral. The delegator holds the debt; the delegate receives the funds. This enables credit delegation and advanced protocol integrations.

In the next chapter, we tie everything together by walking through the complete supply, borrow, repay, and withdraw flows end-to-end.
