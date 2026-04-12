# Chapter 7: Collateral, Liquidations, and the Health Factor

Lending protocols exist because they promise lenders one thing: you will get your money back, plus interest. But Aave lends to anonymous borrowers with no credit checks, no legal recourse, and no collection agencies. The only thing protecting lenders is **overcollateralization** --- borrowers must lock up more value than they borrow.

The problem is that collateral values change. ETH can drop 20% in a day. If a borrower's collateral falls below their debt, the protocol has a hole in its balance sheet --- lenders cannot be made whole. This is called **bad debt**, and it is the existential threat to any lending protocol.

Liquidation is the mechanism that prevents bad debt. When a borrower's position becomes risky, the protocol allows anyone to step in, repay part of the debt, and claim the borrower's collateral at a discount. The borrower loses some collateral. The liquidator earns a profit. And the protocol stays solvent.

This chapter explains the economics of how that system works: the risk parameters that define borrowing limits, the health factor that measures safety, and the liquidation process that enforces it all.

---

## 1. Risk Parameters: The Economic Levers

Every asset on Aave has three key risk parameters set by governance. Together, they define the economic boundaries of borrowing and liquidation.

### Loan-to-Value (LTV): Your Borrowing Power

LTV answers a simple question: for every dollar of this asset you supply, how much can you borrow?

If ETH has an LTV of 80%, then $10,000 of ETH collateral lets you borrow up to $8,000. The remaining $2,000 is your margin of safety --- the protocol's buffer against price drops.

Riskier assets get lower LTVs. Governance sets these based on liquidity, volatility, and market depth:

| Asset | LTV  | What It Means |
|-------|------|---------------|
| WETH  | 80%  | Well-understood, deep liquidity --- generous borrowing power |
| WBTC  | 70%  | Cross-chain bridge risk warrants more caution |
| USDC  | 86.5%| Very stable, tight peg --- high borrowing power |
| DAI   | 75%  | Algorithmic elements add slight risk |

LTV is only checked when **opening or increasing** a position. Once you have borrowed, your position is not liquidated until it crosses a different line.

### Liquidation Threshold: The Safety Line

The liquidation threshold is the point at which your position becomes liquidatable. It is always higher than the LTV, creating a buffer zone.

With ETH's LTV at 80% and liquidation threshold at 82.5%, you can borrow up to 80% of your collateral's value, but you are not liquidated until your debt reaches 82.5% of collateral value. That 2.5% gap is your breathing room --- time to add collateral or repay debt as prices move against you.

Why not make them the same number? Because prices are volatile. If you could borrow right up to the liquidation line, any small price fluctuation would trigger immediate liquidation. The gap gives borrowers a realistic chance to manage their positions.

### Liquidation Bonus: The Incentive for Liquidators

Liquidation does not happen automatically. Someone has to monitor every position on the protocol, detect when one crosses the threshold, submit a transaction, and pay gas. That someone is a **liquidator**, and they need a reason to do this work.

The liquidation bonus is that reason. It is the discount at which liquidators buy collateral. If the liquidation bonus is 5%, a liquidator who repays $10,000 of debt receives $10,500 worth of collateral. That $500 profit comes directly from the borrower's collateral --- the borrower loses more than their debt was worth.

Higher-risk assets have higher bonuses because they need to attract liquidators even when the market is chaotic:

| Asset | LTV  | Liq. Threshold | Liq. Bonus | Buffer Zone |
|-------|------|----------------|------------|-------------|
| WETH  | 80%  | 82.5%          | 5%         | 2.5%        |
| WBTC  | 70%  | 75%            | 10%        | 5%          |
| USDC  | 86.5%| 89%            | 4.5%       | 2.5%        |
| DAI   | 75%  | 80%            | 5%         | 5%          |

*Note: actual values vary by deployment and governance decisions. These are illustrative.*

### Liquidation Protocol Fee

A portion of the liquidation bonus is redirected to the Aave treasury. If the bonus is 5% and the protocol fee is 10% of the bonus, the liquidator keeps 4.5% and the treasury takes 0.5%. This turns every liquidation into a small revenue event for the protocol.

---

## 2. The Health Factor: One Number to Rule Them All

<video src="../animations/final/health_factor.webm" controls autoplay loop muted playsinline style="width:100%;max-width:800px;border-radius:8px;margin:20px 0"></video>

The health factor (HF) is the single most important number for any borrower. It condenses the entire safety of a position into one metric:

**Health Factor = (Total Collateral x Weighted Liquidation Threshold) / Total Debt**

- **HF >= 1**: You are safe. Nobody can liquidate you.
- **HF < 1**: You are liquidatable. Anyone can close part of your position.

The health factor moves for two reasons: your collateral changes in value (price moves), or your debt grows (interest accrues). Both are constantly happening, which is why the health factor is a living number.

### Numerical Example: Watching the Health Factor Move

Alice supplies **10 ETH** as collateral (ETH = $2,000, liquidation threshold = 82.5%).
She borrows **$15,000 USDC**.

**Day 1 --- Everything is fine:**

```
Collateral value:  10 x $2,000 = $20,000
Adjusted collateral: $20,000 x 0.825 = $16,500
Health Factor:     $16,500 / $15,000 = 1.10
```

Alice has a 10% safety margin. She sleeps well.

**Day 2 --- ETH drops to $1,900:**

```
Adjusted collateral: 10 x $1,900 x 0.825 = $15,675
Health Factor:     $15,675 / $15,000 = 1.045
```

Getting uncomfortable, but still safe.

**Day 3 --- ETH drops to $1,800:**

```
Adjusted collateral: 10 x $1,800 x 0.825 = $14,850
Health Factor:     $14,850 / $15,000 = 0.99
```

Health factor is below 1. Alice is now liquidatable.

Notice: Alice originally borrowed at 75% LTV ($15,000 / $20,000), well within the 80% limit. The buffer between LTV (80%) and liquidation threshold (82.5%) gave her some protection, but a 10% price drop was enough to push her over the edge.

### Weighted Averages for Multiple Collateral Types

If you supply multiple assets as collateral, the protocol computes a weighted average liquidation threshold. For example:

- $10,000 in ETH (threshold: 82.5%) and $5,000 in USDC (threshold: 89%)
- Weighted threshold: ($10,000 x 82.5% + $5,000 x 89%) / $15,000 = **84.67%**

This blended threshold determines your health factor. More stable collateral in the mix raises your effective threshold and improves your health factor.

---

## 3. The Liquidation Process: An Economic Transaction

When a health factor drops below 1, a liquidation is not a penalty imposed by the protocol. It is an open economic opportunity. Anyone --- a bot, a DAO, an individual --- can execute it by calling `liquidationCall()` on the Pool contract. No whitelist, no permissions.

The liquidator specifies:
- Which collateral to seize from the borrower
- Which debt to repay on their behalf
- How much debt to cover
- Whether to receive the collateral as aTokens (to keep earning yield) or as the underlying asset

### What Happens Step by Step

**1. Check eligibility.** The protocol recalculates the borrower's health factor using current oracle prices. If HF >= 1, the liquidation reverts --- the position is healthy.

**2. Determine how much can be liquidated** (the close factor --- see next section).

**3. Calculate collateral to seize.** The protocol converts the debt amount to collateral value using oracle prices, then adds the liquidation bonus:

```
Collateral seized = (Debt repaid / Collateral price) x (1 + Bonus%)
```

If the borrower does not have enough collateral to cover the full bonus, the available collateral sets the limit and the debt repaid is reduced accordingly.

**4. Execute the swap.** The liquidator sends debt tokens to the protocol (burning the borrower's debt). The protocol transfers collateral from the borrower to the liquidator. If a protocol fee applies, a small portion of the bonus goes to the Aave treasury.

**5. Update interest rates** for both the collateral and debt reserves to reflect the changed utilization.

After liquidation, the borrower has less collateral but also less debt. Their health factor typically improves, often rising back above 1.

---

## 4. The Close Factor: Partial vs. Full Liquidation

The close factor determines what fraction of a borrower's debt can be liquidated in a single call. Aave V3 uses two tiers:

| Health Factor Range | Close Factor | Rationale |
|---------------------|-------------|-----------|
| 0.95 to 1.0        | **50%**     | Position is slightly underwater. A partial liquidation should restore health, giving the borrower a chance to recover. |
| Below 0.95          | **100%**    | Position is deeply underwater. Partial liquidation might not be enough. Allow full closure to prevent bad debt. |

### Why 50% by Default?

Partial liquidation is more borrower-friendly. After a liquidator repays half the debt and takes the corresponding collateral (plus bonus), the borrower's health factor usually jumps back above 1. The borrower still has a position and can choose to add collateral, repay more, or just ride it out.

### Why 100% Below 0.95?

When a position is deeply underwater, a 50% liquidation might not restore the health factor above 1. The remaining position could become insolvent --- creating bad debt that harms lenders. Allowing full liquidation ensures the protocol can close out dangerous positions entirely.

Consider: if HF = 0.80 and you only liquidate 50% of the debt, the health factor after liquidation might still be below 1, requiring another liquidation. With 100%, a single liquidator can clean up the entire position.

---

## 5. The Liquidation Economy

### Where the Money Flows

A complete liquidation involves three parties. Here is how the economics break down with a 5% liquidation bonus and 10% protocol fee on the bonus:

```
Liquidator repays:       $10,000 of debt (in USDC)
Liquidator receives:     $10,450 of collateral (in ETH)
   -> $10,000 base value + $450 profit (4.5% net bonus)
Aave treasury receives:  $50 of collateral (0.5%, as aTokens)
Borrower loses:          $10,500 of collateral total
Borrower's debt reduced: $10,000
```

The borrower is the one paying for the entire operation through lost collateral. The liquidator profits. The protocol takes a cut. Lenders are protected because the debt is repaid.

### The Competitive Landscape

Liquidation on Aave is a competitive market. Hundreds of bots monitor every position in real time, racing to liquidate the moment a health factor crosses 1. This competition is healthy for the protocol --- it means positions are liquidated quickly, minimizing the chance of bad debt.

The competition takes several forms:

**Priority Gas Auctions (PGA).** Bots bid up gas prices to get their liquidation transaction included first. The winner captures the liquidation bonus; the losers waste gas.

**Flash loan liquidations.** Liquidators do not need capital. They flash loan the debt asset, execute the liquidation, sell the seized collateral, repay the flash loan, and pocket the difference --- all in a single transaction. This dramatically lowers the barrier to entry.

**MEV and block builders.** Sophisticated liquidators work with block builders to guarantee their transaction lands in the right position within a block. Some use private mempools to avoid being front-run.

The result: healthy positions are almost never at risk of bad debt because the moment they become liquidatable, someone is there to clean them up. The liquidation bonus ensures this market stays active even during high-volatility periods.

---

## 6. Oracle Dependency

The entire liquidation system depends on accurate price data. If prices are wrong, healthy positions could be wrongly liquidated, or insolvent positions could go unchecked.

Aave V3 uses **Chainlink price feeds** as its primary oracle source, wrapped in an `AaveOracle` contract that provides:

- **Base currency optimization**: If the asset is the base currency itself (e.g., USD on mainnet), return the unit price directly --- no oracle call needed.
- **Fallback mechanism**: If Chainlink returns zero or a negative price, fall back to a secondary oracle. This provides resilience against feed failures.
- **Consistent precision**: Prices are returned with 8 decimal places, and all health factor calculations account for the decimal differences between assets.

The price flow during liquidation is straightforward: the liquidator's transaction triggers a health factor recalculation, which queries the oracle for every asset the borrower holds. If the resulting health factor is below 1, the liquidation proceeds. The entire check is synchronous and on-chain --- no off-chain components.

---

## 7. Complete Liquidation Example

Let us walk through a full scenario with concrete numbers.

### Setup

Bob supplies **5 ETH** as collateral and borrows **6,000 USDC**.

| Parameter | Value |
|-----------|-------|
| ETH price | $2,000 |
| ETH LTV | 80% |
| ETH liquidation threshold | 82.5% |
| ETH liquidation bonus | 5% |
| Protocol fee | 10% of bonus |

Bob's initial position:
- Collateral: 5 x $2,000 = **$10,000**
- Max borrow: $10,000 x 80% = $8,000 (he only used $6,000)
- Health factor: ($10,000 x 0.825) / $6,000 = **1.375**

Bob is well within safe territory.

### The Price Drop

ETH falls to **$1,450**. Bob's debt has accrued slightly to **$6,050**.

- Collateral: 5 x $1,450 = **$7,250**
- Health factor: ($7,250 x 0.825) / $6,050 = **$5,981 / $6,050 = 0.989**

Bob is liquidatable. Since 0.989 > 0.95, the close factor is 50%.

### The Liquidation

Carol, a liquidator bot, repays **$3,025 of USDC** (50% of Bob's debt).

**Collateral calculation:**

| Step | Calculation | Result |
|------|-------------|--------|
| Base collateral (debt value in ETH) | $3,025 / $1,450 | 2.086 ETH |
| Add 5% bonus | 2.086 x 1.05 | 2.191 ETH |
| Protocol fee (10% of bonus) | 0.105 x 0.10 | 0.010 ETH |
| Carol receives | 2.191 - 0.010 | **2.181 ETH** |

### After Liquidation

| Party | Before | After | Change |
|-------|--------|-------|--------|
| **Bob (borrower)** | 5 ETH collateral, $6,050 debt | 2.809 ETH ($4,073), $3,025 debt | Lost 2.191 ETH, debt halved |
| **Bob's health factor** | 0.989 | ($4,073 x 0.825) / $3,025 = **1.111** | Restored to health |
| **Carol (liquidator)** | Paid $3,025 USDC | Received 2.181 ETH ($3,162) | **+$137 profit** |
| **Aave treasury** | --- | 0.010 ETH ($15) as aTokens | Small fee collected |

The system worked: Bob's risky position was brought back to solvency. Carol earned a profit for performing a useful service. The protocol collected a fee. No bad debt was created. Lenders are whole.

---

## Key Takeaways

1. **Liquidation exists to protect lenders.** Borrowers post collateral, and if it loses value, liquidators step in to repay debt before the protocol becomes insolvent.

2. **Three risk parameters define the economic boundaries.** LTV sets borrowing power. The liquidation threshold is the safety line. The liquidation bonus is the incentive that makes the whole system work.

3. **The health factor is the single metric that matters.** It is a ratio of risk-adjusted collateral to debt. Above 1 means safe. Below 1 means liquidatable.

4. **The close factor balances borrower protection with protocol safety.** At 50%, borrowers usually survive a liquidation. Below HF 0.95, the protocol prioritizes its own solvency with 100%.

5. **Liquidation is a competitive market.** Flash loans, MEV, and gas auctions create a fast and efficient liquidation ecosystem. This is good for the protocol --- positions rarely linger in dangerous territory.

6. **Accurate oracles are the foundation.** Every health factor calculation depends on Chainlink price feeds. Wrong prices mean wrong liquidations (or missed ones).

7. **The buffer between LTV and liquidation threshold is your margin of safety** --- but it is finite. Borrowers should monitor their health factor and maintain a comfortable margin above 1.
