# Chapter 9: E-Mode (Efficiency Mode)

Here is a question that reveals a fundamental tension in lending protocol design: if you deposit $10,000 of USDC and want to borrow DAI, why should the protocol only let you borrow $7,700?

Both assets are USD stablecoins. Both are worth $1. The chance that USDC drops to $0.90 while DAI stays at $1.00 is vanishingly small. Yet under default risk parameters, the protocol forces you to leave $2,300 locked up as a safety buffer against a scenario that almost never happens. That is wasted capital.

Now consider a different case: you deposit $10,000 of ETH and want to borrow USDC. Here, the 20% buffer makes perfect sense --- ETH can drop 20% in a day. The collateral and debt are fundamentally different assets with uncorrelated risk profiles.

The problem is clear: a one-size-fits-all approach to risk parameters is either too conservative for correlated assets or too aggressive for uncorrelated ones. Aave V3 solves this with **E-Mode (Efficiency Mode)** --- a system that gives correlated asset pairs dramatically better borrowing terms.

<video src="../animations/final/emode_comparison.webm" controls autoplay loop muted playsinline style="width:100%;max-width:800px;border-radius:8px;margin:20px 0"></video>

---

## 1. The Capital Efficiency Problem

Let us put concrete numbers on the waste.

**Normal mode --- USDC collateral, borrow DAI:**

| Parameter | Value |
|-----------|-------|
| USDC collateral | $10,000 |
| Default LTV | 77% |
| Max borrow | **$7,700** |
| Capital locked (unborrowed) | $2,300 |

That $2,300 is earning supplier yield, but you cannot deploy it. For a yield farmer who wants to supply USDC and borrow DAI to deposit elsewhere, this 23% overhead directly reduces returns.

**E-Mode --- USDC collateral, borrow DAI (Stablecoin category):**

| Parameter | Value |
|-----------|-------|
| USDC collateral | $10,000 |
| E-Mode LTV | 93% |
| Max borrow | **$9,300** |
| Capital locked (unborrowed) | $700 |

That is **$1,600 more borrowing power** from the same collateral. The locked capital drops from $2,300 to $700 --- a 70% reduction in idle capital. For someone running leveraged stablecoin strategies, this difference compounds into significantly higher returns.

---

## 2. How E-Mode Works

E-Mode groups correlated assets into **categories**. When a user opts into a category, the protocol substitutes boosted risk parameters for all assets in that category. The key parameters that change:

| Parameter | Normal Mode (ETH) | E-Mode (ETH correlated) | Why |
|-----------|-------------------|-------------------------|-----|
| LTV | 80% | 93% | Lower divergence risk means less buffer needed |
| Liquidation threshold | 82.5% | 95% | Correlated assets rarely gap apart |
| Liquidation bonus | 5% | 1% | Smaller price gaps mean liquidators need less incentive |

The lower liquidation bonus is particularly interesting. In normal mode, a liquidator needs a 5% bonus because the collateral (ETH) might be crashing while they execute. In E-Mode for stablecoins, the collateral and debt are nearly identical in value --- a 1% bonus is plenty of incentive.

### The Categories

Each E-Mode category has an ID (a `uint8`), custom risk parameters, an optional oracle override, and a human-readable label. Category 0 means "no E-Mode" and is the default.

A typical Aave V3 deployment might define:

**Category 1: Stablecoins** (LTV 93%, Liq. Threshold 95%, Bonus 1%)

| Asset | Default LTV | E-Mode LTV |
|-------|-------------|------------|
| USDC  | 77%         | 93%        |
| DAI   | 67%         | 93%        |
| USDT  | 75%         | 93%        |

**Category 2: ETH Correlated** (LTV 93%, Liq. Threshold 95%, Bonus 1%)

| Asset  | Default LTV | E-Mode LTV |
|--------|-------------|------------|
| WETH   | 80%         | 93%        |
| stETH  | 69%         | 93%        |
| wstETH | 69%         | 93%        |

Assets like WBTC (category 0) do not belong to any E-Mode group and always use their default parameters.

---

## 3. The Rules of E-Mode

<video src="../animations/final/emode_barchart.webm" controls autoplay loop muted playsinline style="width:100%;max-width:800px;border-radius:8px;margin:20px 0"></video>

E-Mode is not a free lunch. It comes with a strict constraint and some important nuances:

### Rule 1: All Borrows Must Match the Category

When you are in E-Mode category 1 (Stablecoins), every asset you borrow must also belong to category 1. You can borrow USDC, DAI, or USDT --- but not WETH or WBTC. This makes sense: the boosted parameters assume correlated assets on both sides. Borrowing a volatile asset against stablecoin collateral would defeat the purpose.

If you have existing borrows that do not match the target category, you must repay them before entering E-Mode.

### Rule 2: Collateral Is Unrestricted (But Benefits Are Selective)

You can have any collateral while in E-Mode. However, only collateral that belongs to your active E-Mode category gets the boosted parameters. Everything else uses its default LTV and liquidation threshold.

This means you can have a mixed portfolio, but the benefit is proportional to how much of your collateral matches the category.

### Rule 3: Exiting Must Not Break Your Position

To exit E-Mode (set category to 0), the protocol recalculates your health factor using default parameters. If your position is too leveraged to survive the switch --- health factor would drop below 1 --- the exit is blocked. You must repay debt or add collateral first.

---

## 4. Numerical Examples

### Example 1: Pure Stablecoin Position

Alice has $10,000 USDC and enters Stablecoin E-Mode.

**Borrowing capacity:**

```
Max borrow = $10,000 x 93% = $9,300 DAI
```

**Health factor at max borrow:**

```
HF = ($10,000 x 0.95) / $9,300 = 1.022
```

She is just above the liquidation line with a 2.2% margin. In normal mode, the same position would give her:

```
Max borrow = $10,000 x 77% = $7,700 DAI
HF at max = ($10,000 x 0.80) / $7,700 = 1.039
```

E-Mode gives her $1,600 more borrowing power with a similar (slightly tighter) safety margin. The tighter margin is acceptable because both assets are pegged to $1.

### Example 2: Leveraged Staking with ETH E-Mode

Bob wants to amplify his stETH staking yield (~3-4% APR). He enters ETH Correlated E-Mode.

**Without E-Mode:**

| Parameter | Value |
|-----------|-------|
| Supply | 100 stETH (~$300,000) |
| Default LTV | 69% |
| Max WETH borrow | 69 WETH |

**With E-Mode:**

| Parameter | Value |
|-----------|-------|
| Supply | 100 stETH (~$300,000) |
| E-Mode LTV | 93% |
| Max WETH borrow | 93 WETH |

Bob can borrow 93 WETH instead of 69. If he loops (supply stETH, borrow WETH, swap to stETH, repeat --- or use a flash loan), he can build a heavily leveraged staking position:

1. Start with 10 stETH
2. Flash loan 90 WETH, swap to stETH, supply 100 stETH total
3. Borrow 90 WETH to repay the flash loan
4. Result: 100 stETH collateral, 90 WETH debt

Bob is now earning staking yield on 100 stETH while paying borrow interest on 90 WETH. If the staking yield exceeds the borrow rate, the spread is multiplied by his leverage. E-Mode makes this 10x leverage possible; without it, the maximum would be around 3x.

### Example 3: Mixed Collateral

What happens when collateral spans multiple categories?

Charlie is in Stablecoin E-Mode with:
- $8,000 in USDC (category 1 --- gets E-Mode boost)
- $3,000 in WETH (category 2 --- uses default parameters)

| Collateral | Value | LTV Used | Weighted Contribution |
|------------|-------|----------|----------------------|
| USDC | $8,000 | 93% (E-Mode) | $8,000 x 93% = $7,440 |
| WETH | $3,000 | 80% (default) | $3,000 x 80% = $2,400 |

**Weighted average LTV** = ($7,440 + $2,400) / $11,000 = **89.45%**

**Max borrow** = $11,000 x 89.45% = **$9,840** (stablecoins only, since borrows must match E-Mode category)

The WETH contributes collateral value using its default parameters. The USDC gets the E-Mode boost. The blended result falls between the two.

---

## 5. Oracle Override: Eliminating Noise

One of the most subtle features of E-Mode is the optional **custom price oracle**. Each E-Mode category can specify a price source that overrides the default Chainlink feeds for assets in the category.

### The Problem It Solves

Chainlink reports real market prices. Stablecoins occasionally trade at $0.998 or $1.003 due to market microstructure, DEX imbalances, or momentary liquidity gaps. These tiny deviations are economically meaningless for a stablecoin-against-stablecoin position, but they create noise in the health factor calculation.

In extreme cases, a minor depeg of $0.005 could push a highly leveraged E-Mode position below the liquidation threshold --- triggering a liquidation that costs the borrower 1% of their collateral for a risk that does not actually exist.

### The Solution

A custom oracle for the stablecoin E-Mode category can price all stablecoins at exactly $1.00. The health factor becomes a pure function of quantity borrowed versus quantity supplied, ignoring market microstructure:

```
With default oracle:  HF = ($9,970 x 0.95) / $9,300 = 1.019  (USDC at $0.997)
With fixed oracle:    HF = ($10,000 x 0.95) / $9,300 = 1.022  (USDC at $1.000)
```

The difference is small in this example, but for positions at the margin, it prevents spurious liquidations.

### The Trade-off

Custom oracles are a double-edged sword. If a stablecoin genuinely depegs --- say, to $0.80 --- a fixed oracle would still price it at $1.00 within E-Mode. This could delay necessary liquidations and create bad debt.

In practice, this risk is managed by:
1. Only applying custom oracles to thoroughly vetted assets
2. Governance monitoring and the ability to quickly remove assets from categories
3. Most deployments using the default oracle even for E-Mode, relying solely on the boosted LTV and threshold for efficiency

---

## 6. E-Mode and Liquidations

Liquidations in E-Mode use the E-Mode parameters, not the asset defaults. This has two important implications:

### Tighter Threshold, Harder to Liquidate

A stablecoin E-Mode position with $10,000 USDC and $9,400 DAI debt:

- **In E-Mode**: HF = ($10,000 x 0.95) / $9,400 = 1.011 --- healthy
- **Without E-Mode**: HF = ($10,000 x 0.80) / $9,400 = 0.851 --- deep in liquidation

The same position is healthy in E-Mode and deeply underwater without it. The 95% threshold means you tolerate much more debt relative to collateral before becoming liquidatable.

### Lower Bonus, Cheaper Liquidation

If liquidation does occur, the 1% bonus (vs. 5% normally) means the borrower loses much less collateral. On a $100,000 liquidation:

| Mode | Bonus | Collateral Lost Beyond Debt |
|------|-------|----------------------------|
| Normal | 5% | $5,000 |
| E-Mode | 1% | $1,000 |

This makes sense economically. The collateral and debt are closely priced, so the liquidator faces minimal price risk. They do not need a large bonus to be incentivized.

---

## 7. Entering and Exiting E-Mode

### Entering

Call `Pool.setUserEMode(categoryId)`. The protocol:

1. Checks that all your current borrows belong to the target category. If you are borrowing WETH, you cannot enter Stablecoin E-Mode until you repay it.
2. Sets your E-Mode category.
3. Recalculates your health factor with the new parameters and confirms it is >= 1.

### Exiting

Call `Pool.setUserEMode(0)`. The protocol:

1. No borrow validation needed (category 0 has no restrictions).
2. Reverts your risk parameters to per-asset defaults.
3. Recalculates your health factor. If it would drop below 1 (because default parameters are stricter), the exit is blocked.

This creates an interesting situation: a position that is perfectly healthy in E-Mode might be too leveraged to exit. The user must deleverage first.

---

## Key Takeaways

1. **E-Mode solves the capital efficiency problem** for correlated assets. Borrowing a stablecoin against another stablecoin should not require 23% overcollateralization. E-Mode reduces it to 7%.

2. **Categories group correlated assets** with boosted LTV (93%), higher liquidation threshold (95%), and reduced liquidation bonus (1%). The parameters reflect the genuinely lower risk of correlated positions.

3. **The restriction is on borrows, not collateral.** All borrowed assets must belong to the active E-Mode category. Collateral can be anything, but only matching collateral gets boosted parameters.

4. **The capital efficiency gain is substantial.** On $10,000 USDC, E-Mode unlocks $9,300 of borrowing power vs. $7,700 normally --- $1,600 more, with idle capital dropping from $2,300 to $700.

5. **Oracle override** can eliminate spurious liquidations from minor price fluctuations between pegged assets, but introduces risk if the peg genuinely breaks. Most deployments use it conservatively.

6. **Exiting E-Mode requires surviving default parameters.** A position that is healthy at 95% liquidation threshold might be underwater at 82.5%. Users must deleverage before they can leave.

7. **Liquidations in E-Mode are cheaper for borrowers** (1% bonus vs. 5%), reflecting the lower risk and smaller price gaps between correlated assets.
