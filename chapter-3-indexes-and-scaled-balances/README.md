# Chapter 3: Interest Rate Indexes and Scaled Balances

This chapter covers one of the most elegant design patterns in all of DeFi: how Aave V3 tracks interest accrual for thousands of users without ever touching their individual balances. Once you understand this mechanism, everything else in the protocol - aTokens, debt tokens, supply flows, liquidations - falls into place.

<video src="animations/final/liquidity_index.webm" controls autoplay loop muted playsinline style="width:100%;max-width:800px;border-radius:8px;margin:20px 0"></video>

-

## The Problem: You Cannot Update 10,000 Balances

Imagine building a lending protocol the naive way. There are 10,000 users who have supplied ETH. Interest accrues every second. To keep everyone's balances correct, you would need to loop through all 10,000 accounts and update each one's stored balance every time interest should be credited.

On a blockchain, this is impossible. A single loop iteration costs gas. Ten thousand iterations would cost more gas than fits in a block. And interest accrues continuously - you cannot skip updates without losing accuracy.

Even batching would not help. What if 500 new users deposit between batches? What if someone tries to withdraw mid-batch? The accounting becomes a nightmare.

So Aave needs a system where:

- Interest accrues for all users simultaneously
- No loop over balances is ever required
- A single storage write applies interest to every user at once
- Any user's balance can be queried at any time and reflects up-to-date interest

The solution is **indexes** and **scaled balances**.

-

## The Index: A Cumulative Multiplier

The **liquidity index** is a single number, stored once per asset, that encodes the entire history of supply-side interest since the reserve was created. It starts at 1.0 and only ever increases.

Think of it as an exchange rate between "original dollars" and "current dollars." If the liquidity index is 1.08, then one dollar deposited at the very beginning of the protocol is now worth \$1.08. The index captures every second of interest that has ever accrued, compressed into one number.

Think of it like a stock that never pays dividends but always goes up. If you buy at \$105 per share and later it is at \$110, you earned the difference - regardless of what happened before you bought. The index works the same way: your return is entirely determined by the ratio between the index when you exit and the index when you entered.

One important property: **an index can never decrease.** Interest always accumulates over time, even when rates fluctuate. If the supply rate drops from 5% to 1%, the index still grows - just more slowly. It is a monotonically increasing number.

Every reserve has its own liquidity index. USDC has one, ETH has one, WBTC has one. They grow at different rates because each market has different utilization and interest rates.

### How the Liquidity Index Is Computed

Each time anyone interacts with a reserve (supply, withdraw, borrow, repay, liquidate), the index is updated. The formula uses **simple (linear) interest** for the elapsed interval:

$$LI_{new} = LI_{old} \times \left(1 + R_{supply} \times \frac{\Delta t}{seconds_{year}}\right)$$

Where:
- $LI_{old}$ is the stored liquidity index from the last update
- $R_{supply}$ is the current annual supply rate (from Chapter 2's kink model)
- $\Delta t$ is the number of seconds since the last update
- $seconds_{year}$ = 31,536,000

The term $R_{supply} \times \frac{\Delta t}{seconds_{year}}$ converts the annual rate into the fraction of interest earned over the elapsed interval. Multiplying the old index by $(1 + \text{that fraction})$ gives the new index.

**Example:** The current liquidity index is 1.050000. The supply rate is 3.6% APR. 3,600 seconds (1 hour) have passed since the last update.

$$LI_{new} = 1.050000 \times \left(1 + 0.036 \times \frac{3600}{31536000}\right) = 1.050000 \times 1.000004109 = 1.050004$$

Tiny per update, but over a full year at 3.6%, the index grows from 1.05 to roughly 1.0878.

### The Variable Borrow Index

The **variable borrow index** is the same concept for the debt side. It tracks how much a unit of variable-rate debt has grown since inception. Because borrow rates are always higher than supply rates (the spread covers the reserve factor and idle capital), the borrow index grows faster than the liquidity index.

The key difference: the borrow index uses **compound interest**:

$$VBI_{new} = VBI_{old} \times \left(1 + \frac{R_{borrow}}{seconds_{year}}\right)^{\Delta t}$$

This is true compounding - interest accrues on previously accrued interest. On-chain, Aave computes this with a third-order Taylor expansion rather than actual exponentiation (which would be too gas-expensive):

$$(1 + x)^n \approx 1 + nx + \frac{n(n-1)}{2}x^2 + \frac{n(n-1)(n-2)}{6}x^3$$

where $x = \frac{R_{borrow}}{seconds_{year}}$ and $n = \Delta t$.

### Why Linear for Supply, Compound for Borrow?

**Conservative debt accounting.** Borrow rates are higher. Over long intervals between updates on quiet reserves, the difference between simple and compound interest becomes meaningful. Compounding ensures the protocol never underestimates what borrowers owe - underestimating debt would create bad debt.

**The surplus is a feature.** The small gap between compound interest on debt and simple interest on deposits means the protocol collects slightly more from borrowers than it distributes to suppliers. This tiny surplus acts as an additional safety buffer. On active reserves where updates happen every few seconds, the difference is negligible.

### When Do Indexes Update?

Indexes are not updated on a schedule. They update whenever *any* user interacts with the reserve. The causal chain:

**Utilization changes → Borrow rate recalculated → Supply rate derived → Indexes updated**

Between interactions, the stored indexes are technically stale. But as we will see, `balanceOf()` computes the live value on the fly so balances are always accurate.

-

## Scaled Balances: The Accounting Trick

Here is the key insight. Aave never stores your "actual" balance. Instead, it stores a **scaled balance** - your deposit amount divided by the liquidity index at the moment you deposited.

$$scaledBalance = \frac{depositAmount}{liquidityIndex_{deposit}}$$

To recover your actual balance at any point in the future, you multiply by the *current* index:

$$actualBalance = scaledBalance \times currentLiquidityIndex$$

Why does this work? Because the index is a cumulative multiplier. Dividing by the index at deposit time "normalizes" your balance to the protocol's starting point. Multiplying by the current index then applies all the interest that has accrued since you deposited.

Here is the math made explicit. Say you deposit \$1,000 when the index is 1.05, and later the index reaches 1.10:

$$scaledBalance = \frac{1000}{1.05} = 952.38$$

$$actualBalance = 952.38 \times 1.10 = 1047.62$$

You earned \$47.62, which is exactly the interest that accrued between index 1.05 and 1.10. The ratio `1.10 / 1.05 = 1.0476` represents a 4.76% return over that period, regardless of how long it took or what the rates were along the way.

The same principle applies to debt. When you borrow, your debt is divided by the variable borrow index. To find your current debt, multiply by the current borrow index.

-

## How the Index Evolves With Changing Rates

A critical feature of the index: it captures varying interest rates over time without storing the rate history. Here is a concrete example.

Suppose ETH is just listed on Aave. The liquidity index starts at 1.0. Over three months, the supply rate changes as utilization shifts:

| Month | Annual Supply Rate | Index Calculation | New Index |
|-------|-------------------|-------------------|-----------|
| End of Month 1 | 12% | $$1.0 \times (1 + 0.12 \times \frac{1}{12})$$ | 1.0100 |
| End of Month 2 | 6% | $$1.01 \times (1 + 0.06 \times \frac{1}{12})$$ | 1.0150 |
| End of Month 3 | 8% | $$1.015 \times (1 + 0.08 \times \frac{1}{12})$$ | 1.0218 |

A user who deposited 10 ETH at inception now has:

$$actualBalance = 10 \times 1.0218 = 10.218 \text{ ETH}$$

They earned 0.218 ETH across three months with three different interest rates. The index absorbed all of that complexity into a single number. No one had to store the rate history or calculate compound interest across multiple periods - the index did it automatically, one update at a time.

This is the fundamental insight: **the index is a running product of all historical rate intervals.** Each update multiplies the old index by `(1 + rate × timeElapsed)`, and the result encodes the entire interest history.

-

## Alice and Bob: A Complete Walkthrough

Let's trace through a full scenario with actual numbers.

### T=0: Alice Deposits 1,000 USDC

The reserve just launched. The liquidity index is 1.000000.

$$scaledBalance_{Alice} = \frac{1000}{1.000000} = 1000.00$$

| User  | Scaled Balance | Index | Actual Balance |
|-------|---------------|-------|----------------|
| Alice | 1,000.00 | 1.000000 | 1,000.00 |

### T=1: Time Passes, Borrowers Pay Interest

Various users have been borrowing USDC and paying interest. The liquidity index has grown to 1.050000. Alice has not interacted with the protocol at all. Her stored scaled balance is still exactly 1,000.00. But if anyone calls `balanceOf(Alice)`:

$$actualBalance = 1000.00 \times 1.050000 = 1{,}050.00$$

| User  | Scaled Balance | Index | Actual Balance |
|-------|---------------|-------|----------------|
| Alice | 1,000.00 | 1.050000 | 1,050.00 |

Alice earned \$50 in interest without a single transaction. No one updated her balance. No one ran a batch job. The protocol simply updated the index (one storage write), and Alice's balance grew automatically.

### T=1: Bob Deposits 2,000 USDC

Bob deposits while the index is 1.050000:

$$scaledBalance_{Bob} = \frac{2000}{1.050000} = 1{,}904.76$$

| User  | Scaled Balance | Index | Actual Balance |
|-------|---------------|-------|----------------|
| Alice | 1,000.00 | 1.050000 | 1,050.00 |
| Bob | 1,904.76 | 1.050000 | 2,000.00 |

Notice that Bob's scaled balance (1,904.76) is less than his deposit (2,000). This is correct - Bob is "entering" at a higher index, so his scaled balance reflects what his deposit is worth in "original dollars." When multiplied by the current index, it gives back exactly 2,000.

### T=2: More Time Passes, Index Reaches 1.100000

| User  | Scaled Balance | Index | Actual Balance |
|-------|---------------|-------|----------------|
| Alice | 1,000.00 | 1.100000 | 1,100.00 |
| Bob | 1,904.76 | 1.100000 | 2,095.24 |

**Alice** has earned \$100 total (10% on her original \$1,000), reflecting the full period since she deposited.

**Bob** has earned \$95.24 (about 4.76% on his original \$2,000), reflecting only the period since *he* deposited. The index went from 1.05 to 1.10 during Bob's time in the pool, a 4.76% increase.

The system perfectly tracks different entry times using a single global index. No per-user timestamp, no per-user rate tracking.

### T=2: Alice Withdraws 500 USDC

When Alice withdraws, the protocol burns the equivalent scaled amount:

$$scaledAmountToBurn = \frac{500}{1.100000} = 454.55$$

$$scaledBalance_{Alice}^{new} = 1000.00 - 454.55 = 545.45$$

Alice receives 500 USDC in her wallet. Her remaining position:

$$actualBalance = 545.45 \times 1.100000 = 600.00 \text{ USDC}$$

This makes sense: Alice had 1,100.00 USDC in the protocol, withdrew 500.00, and has 600.00 remaining.

### T=3: Index Reaches 1.150000

| User  | Scaled Balance | Index | Actual Balance |
|-------|---------------|-------|----------------|
| Alice | 545.45 | 1.150000 | 627.27 |
| Bob | 1,904.76 | 1.150000 | 2,190.48 |

Alice's remaining 600 USDC has grown to 627.27 (earning the same rate as everyone else). Bob's position has grown to 2,190.48.

The system handles deposits, withdrawals, and different entry times seamlessly, all through one global index.

-

## Why This Design Is Elegant

The power of the index-and-scaled-balance pattern comes down to a single property: **you only update one number (the index) to effectively update every user's balance simultaneously.**

This gives you:

**O(1) state updates.** Updating the index is one storage write, whether there are 10 users or 10 million. The cost is identical.

**O(1) balance queries.** Computing any user's balance is one multiplication: `scaledBalance * index`. No iteration, no historical lookups, no aggregation.

**No "stale balance" problem.** Even if a user disappears for a year, their balance is always correct when queried. The index has been growing with every interaction by *any* user in that market, and the multiplication picks up all that accrued interest.

**Perfect composability.** Because `balanceOf()` returns the up-to-date actual balance, aTokens compose with any DeFi protocol that reads ERC-20 balances. Yield aggregators, dashboards, and wallets all see the correct number without special integration.

**Correctness under concurrent deposits.** Multiple users depositing at different times and amounts are all handled correctly. Each user's scaled balance captures their entry point, and the ratio between indexes handles everything else.

-

## How "Interest Accrues" Without Any Transaction

A common source of confusion: if indexes are only updated when someone interacts with the protocol, how does interest "accrue" between transactions?

The answer is that interest accrues *mathematically* but not *in storage*. Between transactions, the stored index is stale. But any code that reads a balance (including `balanceOf()`) first computes what the index *would be* right now based on the stored rate and elapsed time, then multiplies by the scaled balance.

Here is how `balanceOf()` works under the hood:

```solidity
function balanceOf(address user) public view override returns (uint256) {
    return super.balanceOf(user).rayMul(
        POOL.getReserveNormalizedIncome(_underlyingAsset)
    );
}
```

`super.balanceOf(user)` returns the stored scaled balance. `getReserveNormalizedIncome()` computes the live liquidity index by projecting forward from the last stored value:

```solidity
function getReserveNormalizedIncome(address asset) external view returns (uint256) {
    if (reserve.lastUpdateTimestamp == block.timestamp) {
        return reserve.liquidityIndex;  // Already up to date
    }
    return reserve.liquidityIndex.rayMul(
        MathUtils.calculateLinearInterest(reserve.currentLiquidityRate, reserve.lastUpdateTimestamp)
    );
}
```

So `balanceOf()` always returns a fresh value even if no one has interacted with the reserve in hours.

This means the returned balance is always up-to-date, even if no one has touched the reserve in hours. The stored index catches up the next time someone does interact.

This is also why aToken balances appear to change continuously in wallet UIs that poll `balanceOf()` - each call returns a slightly larger number as time passes.

-

## The Same Pattern for Debt

Everything described above applies symmetrically to debt. When you borrow:

$$scaledDebt = \frac{borrowAmount}{variableBorrowIndex_{current}}$$

When you (or anyone) queries your debt:

$$actualDebt = scaledDebt \times variableBorrowIndex_{current}$$

Your debt grows over time as the borrow index increases, just as supply balances grow as the liquidity index increases. The borrow index simply grows faster (higher rates), so debt accumulates more quickly than supply interest.

When you repay, the protocol burns the corresponding scaled debt amount. Partial repayments work exactly like partial withdrawals in the supply example above.

-

## Putting It All Together: The Supply Flow

Here is the complete sequence when someone calls `Pool.supply(USDC, 1000)`:

1. **Update state.** Call `reserve.updateState()`, which updates the liquidity index and variable borrow index based on elapsed time and current rates, and accrues treasury revenue.
2. **Validate.** Check the reserve is active, not paused, not frozen, and the supply cap is not exceeded.
3. **Recalculate rates.** With the incoming liquidity factored in, utilization drops. Recalculate and store the new supply and borrow rates.
4. **Transfer tokens.** Move 1,000 USDC from the user to the aToken contract.
5. **Mint aTokens.** The contract internally stores `scaledAmount = 1000 / currentLiquidityIndex`, but from the user's perspective they receive 1,000 aUSDC — because `balanceOf()` multiplies the scaled amount back by the index.

Every operation follows the same pattern: **update state first, then act.** This ensures that all interest accrual is accounted for before any balances change, preventing users from gaming the timing of their transactions.

-

## Summary

The index-and-scaled-balance pattern is the accounting foundation of Aave V3. Every other mechanism - aTokens, debt tokens, treasury accruals, liquidation calculations - builds on it.

**Key takeaways:**

- The **liquidity index** is a cumulative multiplier that tracks total supply-side interest since inception. One number, shared by all suppliers of that asset.
- The **variable borrow index** is the same concept for debt, growing faster because borrow rates exceed supply rates.
- **Scaled balances** are user balances divided by the index at deposit/borrow time. This is the *only* per-user value stored on-chain.
- **Actual balances** are computed on the fly: `scaledBalance * currentIndex`. This always reflects up-to-date interest, even between transactions.
- **`updateState()`** is called at the start of every operation to bring indexes current and accrue treasury revenue.
- This design achieves **O(1) cost** for interest accrual regardless of whether the protocol has 10 users or 10 million.

The elegance is in what the protocol *does not* do: it does not loop, it does not batch, it does not schedule. It stores one number per asset that grows over time, and derives everything else from that number on demand.

In the next chapter, we will see how aTokens wrap this scaled balance system into an ERC-20 interface that makes interest-bearing deposits feel like holding a normal token.
