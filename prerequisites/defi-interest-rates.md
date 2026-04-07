# DeFi Interest Rate Models

In traditional finance, interest rates are set by central banks, negotiated between parties, or determined by bond markets. In DeFi lending protocols, interest rates are **algorithmic** --- they are computed by a smart contract based on the current state of the pool.

Aave V3 uses a well-known model called the **kink model** (or piecewise linear model) to set borrow and supply rates. This prerequisite explains how that model works from first principles.

---

## The Core Idea: Utilization Rate

Every lending pool has two quantities:

- **Total supplied**: the amount of capital deposited by lenders
- **Total borrowed**: the amount of capital currently lent out to borrowers

The **utilization rate** is the ratio of borrowed capital to total available capital:

```
U = Total Borrowed / Total Supplied
```

- When U = 0%, no one is borrowing. All capital is idle.
- When U = 100%, every deposited token has been borrowed. No liquidity remains for withdrawals.

The utilization rate is the single most important input to the interest rate model. It reflects supply and demand: high utilization means borrowing demand outstrips available liquidity.

---

## Why Rates Must Respond to Utilization

Consider what happens if rates were fixed:

- If the borrow rate is too low, everyone borrows, utilization hits 100%, and depositors cannot withdraw (no liquidity).
- If the borrow rate is too high, no one borrows, utilization is 0%, and depositors earn nothing.

An algorithmic rate model solves this by creating a **feedback loop**:

1. High utilization -> rates increase -> borrowing becomes expensive -> some borrowers repay -> utilization decreases
2. Low utilization -> rates decrease -> borrowing becomes cheap -> new borrowers arrive -> utilization increases

The system self-corrects toward an equilibrium utilization rate.

---

## The Linear Model (Simplified)

The simplest interest rate model is a straight line:

```
Borrow Rate = Base Rate + (Utilization * Slope)
```

For example, with a base rate of 2% and a slope of 20%:

| Utilization | Borrow Rate |
|------------|-------------|
| 0% | 2% |
| 25% | 7% |
| 50% | 12% |
| 75% | 17% |
| 100% | 22% |

This works, but it has a problem: the rate at 90% utilization (20%) is not much higher than at 80% (18%). There is no urgency signal when the pool is running dangerously low on liquidity. Depositors who want to withdraw at 95% utilization face the same moderate rate incentive as at 70%.

---

## The Kink Model (Piecewise Linear)

The **kink model** fixes this by using two different slopes:

- **Below optimal utilization**: a gentle slope (normal market conditions)
- **Above optimal utilization**: a steep slope (emergency conditions --- liquidity is scarce)

The "optimal utilization" is the **kink point** where the slope changes.

```
If U <= U_optimal:
    Borrow Rate = Base Rate + (U / U_optimal) * Slope1

If U > U_optimal:
    Borrow Rate = Base Rate + Slope1 + ((U - U_optimal) / (1 - U_optimal)) * Slope2
```

Where:
- `Base Rate` is the minimum borrow rate (the y-intercept)
- `U_optimal` is the target utilization (the kink point)
- `Slope1` is the rate of increase below the kink
- `Slope2` is the rate of increase above the kink (much steeper)

### Example Parameters

Let's use realistic values:
- Base Rate = 0%
- U_optimal = 80%
- Slope1 = 4%
- Slope2 = 75%

| Utilization | Borrow Rate | Explanation |
|------------|-------------|-------------|
| 0% | 0% | No borrowing, no rate |
| 40% | 2% | Half of optimal, half of Slope1 |
| 80% | 4% | At the kink point |
| 85% | 4% + 18.75% = 22.75% | Just 5% past optimal, rate jumps |
| 90% | 4% + 37.5% = 41.5% | Rates climbing fast |
| 95% | 4% + 56.25% = 60.25% | Near-crisis rates |
| 100% | 4% + 75% = 79% | Maximum rate |

The sharp increase past 80% creates a strong incentive to bring utilization back below optimal. Borrowers at 90%+ utilization face punishing rates and are motivated to repay. Meanwhile, the high supply rate attracts new depositors.

---

## Visualizing the Kink

```
Borrow Rate
    |
79% |                                                          *
    |                                                     *
    |                                                *
    |                                           *
    |                                      *
    |                                 *
    |                            *
 4% |                       *
    |                  *
    |             *
    |        *
    |   *
 0% *---------------------------------------------------
    0%        20%       40%       60%  80%  90%  100%
                                        ^
                                   U_optimal
                                   (the kink)
```

The "kink" is visible at 80% --- a sharp change in the slope of the curve.

---

## Supply Rate: Where Depositors Earn

Borrowers pay interest. That interest is distributed to depositors (suppliers). But not all of it --- the protocol takes a **reserve factor** cut.

The supply rate is derived from the borrow rate:

```
Supply Rate = Borrow Rate * Utilization * (1 - Reserve Factor)
```

Breaking this down:

- `Borrow Rate * Utilization`: the total interest paid by borrowers, spread across all supplied capital. If only 50% of the pool is borrowed, only 50% of the capital is generating interest.
- `(1 - Reserve Factor)`: the protocol keeps a fraction (typically 10-20%) as revenue. The rest goes to suppliers.

### Example

With a borrow rate of 4%, utilization of 80%, and a reserve factor of 10%:

```
Supply Rate = 4% * 0.80 * (1 - 0.10) = 4% * 0.80 * 0.90 = 2.88%
```

Suppliers earn less than borrowers pay because:
1. Not all capital is utilized (80% is, 20% sits idle)
2. The protocol takes a cut (10%)

---

## Why the Kink Point Matters

The choice of `U_optimal` reflects a protocol's philosophy:

- **Low U_optimal (e.g., 45%)**: Conservative. Prioritizes liquidity for withdrawals. Rates spike early. Common for volatile assets.
- **High U_optimal (e.g., 90%)**: Aggressive. Maximizes capital efficiency. Rates stay low longer. Common for stablecoins.

In Aave V3, different assets have different rate strategies:

| Asset Type | Typical U_optimal | Rationale |
|-----------|-------------------|-----------|
| Stablecoins (USDC, DAI) | 90% | Low volatility, predictable demand |
| Blue-chip (ETH, WBTC) | 80% | Moderate volatility |
| Long-tail assets | 45-65% | High volatility, less liquid |

This makes intuitive sense: stablecoins rarely see sudden withdrawal spikes, so the pool can safely operate at higher utilization. Volatile assets need more buffer.

---

## Variable vs. Stable Rates

Aave V3 offers two types of borrow rates:

- **Variable rate**: Changes continuously based on current utilization. This is the kink model described above.
- **Stable rate**: Locked in at the time of borrowing (with some conditions). Provides predictability for borrowers but comes at a premium.

The stable rate mechanism is more complex and is covered in detail in Chapter 2. For this prerequisite, focus on understanding the variable rate model --- it is the foundation.

---

## Putting It in Code

A simplified Solidity implementation of the kink model:

```solidity
function calculateBorrowRate(
    uint256 totalSupplied,
    uint256 totalBorrowed,
    uint256 optimalUtilization,  // in ray (1e27)
    uint256 baseRate,            // in ray
    uint256 slope1,              // in ray
    uint256 slope2               // in ray
) public pure returns (uint256) {
    if (totalSupplied == 0) return baseRate;

    uint256 utilization = (totalBorrowed * 1e27) / totalSupplied;

    if (utilization <= optimalUtilization) {
        return baseRate + (utilization * slope1) / optimalUtilization;
    } else {
        uint256 excessUtilization = utilization - optimalUtilization;
        uint256 maxExcess = 1e27 - optimalUtilization;
        return baseRate + slope1 + (excessUtilization * slope2) / maxExcess;
    }
}
```

Aave V3 uses **ray math** (27 decimal places) for precision. The actual implementation in `DefaultReserveInterestRateStrategy` follows this same structure but includes additional considerations for stable rate rebalancing.

---

## Summary

| Concept | Key Point |
|---------|-----------|
| Utilization rate | Borrowed / Supplied --- the key input |
| Feedback loop | High utilization raises rates, discouraging borrowing |
| Kink model | Two slopes --- gentle below optimal, steep above |
| Optimal utilization | The target utilization where the slope changes |
| Supply rate | Derived from borrow rate, adjusted for utilization and reserve factor |
| Asset-specific parameters | Different assets have different optimal utilization and slopes |

This model is the foundation for Chapter 2 (Interest Rate Model), where we examine Aave V3's actual implementation, including ray math, rate accumulation over time, and the stable rate mechanism.
