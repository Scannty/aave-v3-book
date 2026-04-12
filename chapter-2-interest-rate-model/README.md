# Chapter 2: The Interest Rate Model

## The Core Problem: Balancing a Two-Sided Market

A lending protocol is fundamentally a marketplace. On one side, suppliers want to earn yield on idle capital. On the other side, borrowers want access to capital and are willing to pay for it. The interest rate is the price that balances these two sides.

If rates are too low, borrowers flood in and drain the pool. Suppliers cannot withdraw because there is no liquidity left --- a crisis scenario. If rates are too high, no one borrows, suppliers earn nothing, and capital sits idle. The protocol needs a mechanism that automatically adjusts rates to keep supply and demand in equilibrium.

Aave V3 solves this with a **utilization-based interest rate model**. The interest rate is not set by governance or by an oracle --- it is a pure function of how much of the available liquidity is currently being borrowed. More borrowing means higher rates. Less borrowing means lower rates. The system is self-correcting.

<video src="../animations/final/interest_rate_curve.webm" controls autoplay loop muted playsinline style="width:100%;max-width:800px;border-radius:8px;margin:20px 0"></video>

## Utilization: The One Number That Drives Everything

The **utilization rate** measures what fraction of the pool's capital is currently lent out:

```
            totalDebt
U = ─────────────────────────────
     availableLiquidity + totalDebt
```

The denominator represents the total capital in the system: the liquidity sitting in the pool plus the liquidity that has been borrowed out. The numerator is just the borrowed portion.

- **U = 0%** means no one is borrowing. All capital is idle.
- **U = 50%** means half the pool has been lent out.
- **U = 100%** means every last token has been borrowed. Suppliers cannot withdraw --- there is nothing left in the pool.

Utilization near 100% is dangerous. It creates a liquidity crisis where suppliers are trapped. The interest rate model's primary job is to prevent this from happening.

## The Kink Model: Incentive Design Through a Rate Curve

Aave does not use a simple linear relationship between utilization and interest rates. Instead, it uses a **piecewise linear model with a kink** --- a point where the slope of the rate curve changes dramatically.

<video src="../animations/final/utilization_shift.webm" controls autoplay loop muted playsinline style="width:100%;max-width:800px;border-radius:8px;margin:20px 0"></video>

The kink point is called the **optimal utilization ratio** (typically 80--90% for stablecoins, 45--65% for volatile assets). Think of it as the protocol's target: "We want utilization to hover around this level."

### Below the kink: gentle encouragement

When utilization is below the target, the protocol is comfortable. There is plenty of liquidity for suppliers to withdraw. Rates increase slowly to gently encourage more borrowing and make the idle capital productive.

The formula is:

```
borrowRate = baseRate + (U / U_optimal) * slope1
```

The rate climbs linearly from the base rate toward `baseRate + slope1` as utilization approaches the target.

### Above the kink: aggressive discouragement

When utilization crosses the target, the protocol gets aggressive. Rates start climbing steeply --- often 10x to 100x faster than below the kink. This serves two purposes simultaneously:

1. **Discourage new borrowing.** The cost of borrowing becomes painful, so fewer people take new loans.
2. **Incentivize new supply.** The high rates make supplying very attractive, drawing in new capital.

The formula is:

```
borrowRate = baseRate + slope1 + ((U - U_optimal) / (1 - U_optimal)) * slope2
```

Above the kink, you pay the full `slope1` *plus* a rapidly increasing portion of `slope2`. Since `slope2` is typically 15--75x larger than `slope1`, the rate curve bends sharply upward.

### Why a kink and not a smooth curve?

A smooth exponential curve would also work, but the piecewise linear model has practical advantages. It is simple to reason about (governance can clearly see the rate at any utilization level), cheap to compute on-chain (just addition, multiplication, and division), and easy to parameterize (four numbers control the entire curve).

## The Four Parameters That Define a Market

Each asset's interest rate curve is controlled by four parameters set by governance:

| Parameter | What It Controls | Typical Values |
|-----------|-----------------|----------------|
| `baseVariableBorrowRate` | The floor rate when no one is borrowing | 0% for most assets |
| `optimalUsageRatio` | The kink point (target utilization) | 80--90% for stablecoins, 45--65% for volatile assets |
| `variableRateSlope1` | How quickly rates rise below the kink | 3--7% for stablecoins, 3--8% for volatile assets |
| `variableRateSlope2` | How quickly rates rise above the kink | 60--300% for stablecoins, 80--300% for volatile assets |

These parameters encode a governance judgment about each asset: how liquid does the market need to be? How aggressively should the protocol defend against liquidity crises? A stablecoin like USDC might tolerate high utilization (90% optimal) with a moderate penalty slope, while a volatile asset like LINK might have a lower optimal (45%) with a steeper penalty.

The parameters are stored per reserve in the `DefaultReserveInterestRateStrategyV2` contract. They are set in basis points for storage efficiency but converted to ray (27-decimal fixed-point) for calculations.

## Supply Rate: Where Does Yield Come From?

Suppliers earn interest that comes directly from borrowers. But the supply rate is always lower than the borrow rate, for two reasons:

1. **Not all capital is borrowed.** If utilization is 80%, then 20% of the supplied capital is sitting idle, earning nothing. The interest from borrowers is spread across *all* suppliers, including those whose capital is not being used.

2. **The protocol takes a cut.** The **reserve factor** (typically 10--20%) is governance's fee. This portion of the interest goes to the Aave treasury rather than to suppliers.

The supply rate formula captures both effects:

```
supplyRate = borrowRate * utilization * (1 - reserveFactor)
```

Let's make this concrete. If borrowers are paying 5% APY, utilization is 80%, and the reserve factor is 10%:

```
supplyRate = 5% * 0.80 * 0.90 = 3.6%
```

Where does the remaining 1.4% go?

- **0.8% is the "idle capital" cost.** Twenty percent of supplied capital is not lent out, so that portion earns nothing. This dilutes the effective yield: 5% * 0.20 = 1.0% "lost" to idle capital, but since we are computing the rate on total supply, the math works out to 5% * 0.80 = 4.0% before the protocol cut.
- **0.4% is the protocol's revenue.** Ten percent of the interest that reaches suppliers (4.0% * 0.10 = 0.4%) is diverted to the treasury.

This creates a clean economic flow: borrowers pay interest, that interest is distributed to suppliers proportional to utilization, and the protocol skims a percentage off the top.

## Worked Example: USDC on Ethereum Mainnet

Let's trace through the full rate model with realistic parameters.

### Parameters

| Parameter | Value |
|-----------|-------|
| Optimal Usage Ratio | 90% |
| Base Variable Borrow Rate | 0% |
| Variable Rate Slope1 | 3.5% |
| Variable Rate Slope2 | 60% |
| Reserve Factor | 10% |

### Scenario 1: Utilization at 60% (comfortable territory)

We are well below the 90% kink. Rates are in the gentle zone.

```
borrowRate = 0% + (60% / 90%) * 3.5%
           = 0.667 * 3.5%
           = 2.33%

supplyRate = 2.33% * 60% * 90%
           = 1.26%
```

Borrowers pay 2.33%. Suppliers earn 1.26%. The market is relaxed.

### Scenario 2: Utilization at 90% (right at the kink)

```
borrowRate = 0% + (90% / 90%) * 3.5%
           = 1.0 * 3.5%
           = 3.5%

supplyRate = 3.5% * 90% * 90%
           = 2.84%
```

At the target, borrowers pay 3.5% and suppliers earn 2.84%. Still manageable.

### Scenario 3: Utilization at 95% (just 5% above the kink)

Now the steep slope kicks in:

```
borrowRate = 0% + 3.5% + ((95% - 90%) / (100% - 90%)) * 60%
           = 3.5% + (0.5) * 60%
           = 3.5% + 30%
           = 33.5%

supplyRate = 33.5% * 95% * 90%
           = 28.64%
```

Going from 90% to 95% utilization --- just 5 percentage points --- caused the borrow rate to **jump from 3.5% to 33.5%**. That is nearly a 10x increase. Meanwhile, suppliers are now earning 28.64%, which will attract new capital and push utilization back down.

This is the kink model doing its job.

### Scenario 4: Utilization at 100% (crisis territory)

```
borrowRate = 0% + 3.5% + ((100% - 90%) / (100% - 90%)) * 60%
           = 3.5% + 60%
           = 63.5%

supplyRate = 63.5% * 100% * 90%
           = 57.15%
```

At full utilization, borrowers are paying 63.5% APY. This rate is designed to be untenable --- no rational borrower will maintain a position at this cost for long. At the same time, 57.15% supply APY is a powerful magnet for new capital.

### The Full Picture

| Utilization | Borrow Rate | Supply Rate | Zone |
|-------------|-------------|-------------|------|
| 0% | 0.00% | 0.00% | No activity |
| 30% | 1.17% | 0.32% | Gentle slope |
| 60% | 2.33% | 1.26% | Gentle slope |
| 80% | 3.11% | 2.24% | Approaching kink |
| 90% | 3.50% | 2.84% | At the kink |
| 92% | 15.50% | 12.84% | Above kink --- rates jumping |
| 95% | 33.50% | 28.64% | Well above kink |
| 100% | 63.50% | 57.15% | Maximum pain |

The table tells the story. Below 90%, rates barely move. The moment utilization crosses 90%, rates explode. This discontinuity is the entire point of the kink design.

## A Brief Note on Precision: Ray Math

Solidity has no floating-point numbers, so Aave uses fixed-point integers with 27 decimal places, called **ray** notation. In ray, the number 1.0 is represented as `1e27` (1 followed by 27 zeros). A 5% interest rate is stored as `5e25`.

Why 27 decimals? Interest rates can be fractions of a percent, and they compound over small time intervals (seconds). High precision prevents rounding errors from accumulating over months and years.

The `WadRayMath` library provides `rayMul` and `rayDiv` operations --- essentially multiplication and division that account for the 27-decimal scaling factor. You will see these throughout the codebase, but the concept is straightforward: it is just fixed-point arithmetic with very high precision.

For reference, Aave also uses **wad** (18 decimals, matching most ERC-20 tokens) for token amounts. Ray is reserved for rates and indexes where extra precision matters.

## Stable Rate Borrowing (Deprecated)

Early versions of Aave offered **stable rate borrowing**, where a borrower could lock in a fixed rate at the time of borrowing. The appeal was predictability --- you knew what you would pay regardless of market conditions.

In practice, this feature proved problematic. Borrowers could lock in artificially low rates during favorable conditions, creating an asymmetry that disadvantaged suppliers. A "rebalancing" mechanism existed to reset egregiously stale rates, but it added complexity and potential for manipulation.

Newer Aave V3 deployments disable stable rate borrowing entirely. The `StableDebtToken` contract still exists for interface compatibility, but the feature is effectively retired. The `calculateInterestRates()` function returns 0 for the stable rate.

For the remainder of this book, we focus exclusively on variable rate borrowing.

## When Do Rates Update?

Rates are not continuously streamed like a price feed. They are **recalculated on every state-changing operation**:

- **`supply()`** --- Liquidity increases, utilization drops, rates decrease
- **`withdraw()`** --- Liquidity decreases, utilization rises, rates increase
- **`borrow()`** --- Debt increases, utilization rises, rates increase
- **`repay()`** --- Debt decreases, utilization drops, rates decrease
- **`liquidationCall()`** --- Debt is repaid and collateral is seized, rates change

After executing the core operation, the Pool calls `reserve.updateInterestRatesAndVirtualBalance()`, which invokes the interest rate strategy's `calculateInterestRates()` function and stores the new rates in `ReserveData`.

Between transactions, the stored rates are static. But the **indexes** (covered in Chapter 3) use these stored rates plus elapsed time to compute how much interest has accrued since the last update. So while rates only change on transactions, interest accrual is effectively continuous.

This design means that in periods of high activity, rates update frequently and track utilization closely. In quiet periods, rates may be stale by hours, but the index math ensures no interest is lost or miscounted.

## The Economic Feedback Loop

The kink model creates a self-correcting system:

1. **Utilization rises above target** --- Borrow rates spike, making borrowing expensive. Supply rates also spike, attracting new capital.
2. **Borrowers repay or get liquidated** --- Debt decreases, utilization falls.
3. **New suppliers enter** --- Available liquidity increases, utilization falls further.
4. **Utilization returns to target** --- Rates normalize.

The same loop works in reverse: if utilization drops too low, low supply rates cause some suppliers to withdraw and seek yield elsewhere, while low borrow rates attract new borrowers. Utilization drifts back up.

This is not a theoretical construct --- it plays out in real time across Aave's markets. During periods of market stress (when many users want to borrow stablecoins to cover positions), utilization spikes, rates skyrocket, and the protocol incentivizes the exact behavior needed to restore equilibrium.

## Summary

Aave V3's interest rate model is a utilization-based kink model with four parameters per asset. Below the optimal utilization target, rates climb gently to encourage productive use of capital. Above the target, rates spike dramatically to prevent liquidity crises and attract new supply.

The supply rate is derived from the borrow rate, reduced by two factors: the share of capital that sits idle (1 - utilization) and the protocol's revenue cut (reserve factor). This creates a clean economic flow from borrowers to suppliers, with the protocol extracting a sustainable fee.

The kink model is simple by design --- four numbers define the entire curve --- but it creates a powerful self-correcting feedback loop that keeps each market in equilibrium without any manual intervention.

In the next chapter, we examine how these instantaneous rates translate into actual interest accrual through **indexes** and **scaled balances** --- the mechanism that lets thousands of users earn interest without a single storage write per user.
