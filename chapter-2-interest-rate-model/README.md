# Chapter 2: Aave V3 Interest Rate Model

## Overview

Lending protocols need a mechanism to balance supply and demand for each asset. If there is plenty of available liquidity and little borrowing, interest rates should be low to encourage borrowing. If almost all supplied liquidity is being borrowed, rates should spike to incentivize new supply and encourage borrowers to repay.

Aave V3 achieves this with a **utilization-based variable interest rate model**. The borrow rate is a function of how much of the supplied liquidity is currently being borrowed. The supply rate is then derived from the borrow rate. Both rates update continuously — every time someone supplies, borrows, repays, or withdraws, the rates are recalculated.

This chapter covers the math behind the rate model, the Solidity implementation, and a worked numerical example.

<video src="../animations/final/interest_rate_curve.webm" controls autoplay loop muted playsinline style="width:100%;max-width:800px;border-radius:8px;margin:20px 0"></video>

## Utilization Rate

The **utilization rate** is the single most important variable in the interest rate model. It measures what fraction of the available liquidity is currently being borrowed.

```
            totalDebt
U = ─────────────────────────
     totalSupply + totalDebt
```

More precisely, in Aave's implementation:

```
         totalVariableDebt + totalStableDebt
U = ──────────────────────────────────────────────
     totalATokenSupply + totalVariableDebt + totalStableDebt
```

Wait — why is `totalDebt` in both the numerator and denominator? Because `totalATokenSupply` already represents the underlying balance held by the aToken contract (which is the supplied liquidity minus what has been borrowed), while `totalDebt` represents the amount that has been lent out. Together, they sum to the total capital in the system.

Actually, let us be more precise. In Aave V3's implementation with virtual accounting, the utilization is calculated as:

```
         totalDebt
U = ─────────────────────────────
     virtualUnderlyingBalance + totalDebt
```

Where `virtualUnderlyingBalance` is the protocol's internal accounting of the underlying asset held by the aToken contract, and `totalDebt` is the sum of all outstanding borrows (variable + stable).

When `U = 0`, no one is borrowing — all supplied liquidity sits idle. When `U = 1` (100%), every last unit of supplied liquidity has been borrowed out. In practice, utilization near 100% is dangerous because suppliers cannot withdraw (there is no liquidity left in the pool).

## The Kink Model

<video src="../animations/final/utilization_shift.webm" controls autoplay loop muted playsinline style="width:100%;max-width:800px;border-radius:8px;margin:20px 0"></video>

Aave uses a **piecewise linear** interest rate model with a "kink" — a point where the slope of the rate curve changes dramatically. In Aave's terminology, this kink point is called the **optimal utilization ratio** (`OPTIMAL_USAGE_RATIO`).

The intuition: below optimal utilization, the protocol wants to gently encourage borrowing, so rates increase slowly. Above optimal utilization, the protocol wants to aggressively discourage further borrowing and incentivize repayment, so rates increase steeply.

The variable borrow rate formula is:

**When U <= U_optimal:**

```
borrowRate = baseVariableBorrowRate + (U / U_optimal) * variableRateSlope1
```

**When U > U_optimal:**

```
borrowRate = baseVariableBorrowRate + variableRateSlope1 + ((U - U_optimal) / (1 - U_optimal)) * variableRateSlope2
```

Where:
- `baseVariableBorrowRate` — The minimum borrow rate when utilization is zero
- `variableRateSlope1` — The rate of increase in the borrow rate below optimal utilization
- `variableRateSlope2` — The rate of increase above optimal utilization (typically much steeper)
- `U_optimal` — The target utilization ratio (typically 80-90% for stablecoins, 45-65% for volatile assets)

Below the kink, the rate curve is a gentle slope. The moment utilization crosses `U_optimal`, the slope changes to `variableRateSlope2`, which is typically 10-100x steeper than `variableRateSlope1`. This creates a strong economic incentive to keep utilization near or below the optimal point.

## Supply Rate Derivation

Suppliers earn interest that comes from borrowers paying interest. But not all of the interest paid by borrowers goes to suppliers — the protocol takes a cut called the **reserve factor**.

The supply rate formula is:

```
supplyRate = borrowRate * U * (1 - reserveFactor)
```

Breaking this down:
- `borrowRate * U` — Only the borrowed portion of the pool generates interest. If utilization is 50%, only half the supplied capital is earning borrow interest.
- `(1 - reserveFactor)` — The protocol takes `reserveFactor` fraction of the interest as revenue (sent to the treasury). The rest goes to suppliers.

For example, if the borrow rate is 5%, utilization is 80%, and the reserve factor is 10%:

```
supplyRate = 5% * 80% * (1 - 10%) = 5% * 0.8 * 0.9 = 3.6%
```

This means suppliers earn 3.6% APY, borrowers pay 5% APY, and the 1.4% difference goes to the protocol treasury (0.4% because not all capital is utilized, and 0.4% as the reserve factor cut, totaling the difference).

The supply rate is always lower than the borrow rate for two reasons:
1. Not all supplied capital is borrowed (utilization < 100%)
2. The protocol takes a cut (reserve factor > 0%)

## Ray Math (1e27 Precision)

Before we look at the Solidity implementation, we need to understand Aave's fixed-point math system. Solidity has no native floating-point numbers, so Aave uses fixed-point integers with very high precision.

Aave defines two precision standards:

| Unit | Precision | Value of 1.0 | Used For |
|------|-----------|---------------|----------|
| **Wad** | 18 decimals | `1e18` | Token amounts, general math |
| **Ray** | 27 decimals | `1e27` | Interest rates, indexes |

Why 27 decimals? Interest rates can be very small (fractions of a percent), and they compound over small time intervals (seconds). Using 27 decimals provides enough precision to avoid rounding errors that would accumulate over time.

The `WadRayMath` library provides the core arithmetic:

```solidity
library WadRayMath {
    uint256 internal constant WAD = 1e18;
    uint256 internal constant RAY = 1e27;
    uint256 internal constant HALF_WAD = 0.5e18;
    uint256 internal constant HALF_RAY = 0.5e27;
    uint256 internal constant WAD_RAY_RATIO = 1e9;

    // Multiplies two ray values, rounding half up
    function rayMul(uint256 a, uint256 b) internal pure returns (uint256 c) {
        assembly {
            // Check for overflow
            if iszero(or(iszero(b), iszero(gt(a, div(sub(not(0), HALF_RAY), b))))) {
                revert(0, 0)
            }
            c := div(add(mul(a, b), HALF_RAY), RAY)
        }
    }

    // Divides two ray values, rounding half up
    function rayDiv(uint256 a, uint256 b) internal pure returns (uint256 c) {
        assembly {
            if or(iszero(b), iszero(iszero(gt(a, div(sub(not(0), div(b, 2)), RAY))))) {
                revert(0, 0)
            }
            c := div(add(mul(a, RAY), div(b, 2)), b)
        }
    }

    // Convert wad to ray (multiply by 1e9)
    function wadToRay(uint256 a) internal pure returns (uint256 b) {
        assembly {
            b := mul(a, WAD_RAY_RATIO)
            if iszero(eq(div(b, WAD_RAY_RATIO), a)) {
                revert(0, 0)
            }
        }
    }

    // Convert ray to wad (divide by 1e9, rounding half up)
    function rayToWad(uint256 a) internal pure returns (uint256 b) {
        assembly {
            b := div(a, WAD_RAY_RATIO)
            let remainder := mod(a, WAD_RAY_RATIO)
            if iszero(lt(remainder, div(WAD_RAY_RATIO, 2))) {
                b := add(b, 1)
            }
        }
    }
}
```

The key operations:
- **`rayMul(a, b)`** — Multiplies two ray-denominated numbers: `(a * b + HALF_RAY) / RAY`. The `HALF_RAY` provides rounding to the nearest integer.
- **`rayDiv(a, b)`** — Divides two ray-denominated numbers: `(a * RAY + b/2) / b`.
- **`wadToRay(a)`** — Converts from wad to ray by multiplying by `1e9`.
- **`rayToWad(a)`** — Converts from ray to wad by dividing by `1e9`.

When you see interest rates stored as `uint128` values in `ReserveData`, they are in **ray**. A 5% annual rate is stored as `0.05 * 1e27 = 5e25`.

The assembly implementations avoid Solidity's built-in overflow checks (which are redundant here since the functions do their own overflow checking) for gas optimization.

## DefaultReserveInterestRateStrategyV2

Each reserve has an interest rate strategy contract that implements the rate calculation. In Aave V3, the default strategy is `DefaultReserveInterestRateStrategyV2`.

The key function is `calculateInterestRates()`, which takes the current state of a reserve and returns the new supply, stable borrow, and variable borrow rates.

Here is the simplified flow:

```solidity
function calculateInterestRates(
    DataTypes.CalculateInterestRatesParams memory params
) public view override returns (uint256, uint256, uint256) {

    // 1. Calculate utilization
    uint256 totalDebt = params.totalStableDebt + params.totalVariableDebt;

    uint256 currentUtilizationRate;
    uint256 availableLiquidity;

    if (totalDebt != 0) {
        availableLiquidity =
            params.virtualUnderlyingBalance +
            params.liquidityAdded -
            params.liquidityTaken;

        currentUtilizationRate = totalDebt.rayDiv(
            availableLiquidity + totalDebt
        );
    }

    // 2. Calculate variable borrow rate using the kink model
    InterestRateData memory rateData = _interestRateData[params.reserve];
    uint256 currentVariableBorrowRate = _calcVariableBorrowRate(
        rateData,
        currentUtilizationRate
    );

    // 3. Calculate supply rate from borrow rate
    uint256 currentLiquidityRate = _getOverallBorrowRate(
        params.totalStableDebt,
        params.totalVariableDebt,
        currentVariableBorrowRate,
        params.averageStableBorrowRate
    ).rayMul(currentUtilizationRate).percentMul(
        PercentageMath.PERCENTAGE_FACTOR - params.reserveFactor
    );

    return (currentLiquidityRate, 0, currentVariableBorrowRate);
}
```

The `_calcVariableBorrowRate` function implements the piecewise formula we discussed:

```solidity
function _calcVariableBorrowRate(
    InterestRateData memory rateData,
    uint256 currentUtilizationRate
) internal pure returns (uint256) {
    if (currentUtilizationRate > rateData.optimalUsageRatio) {
        // Above optimal: steep slope
        uint256 excessBorrowUsageRatio =
            (currentUtilizationRate - rateData.optimalUsageRatio).rayDiv(
                WadRayMath.RAY - rateData.optimalUsageRatio
            );

        return rateData.baseVariableBorrowRate +
            rateData.variableRateSlope1 +
            rateData.variableRateSlope2.rayMul(excessBorrowUsageRatio);
    } else {
        // Below optimal: gentle slope
        return rateData.baseVariableBorrowRate +
            currentUtilizationRate.rayDiv(rateData.optimalUsageRatio).rayMul(
                rateData.variableRateSlope1
            );
    }
}
```

Let us trace through the below-optimal case:

1. `currentUtilizationRate.rayDiv(rateData.optimalUsageRatio)` — This computes `U / U_optimal`, giving a value between 0 and 1 (in ray).
2. The result is `rayMul`'d with `variableRateSlope1` — This gives the portion of slope1 proportional to how close we are to optimal.
3. `baseVariableBorrowRate` is added — This is the floor rate.

For the above-optimal case:

1. `excessBorrowUsageRatio` computes `(U - U_optimal) / (1 - U_optimal)` — How far past optimal we are, normalized to 0-1.
2. This is `rayMul`'d with `variableRateSlope2` — The steep slope kicks in.
3. Both `baseVariableBorrowRate` and the full `variableRateSlope1` are added — You get the base, the full gentle slope, plus the excess steep slope.

### The InterestRateData Struct

The strategy stores its parameters per reserve in a gas-optimized struct:

```solidity
struct InterestRateData {
    uint16 optimalUsageRatio;      // in bps (e.g., 9000 = 90%)
    uint32 baseVariableBorrowRate; // in bps (e.g., 0 = 0%)
    uint32 variableRateSlope1;     // in bps (e.g., 400 = 4%)
    uint32 variableRateSlope2;     // in bps (e.g., 6000 = 60%)
}
```

Note that the parameters are stored as `uint16`/`uint32` in basis points for storage efficiency, but are converted to ray (1e27) when used in calculations. This conversion is done internally by the strategy — the `_calcVariableBorrowRate` function works entirely in ray precision.

## Stable Rate (Legacy)

Aave V2 and early V3 deployments included a **stable borrow rate** feature. The idea: when a user borrows at a stable rate, their rate is "locked in" at the time of borrowing. Even if market conditions change, their rate remains fixed.

This was appealing for borrowers who wanted predictability, but it created problems:

**How it worked:**
- When a user borrows at a stable rate, the current stable rate is recorded as their personal rate.
- Their debt accrues at this personal rate, not the market rate.
- The protocol tracks an overall `averageStableBorrowRate` across all stable borrowers.
- If a user's rate becomes significantly out of line with the current market rate (much lower than what it should be), anyone can call `rebalanceStableBorrowRate()` to reset that user's rate to the current market rate.

**Why it was deprecated:**
- The rebalancing mechanism added complexity and potential for manipulation.
- Stable rates created an asymmetry — borrowers could lock in low rates during favorable conditions and there was limited ability to adjust.
- The feature added gas overhead and code complexity.
- In newer V3 deployments, `StableDebtToken` is still deployed (for interface compatibility) but stable rate borrowing is disabled in the reserve configuration bitmap.

In the `calculateInterestRates` function shown above, you can see the stable borrow rate return value is hardcoded to `0`. The function signature keeps it for backward compatibility.

For the remainder of this book, we focus on variable rate borrowing unless stated otherwise.

## Practical Example

Let us work through a concrete example using parameters from a real USDC deployment on Ethereum mainnet.

### Parameters

Typical USDC reserve parameters:

| Parameter | Value | In Ray (1e27) |
|-----------|-------|---------------|
| Optimal Usage Ratio | 90% | `0.9e27` |
| Base Variable Borrow Rate | 0% | `0` |
| Variable Rate Slope1 | 3.5% | `3.5e25` |
| Variable Rate Slope2 | 60% | `6e26` |
| Reserve Factor | 10% | N/A (in bps) |

### Scenario 1: Utilization at 60% (Below Optimal)

With 60% utilization, we are below the 90% optimal point. We use the first formula:

```
borrowRate = baseRate + (U / U_optimal) * slope1
borrowRate = 0% + (60% / 90%) * 3.5%
borrowRate = 0% + 0.6667 * 3.5%
borrowRate = 2.33%
```

Now the supply rate:

```
supplyRate = borrowRate * U * (1 - reserveFactor)
supplyRate = 2.33% * 60% * (1 - 10%)
supplyRate = 2.33% * 0.6 * 0.9
supplyRate = 1.26%
```

At 60% utilization, borrowers pay about 2.33% APY and suppliers earn about 1.26% APY.

### Scenario 2: Utilization at 90% (At the Kink)

At exactly the optimal point:

```
borrowRate = 0% + (90% / 90%) * 3.5%
borrowRate = 0% + 1.0 * 3.5%
borrowRate = 3.5%
```

Supply rate:

```
supplyRate = 3.5% * 90% * 90%
supplyRate = 2.835%
```

At the kink, borrowers pay 3.5% and suppliers earn about 2.84%.

### Scenario 3: Utilization at 95% (Above Optimal)

Now we are above optimal, so we use the second formula:

```
borrowRate = baseRate + slope1 + ((U - U_optimal) / (1 - U_optimal)) * slope2
borrowRate = 0% + 3.5% + ((95% - 90%) / (100% - 90%)) * 60%
borrowRate = 3.5% + (5% / 10%) * 60%
borrowRate = 3.5% + 0.5 * 60%
borrowRate = 3.5% + 30%
borrowRate = 33.5%
```

Supply rate:

```
supplyRate = 33.5% * 95% * 90%
supplyRate = 28.64%
```

The difference is dramatic. Going from 90% to 95% utilization (just 5 percentage points) caused the borrow rate to jump from 3.5% to 33.5% — nearly a **10x increase**. This is the kink model doing its job: aggressively discouraging utilization above the target.

### Scenario 4: Utilization at 100%

At maximum utilization:

```
borrowRate = 0% + 3.5% + ((100% - 90%) / (100% - 90%)) * 60%
borrowRate = 3.5% + 1.0 * 60%
borrowRate = 63.5%
```

Supply rate:

```
supplyRate = 63.5% * 100% * 90%
supplyRate = 57.15%
```

At 100% utilization, borrowers pay 63.5%. This is an extreme rate designed to make borrowing untenable and rapidly attract new supply.

### The Math in Ray

Let us verify Scenario 3 using ray arithmetic, as the contract would compute it.

```
U               = 0.95e27  (950000000000000000000000000)
U_optimal       = 0.9e27   (900000000000000000000000000)
baseRate        = 0
slope1          = 0.035e27 (35000000000000000000000000)
slope2          = 0.6e27   (600000000000000000000000000)

excessRatio = rayDiv(U - U_optimal, RAY - U_optimal)
            = rayDiv(0.05e27, 0.1e27)
            = (0.05e27 * 1e27 + 0.05e27) / 0.1e27
            = 0.5e27

borrowRate  = 0 + 0.035e27 + rayMul(0.6e27, 0.5e27)
            = 0.035e27 + (0.6e27 * 0.5e27 + 0.5e27) / 1e27
            = 0.035e27 + 0.3e27
            = 0.335e27

This is 33.5%, confirming our manual calculation.
```

### When Are Rates Recalculated?

Rates are not continuously updated like a feed. They are recalculated on every state-changing operation:

- `supply()` — Liquidity increases, utilization drops, rates decrease
- `withdraw()` — Liquidity decreases, utilization rises, rates increase
- `borrow()` — Debt increases, utilization rises, rates increase
- `repay()` — Debt decreases, utilization drops, rates decrease
- `liquidationCall()` — Debt decreases and collateral is seized, rates change

Inside the Pool's logic libraries, after executing the core operation, the function calls `reserve.updateInterestRatesAndVirtualBalance()`, which invokes the interest rate strategy's `calculateInterestRates()` and stores the new rates in `ReserveData`.

```solidity
// Inside ReserveLogic.sol (simplified)
function updateInterestRatesAndVirtualBalance(
    DataTypes.ReserveData storage reserve,
    DataTypes.ReserveCache memory reserveCache,
    address reserveAddress,
    uint256 liquidityAdded,
    uint256 liquidityTaken
) internal {
    // Call the strategy to get new rates
    (uint256 newLiquidityRate, , uint256 newVariableBorrowRate) =
        IReserveInterestRateStrategy(reserve.interestRateStrategyAddress)
            .calculateInterestRates(
                DataTypes.CalculateInterestRatesParams({
                    // ... pass current state
                    liquidityAdded: liquidityAdded,
                    liquidityTaken: liquidityTaken,
                    totalStableDebt: reserveCache.nextTotalStableDebt,
                    totalVariableDebt: reserveCache.nextTotalVariableDebt,
                    averageStableBorrowRate: reserveCache.nextAvgStableBorrowRate,
                    reserveFactor: reserveCache.reserveFactor,
                    reserve: reserveAddress,
                    virtualUnderlyingBalance: reserve.virtualUnderlyingBalance
                })
            );

    // Store the new rates
    reserve.currentLiquidityRate = newLiquidityRate.toUint128();
    reserve.currentVariableBorrowRate = newVariableBorrowRate.toUint128();
}
```

This means the rates stored in `ReserveData` are always the rates computed after the last state-changing transaction. Between transactions, rates do not change — but the **indexes** that track accumulated interest are updated based on the stored rates and elapsed time. We cover indexes in Chapter 3.

## Summary

Aave V3's interest rate model is a utilization-based kink model with four parameters per reserve: the optimal utilization ratio, a base rate, and two slopes (gentle below the kink, steep above). The supply rate is derived from the borrow rate, scaled by utilization and reduced by the reserve factor.

All rate math is done in ray (1e27) precision using the `WadRayMath` library. Rates are recalculated on every state-changing operation and stored in the reserve's data structure.

The kink model creates a powerful economic feedback loop: when utilization is too high, borrow rates spike, discouraging new borrows and encouraging repayment. When utilization is too low, rates fall, encouraging borrowing. This mechanism keeps each reserve's utilization hovering near the optimal target.

In the next chapter, we examine how these instantaneous rates translate into actual interest accrual through the **liquidity index** and **variable borrow index** — the mechanism by which balances grow over time.
