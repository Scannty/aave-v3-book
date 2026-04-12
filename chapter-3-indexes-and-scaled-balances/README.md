# Chapter 3: Interest Rate Indexes and Scaled Balances

This chapter covers one of the most elegant design patterns in all of DeFi: how Aave V3 tracks interest accrual for thousands of users without touching their individual balances. If you understand this chapter, everything that follows --- aTokens, debt tokens, supply/borrow flows --- will make immediate sense.

<video src="../animations/final/liquidity_index.webm" controls autoplay loop muted playsinline style="width:100%;max-width:800px;border-radius:8px;margin:20px 0"></video>

---

## The Problem: Updating Balances Doesn't Scale

Imagine a naive implementation of a lending protocol. There are 10,000 users who have supplied ETH. Interest accrues every second. To keep everyone's balances accurate, the protocol would need to loop through all 10,000 users and update each of their stored balances every time interest should be credited.

This is obviously impossible on a blockchain. Gas costs would be astronomical. Even if you tried batching, the protocol would grind to a halt. And interest accrues continuously --- you can't just "skip" updates without losing accuracy.

So Aave needs a mechanism where:

- Interest accrues continuously for all users
- No loop over user balances is ever required
- A single storage write can "apply" interest to every user simultaneously
- Balances can be queried at any time and reflect up-to-date interest

The answer is **indexes** and **scaled balances**.

---

## The Liquidity Index

The **liquidity index** is a cumulative multiplier that tracks how much value a unit of supplied capital has accumulated since the reserve was initialized. It starts at `1.0` (represented as `1e27` in Aave's ray math) and only ever increases.

Think of it this way: if the liquidity index is currently `1.08`, that means one unit of capital deposited at the very beginning of the protocol would now be worth `1.08` units. The index encodes the entire history of supply-side interest into a single number.

Every reserve in Aave V3 has its own liquidity index, stored in the `ReserveData` struct:

```solidity
struct ReserveData {
    // ...
    uint128 liquidityIndex;    // ray (1e27)
    uint128 variableBorrowIndex; // ray (1e27)
    uint128 currentLiquidityRate;  // ray, per-second rate
    uint128 currentVariableBorrowRate; // ray, per-second rate
    // ...
    uint40 lastUpdateTimestamp;
    // ...
}
```

The `liquidityIndex` is updated every time someone interacts with the reserve --- on every supply, withdraw, borrow, repay, liquidation, or flash loan. Between interactions, it sits in storage unchanged, but the "true" index at any moment can be computed from the stored value plus the time elapsed.

### Key Insight

The liquidity index never decreases. It is a monotonically increasing value. Even if no one is borrowing (and the supply rate is zero), the index stays flat. It never goes down because interest is never negative in Aave.

---

## The Variable Borrow Index

The **variable borrow index** is the borrower-side equivalent of the liquidity index. It tracks how much a unit of variable-rate debt has grown since the reserve was initialized.

Because borrow rates are always higher than supply rates (the spread covers the reserve factor and accounts for un-utilized capital), the variable borrow index grows faster than the liquidity index.

If the variable borrow index is `1.12`, that means one unit of variable debt taken at inception would now represent `1.12` units owed. A borrower who took a loan when the index was `1.05` and checks their debt when the index is `1.12` owes proportionally more.

The mechanics are identical to the liquidity index, just applied to debt instead of deposits.

---

## How Indexes Update

Indexes are updated inside `ReserveLogic.sol`, in the `updateState()` function. This function is called at the top of virtually every user-facing operation. It ensures that all accounting is current before any state changes occur.

The core update logic lives in the internal `_updateIndexes()` function:

```solidity
function _updateIndexes(
    DataTypes.ReserveData storage reserve,
    DataTypes.ReserveCache memory reserveCache
) internal returns (bool) {
    if (reserveCache.reserveLastUpdateTimestamp == uint40(block.timestamp)) {
        return false; // Already updated this block, nothing to do
    }

    uint256 timeDelta = block.timestamp - reserveCache.reserveLastUpdateTimestamp;

    // Update liquidity index
    uint256 cumulatedLiquidityInterest = MathUtils.calculateLinearInterest(
        reserveCache.currLiquidityRate,
        reserveCache.reserveLastUpdateTimestamp
    );
    uint256 newLiquidityIndex = cumulatedLiquidityInterest.rayMul(
        reserveCache.currLiquidityIndex
    );
    reserve.liquidityIndex = newLiquidityIndex.toUint128();

    // Update variable borrow index
    uint256 cumulatedVariableBorrowInterest = MathUtils.calculateCompoundedInterest(
        reserveCache.currVariableBorrowRate,
        reserveCache.reserveLastUpdateTimestamp,
        block.timestamp
    );
    uint256 newVariableBorrowIndex = cumulatedVariableBorrowInterest.rayMul(
        reserveCache.currVariableBorrowIndex
    );
    reserve.variableBorrowIndex = newVariableBorrowIndex.toUint128();

    reserve.lastUpdateTimestamp = uint40(block.timestamp);
    return true;
}
```

### The Compounding Formulas

There is a subtle but important difference in how the two indexes are computed.

**Liquidity index** uses **linear (simple) interest** for the elapsed period:

```
newLiquidityIndex = oldLiquidityIndex * (1 + supplyRate * timeDelta / SECONDS_PER_YEAR)
```

In code (`MathUtils.calculateLinearInterest`):

```solidity
function calculateLinearInterest(
    uint256 rate,
    uint40 lastUpdateTimestamp
) internal view returns (uint256) {
    uint256 result = rate * (block.timestamp - uint256(lastUpdateTimestamp));
    unchecked {
        result = result / SECONDS_PER_YEAR;
    }
    result = result + WadRayMath.RAY; // 1 + rate * timeDelta
    return result;
}
```

**Variable borrow index** uses **compound interest** approximated by a Taylor expansion:

```
newVariableBorrowIndex = oldVariableBorrowIndex * (1 + rate/n)^n
```

Where `n` is the number of seconds elapsed. The actual implementation uses a binomial approximation to avoid the cost of exponentiation:

```solidity
function calculateCompoundedInterest(
    uint256 rate,
    uint40 lastUpdateTimestamp,
    uint256 currentTimestamp
) internal pure returns (uint256) {
    uint256 exp = currentTimestamp - uint256(lastUpdateTimestamp);

    if (exp == 0) {
        return WadRayMath.RAY;
    }

    uint256 expMinusOne;
    uint256 expMinusTwo;
    uint256 basePowerTwo;
    uint256 basePowerThree;

    unchecked {
        expMinusOne = exp - 1;
        expMinusTwo = exp > 2 ? exp - 2 : 0;

        basePowerTwo = rate.rayMul(rate) / (SECONDS_PER_YEAR * SECONDS_PER_YEAR);
        basePowerThree = basePowerTwo.rayMul(rate) / SECONDS_PER_YEAR;
    }

    uint256 secondTerm = exp * expMinusOne * basePowerTwo;
    unchecked {
        secondTerm /= 2;
    }

    uint256 thirdTerm = exp * expMinusOne * expMinusTwo * basePowerThree;
    unchecked {
        thirdTerm /= 6;
    }

    return WadRayMath.RAY
        + (rate * exp) / SECONDS_PER_YEAR
        + secondTerm
        + thirdTerm;
}
```

This is a third-order Taylor expansion of `(1 + rate/SECONDS_PER_YEAR)^exp`. The first three terms give a very accurate approximation for typical rate values and time intervals.

### Why Linear for Supply and Compound for Borrow?

The supply side uses linear interest because the error is negligible for the typical intervals between updates (a few seconds to a few hours at most). The borrow side uses compound interest because borrow rates are higher and the protocol needs precise debt tracking to ensure solvency. The difference between the compound borrow interest and the linear supply interest also generates a small surplus that benefits the protocol.

---

## Scaled Balances

<video src="../animations/final/scaled_balance.webm" controls autoplay loop muted playsinline style="width:100%;max-width:800px;border-radius:8px;margin:20px 0"></video>

Now for the key mechanism. Aave never stores a user's "actual" balance. Instead, it stores a **scaled balance** --- the user's balance divided by the liquidity index at the time of their deposit (or the borrow index at the time of their borrow).

The scaled balance answers the question: "What is the equivalent value of this user's position, expressed in terms of the index at time zero?"

### The Core Equations

**On deposit:**

```
scaledBalance = depositAmount / currentLiquidityIndex
```

**To read actual balance at any time:**

```
actualBalance = scaledBalance * currentLiquidityIndex
```

**On borrow:**

```
scaledDebt = borrowAmount / currentVariableBorrowIndex
```

**To read actual debt at any time:**

```
actualDebt = scaledDebt * currentVariableBorrowIndex
```

### Why This Works

The scaled balance is a **normalized** representation. By dividing out the index at deposit time, you get a number that, when multiplied by *any future index*, gives the correct balance including all interest accrued between those two points.

This works because the index is a cumulative multiplier. If the index was `1.05` when you deposited and is now `1.10`:

```
actualBalance = (amount / 1.05) * 1.10 = amount * (1.10 / 1.05) = amount * 1.0476...
```

You earned approximately 4.76% interest, which is exactly the interest that accrued between those two index values.

### Numerical Example

Let's trace through a concrete scenario.

**Step 1: Alice deposits 1000 USDC**

The reserve just launched, so `liquidityIndex = 1.0` (1e27 in ray).

```
Alice's scaledBalance = 1000 / 1.0 = 1000
```

Stored in contract: `balances[Alice] = 1000` (in scaled units)

**Step 2: Time passes, interest accrues**

Borrowers are paying interest. The `liquidityIndex` has grown to `1.03`.

Alice hasn't interacted with the protocol at all. Her stored scaled balance is still `1000`. But if she calls `balanceOf(Alice)`:

```
actualBalance = 1000 * 1.03 = 1030 USDC
```

Alice has earned 30 USDC in interest without a single transaction.

**Step 3: Bob deposits 500 USDC**

The `liquidityIndex` is now `1.03`.

```
Bob's scaledBalance = 500 / 1.03 = 485.44 (approximately)
```

Stored in contract: `balances[Bob] = 485.44` (in scaled units)

**Step 4: More time passes**

The `liquidityIndex` grows to `1.06`.

Alice's balance:
```
1000 * 1.06 = 1060 USDC
```

Bob's balance:
```
485.44 * 1.06 = 514.57 USDC
```

Alice earned 60 USDC total (6% on her original 1000). Bob earned 14.57 USDC (about 2.91% on his 500, reflecting the shorter time he has been supplying).

---

## Why This Design Works

The elegance of the index-and-scaled-balance pattern comes down to a single insight: **you only need to update one number (the index) to effectively update every user's balance simultaneously**.

Here is what this gives you:

1. **O(1) state updates**: Updating the index is one storage write, regardless of whether there are 10 users or 10 million users.

2. **O(1) balance queries**: Computing any user's balance is a single multiplication: `scaledBalance * index`. No iteration, no historical lookups.

3. **No "stale balance" problem**: Even if a user never interacts with the protocol for months, their balance is always accurate when queried, because the index has been growing with every interaction by *any* user.

4. **Composability**: Because `balanceOf()` returns the current actual balance, aTokens compose naturally with other DeFi protocols that read ERC-20 balances.

5. **Correctness under concurrent deposits**: When multiple users deposit at different times, the scaled balance system handles them all correctly. Each user's scaled balance "locks in" the index at their deposit time, and the ratio between indexes handles the rest.

---

## The `updateState()` Function: A Complete Walk-Through

`updateState()` is the heartbeat of every reserve. It is called at the beginning of virtually every operation: `supply()`, `withdraw()`, `borrow()`, `repay()`, `liquidationCall()`, `flashLoan()`, and more. Here is what it does, step by step:

```solidity
function updateState(
    DataTypes.ReserveData storage reserve,
    DataTypes.ReserveCache memory reserveCache
) internal {
    // Step 1: Update indexes
    bool isUpdated = _updateIndexes(reserve, reserveCache);

    // Step 2: Accrue interest to treasury
    if (isUpdated) {
        _accrueToTreasury(reserve, reserveCache);
    }
}
```

### Step 1: Update Indexes

As described above, `_updateIndexes()` computes the new liquidity index and variable borrow index based on the current rates and the time elapsed since the last update. If the last update was in the same block, it short-circuits and returns `false`.

### Step 2: Accrue to Treasury

After updating the indexes, the protocol mints a portion of the accrued interest to the Aave treasury. This is how the protocol earns revenue.

The `_accrueToTreasury()` function computes how much total interest was generated by borrowers since the last update and how much of that interest is captured by the reserve factor:

```solidity
function _accrueToTreasury(
    DataTypes.ReserveData storage reserve,
    DataTypes.ReserveCache memory reserveCache
) internal {
    uint256 prevTotalVariableDebt = reserveCache.currScaledVariableDebt.rayMul(
        reserveCache.currVariableBorrowIndex
    );

    uint256 currTotalVariableDebt = reserveCache.currScaledVariableDebt.rayMul(
        reserve.variableBorrowIndex
    );

    // Total debt increase = new debt - old debt
    uint256 totalDebtAccrued = currTotalVariableDebt - prevTotalVariableDebt;

    // Treasury gets reserveFactor% of all interest
    uint256 amountToMint = totalDebtAccrued.percentMul(
        reserveCache.reserveFactor
    );

    if (amountToMint != 0) {
        reserve.accruedToTreasury += amountToMint.rayDiv(
            reserve.liquidityIndex
        ).toUint128();
    }
}
```

Notice that `accruedToTreasury` is stored in **scaled units** (divided by the liquidity index), consistent with how all balances are stored in the system.

### The Full Sequence

Putting it all together, here is the timeline of a single `supply()` call:

1. User calls `Pool.supply(USDC, 1000, onBehalfOf, referralCode)`
2. Pool calls `reserve.updateState()`:
   - Compute time elapsed since last update
   - Calculate new `liquidityIndex` (linear interest)
   - Calculate new `variableBorrowIndex` (compound interest)
   - Compute treasury accrual and add to `accruedToTreasury`
   - Write updated indexes and timestamp to storage
3. Pool transfers 1000 USDC from user to the aToken contract
4. Pool calls `aToken.mint()` with scaled amount = `1000 / newLiquidityIndex`
5. Interest rates are recalculated based on the new utilization

Every operation follows this same pattern: update state first, then act.

---

## Full Numerical Walkthrough

Let's work through a complete example with exact numbers to cement the concept.

### Setup

- Reserve: USDC
- Reserve factor: 10%
- Starting liquidity index: `1.0` (1e27 ray)
- Starting variable borrow index: `1.0`

### T=0: Alice Supplies 1000 USDC

```
liquidityIndex = 1.000000
Alice deposits 1000 USDC
scaledBalance(Alice) = 1000 / 1.000000 = 1000.00
```

| User  | Scaled Balance | Actual Balance |
|-------|---------------|----------------|
| Alice | 1000.00       | 1000.00        |

### T=1 (some time later): Index grows

Borrowers have been paying interest. The liquidity index has grown to `1.05`.

```
liquidityIndex = 1.050000
```

No one has interacted, but if we query balances:

| User  | Scaled Balance | Actual Balance         |
|-------|---------------|------------------------|
| Alice | 1000.00       | 1000.00 * 1.05 = 1050.00 |

Alice has earned 50 USDC.

### T=1: Bob Supplies 2000 USDC

Bob deposits while the index is `1.05`:

```
scaledBalance(Bob) = 2000 / 1.05 = 1904.76
```

| User  | Scaled Balance | Actual Balance         |
|-------|---------------|------------------------|
| Alice | 1000.00       | 1000.00 * 1.05 = 1050.00 |
| Bob   | 1904.76       | 1904.76 * 1.05 = 2000.00 |

The scaled total supply is `2904.76`. The actual total supply is `3050.00`.

### T=2 (more time passes): Index grows to 1.10

```
liquidityIndex = 1.100000
```

| User  | Scaled Balance | Actual Balance            |
|-------|---------------|---------------------------|
| Alice | 1000.00       | 1000.00 * 1.10 = 1100.00  |
| Bob   | 1904.76       | 1904.76 * 1.10 = 2095.24  |

Alice's total interest earned: 100 USDC (10% on her original 1000).
Bob's total interest earned: 95.24 USDC (about 4.76% on his original 2000, reflecting his later entry).

Total actual supply: `3195.24`.

### T=2: Alice Withdraws 500 USDC

When Alice withdraws, the protocol burns the equivalent scaled amount:

```
scaledAmountToBurn = 500 / 1.10 = 454.55
```

Alice's new scaled balance:

```
1000.00 - 454.55 = 545.45
```

Alice's actual remaining balance:

```
545.45 * 1.10 = 600.00 USDC
```

Alice receives 500 USDC transferred to her wallet. She still has 600 USDC earning interest in the protocol.

### T=3: Index grows to 1.15

| User  | Scaled Balance | Actual Balance            |
|-------|---------------|---------------------------|
| Alice | 545.45        | 545.45 * 1.15 = 627.27    |
| Bob   | 1904.76       | 1904.76 * 1.15 = 2190.48  |

The system continues to work perfectly. Alice's remaining balance grows at the same rate as everyone else's, and the only values that ever change in storage are the reserve's index and timestamp.

---

## Summary

The index-and-scaled-balance pattern is the foundation of Aave V3's accounting system. Every other mechanism in the protocol --- aTokens, debt tokens, treasury accruals, liquidation calculations --- builds on this primitive.

**Key takeaways:**

- The **liquidity index** is a cumulative multiplier that tracks supply-side interest. It is updated via linear interest on every reserve interaction.
- The **variable borrow index** is the borrower equivalent, updated via compound interest (Taylor expansion approximation).
- **Scaled balances** are user balances divided by the index at the time of deposit/borrow. They are the only values stored in contract state.
- **Actual balances** are computed on the fly: `scaledBalance * currentIndex`.
- **`updateState()`** is called at the start of every operation. It updates both indexes and accrues treasury revenue.
- This design achieves O(1) cost for interest accrual regardless of the number of users.

In the next chapter, we will see how aTokens wrap this scaled balance system into an ERC-20 interface that makes interest-bearing deposits feel like holding a normal token.
