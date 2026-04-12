# Chapter 10: Isolation Mode

DeFi moves fast. Every week, new tokens launch --- governance tokens, liquid staking derivatives, real-world asset tokens, memecoins-turned-infrastructure. Users want to use these tokens as collateral on Aave. More listed assets mean more users, more liquidity, and more revenue.

But new tokens are risky. A freshly launched governance token might have \$5M of liquidity on DEXes today and \$500K tomorrow. Its price could crash 80% in an hour. If Aave allows unlimited borrowing against such a token, and the token collapses, the protocol could end up with millions in bad debt --- losses that fall on every lender in the pool.

The traditional answer was simple: do not list risky assets. But that limits growth. Aave V3 introduces a better answer: **Isolation Mode**. List the asset, but with strict guardrails that cap the protocol's maximum exposure.

---

## 1. The Risk Problem

Not all collateral is created equal. Consider two assets:

| Property | WETH | NEW_TOKEN |
|----------|------|-----------|
| Market cap | \$300B+ | \$50M |
| Daily DEX volume | \$2B+ | \$3M |
| Price history | 8+ years | 3 months |
| Oracle reliability | Battle-tested Chainlink feed | Newer feed, less validation |
| Worst daily drop | ~20% | Unknown |

Lending against WETH is well-understood. The risk parameters (80% LTV, 5% liquidation bonus) are calibrated against years of volatility data and deep liquidation markets. Bots can liquidate WETH positions quickly because there is ample liquidity to buy or sell.

Lending against NEW_TOKEN is a different story. If its price drops 50% in minutes, liquidators may not be able to sell the seized collateral fast enough. The liquidation bonus might not cover the slippage. And if many users have borrowed against NEW_TOKEN, the total bad debt could be substantial.

**Isolation Mode bounds this risk.** It says: "Yes, list the asset. Let people borrow against it. But cap the total damage."

---

## 2. The Three Guardrails

Isolation Mode imposes three restrictions on an isolated asset:

### Guardrail 1: Debt Ceiling

The most important safeguard. The **debt ceiling** is a hard cap on the total USD value of debt that can be backed by this isolated collateral, across all users combined.

If NEW_TOKEN has a \$5M debt ceiling, then no matter how many users supply it as collateral, the total borrowing against it cannot exceed \$5M. Even if NEW_TOKEN goes to zero and every position becomes insolvent, the protocol's maximum loss is \$5M (minus whatever liquidators recover).

This is a **global** limit, not per-user. Why? Because the protocol's risk is aggregate. Whether one user borrows \$5M or 5,000 users each borrow \$1,000, the protocol's exposure is the same \$5M if the collateral collapses.

| Debt Ceiling | What It Means |
|--------------|---------------|
| \$1M | Extremely cautious listing --- testing the waters |
| \$5M | Moderate confidence, growing track record |
| \$50M | High confidence, but still wants a cap |
| \$0 | Not isolated (normal asset, no ceiling) |

The ceiling is denominated in the protocol's base currency (USD on mainnet) with 2 decimals of precision. It is tracked by a global counter (`isolationModeTotalDebt`) that increments on every borrow and decrements on every repay or liquidation.

### Guardrail 2: Restricted Borrowing

A user in Isolation Mode can only borrow assets that governance has explicitly flagged as "borrowable in isolation." In practice, this means **stablecoins**: USDC, DAI, USDT.

Why stablecoins? Because they keep the debt side of the equation predictable. If a user borrows WETH against isolated collateral and ETH doubles, the debt value doubles too --- making the health factor calculation more complex and the debt ceiling less meaningful in dollar terms. Stablecoins maintain a consistent dollar value, which means the debt ceiling directly translates to a maximum dollar exposure.

| Borrowable in Isolation? | Asset | Rationale |
|--------------------------|-------|-----------|
| Yes | USDC, DAI, USDT | Stable value, predictable debt |
| No | WETH, WBTC | Volatile --- would make debt ceiling unreliable |
| Sometimes | FRAX, other stables | Governance decides case by case |

### Guardrail 3: No Additional Collateral

A user in Isolation Mode cannot enable other assets as collateral alongside the isolated asset. The isolated asset must be their **sole collateral**.

This prevents a scenario where a user mixes isolated and non-isolated collateral, making it difficult to attribute risk. If a user has both WETH and NEW_TOKEN as collateral, how much of their borrow is "backed by" the risky token? The answer is ambiguous, and the debt ceiling becomes harder to enforce meaningfully.

By requiring sole collateral, the relationship is clear: this user's entire position depends on the isolated asset, and their borrow counts fully against the debt ceiling.

---

## 3. How Isolation Mode Is Triggered

There is no "enter isolation mode" button. The protocol detects Isolation Mode dynamically based on the user's collateral configuration:

1. The user supplies an asset that has a non-zero debt ceiling (meaning governance has marked it as isolated)
2. The user enables that asset as their collateral
3. That asset is their **only** enabled collateral
4. Result: the user is in Isolation Mode

The detection happens at borrow time. The protocol looks at the user's collateral, finds the first (and only) collateral asset, checks if it has a debt ceiling, and if so, applies the isolation restrictions.

Two-way enforcement prevents mixing:
- If you already have an isolated collateral, you cannot enable additional collateral
- If you already have non-isolated collateral, you cannot enable an isolated asset

To exit, disable the isolated collateral (requires no outstanding debt that depends on it) or swap your collateral base by supplying and enabling a non-isolated asset first.

---

## 4. A Complete Example

Let us trace through a realistic scenario.

### Governance Lists NEW_TOKEN

Governance decides to list a new DeFi governance token. The configuration:

| Parameter | Value |
|-----------|-------|
| Asset | NEW_TOKEN |
| Price | \$10 |
| Isolated | Yes |
| Debt ceiling | \$5,000,000 |
| LTV | 50% |
| Liquidation threshold | 55% |
| Liquidation bonus | 10% |

Assets borrowable in isolation: USDC, DAI, USDT.

The conservative parameters reflect the asset's risk: 50% LTV (vs. 80% for ETH), 10% liquidation bonus (vs. 5% for ETH), and a \$5M debt ceiling.

### Alice Borrows Against NEW_TOKEN

Alice holds 100,000 NEW_TOKEN (\$1,000,000 at \$10 each).

**Step 1:** She supplies NEW_TOKEN to Aave and enables it as collateral. Since it has a debt ceiling and is her only collateral, she is now in Isolation Mode.

**Step 2:** She borrows \$400,000 USDC.

The protocol checks:
1. Is she in Isolation Mode? Yes.
2. Is USDC borrowable in isolation? Yes.
3. Current debt against NEW_TOKEN across all users: \$3,200,000. Adding \$400,000 = \$3,600,000. Ceiling is \$5,000,000. Under the limit.
4. Health factor: (\$1,000,000 x 0.55) / \$400,000 = **1.375**. Healthy.

The borrow succeeds. The `isolationModeTotalDebt` counter for NEW_TOKEN increases to \$3,600,000.

**What Alice cannot do:**

| Action | Result | Why |
|--------|--------|-----|
| Borrow WETH | Reverts | WETH is not borrowable in isolation |
| Enable ETH as additional collateral | Reverts | Cannot mix collateral in Isolation Mode |
| Borrow another \$2M USDC | Reverts | Would push total debt to \$5,600,000, exceeding the \$5M ceiling |

### The Debt Ceiling in Action

Other users have also been borrowing against NEW_TOKEN. The debt counter reaches \$5,000,000. Bob tries to borrow \$100,000 USDC against his NEW_TOKEN collateral:

```
Current total: \$5,000,000
Bob's borrow:  \$100,000
New total:     \$5,100,000 > \$5,000,000 ceiling
Result:        REVERTS (DEBT_CEILING_EXCEEDED)
```

No more borrowing against NEW_TOKEN is possible until some users repay. The protocol's maximum exposure is capped.

### The Worst-Case Scenario

Imagine NEW_TOKEN crashes to \$0. Every position backed by it becomes insolvent. Liquidators cannot sell the worthless collateral. The protocol absorbs up to \$5M in bad debt.

But \$5M is the absolute worst case, by design. Without the debt ceiling, users could have borrowed \$50M or \$100M against NEW_TOKEN, and the loss would be catastrophic. The ceiling turns a potential existential crisis into a manageable loss that the Aave treasury and safety module can absorb.

### Alice Exits Isolation Mode

Alice repays her \$400,000 USDC debt. The `isolationModeTotalDebt` decreases by \$400,000, freeing capacity for other users.

She disables NEW_TOKEN as collateral. She is no longer in Isolation Mode and can now enable other assets as collateral and borrow any asset.

---

## 5. Isolation Mode + E-Mode

A user can be in both Isolation Mode and E-Mode simultaneously. This is particularly relevant for new stablecoins.

Imagine governance lists a new stablecoin (nUSD) as:
- Isolated with a \$5M debt ceiling
- E-Mode category 1 (Stablecoins)

A user supplies nUSD, enters Stablecoin E-Mode, and borrows USDC. They get:
- E-Mode's boosted 93% LTV (instead of nUSD's default, which might be 50%)
- But the debt ceiling still applies
- And only isolation-borrowable assets can be borrowed
- Both constraint sets must be satisfied

This combination lets Aave list a new stablecoin with high capital efficiency (via E-Mode) while still capping risk exposure (via the debt ceiling). It is the best of both worlds.

---

## 6. The Debt Ceiling Mechanics

The debt ceiling counter is tracked per isolated asset in the reserve data as `isolationModeTotalDebt`. The counter uses **2 decimal precision** to match the debt ceiling's denomination.

- **On borrow**: The counter increases by the borrowed amount (scaled to 2 decimals). A borrow of 5,000.123456 USDC increases the counter by 5,000.12.
- **On repay**: The counter decreases by the repaid amount. A saturating subtraction prevents underflow from rounding differences.
- **On liquidation**: The counter also decreases, freeing capacity under the ceiling for other users.

This means the debt ceiling is a living limit. As users repay or get liquidated, capacity opens up for new borrowers. It is not a one-time allocation.

---

## 7. Liquidation in Isolation Mode

Liquidation works the same as normal mode, but with two important economic effects:

### Higher Liquidation Bonus = Faster Liquidator Response

Isolated assets typically have a 10% liquidation bonus (vs. 5% for ETH). This is deliberate. Riskier, less liquid assets need a bigger incentive to attract liquidators. If the collateral is hard to sell, liquidators demand a larger discount to compensate for the risk of holding it. The higher bonus ensures positions get liquidated promptly even if the token is thinly traded.

### Liquidation Frees Ceiling Capacity

When a position is liquidated, the debt counter decreases. If Alice's \$400,000 position is liquidated, \$400,000 of ceiling capacity becomes available for other users. This is important: the debt ceiling does not permanently consume capacity. It is a measure of current outstanding exposure, not lifetime usage.

| Event | Debt Counter | Available Under \$5M Ceiling |
|-------|-------------|----------------------------|
| Initial state | \$0 | \$5,000,000 |
| Alice borrows \$400K | \$400,000 | \$4,600,000 |
| Others borrow \$4.6M | \$5,000,000 | \$0 (full) |
| Alice is liquidated | \$4,600,000 | \$400,000 |
| Others repay \$1M | \$3,600,000 | \$1,400,000 |

---

## 8. The Governance Progression

Isolation Mode is often a stepping stone. A new asset starts isolated, proves itself, and gradually gets promoted:

**Stage 1: Isolated listing.** The asset is listed with a conservative debt ceiling (\$1-5M), low LTV (40-50%), and high liquidation bonus (10%). This lets the market test the asset while capping risk.

**Stage 2: Ceiling increases.** As the asset demonstrates stability and liquidity grows, governance raises the debt ceiling. A token that started at \$5M might move to \$20M, then \$50M.

**Stage 3: Full listing.** If the asset proves itself over months or years --- deep liquidity, reliable oracle, predictable volatility --- governance can remove the debt ceiling entirely (set it to 0). The asset becomes a normal collateral type with no isolation restrictions.

**Stage 4: E-Mode eligibility.** Mature assets that are correlated with existing categories may be added to E-Mode groups, unlocking the highest capital efficiency.

This progression lets Aave balance growth with safety. New assets bring users and TVL. Isolation Mode ensures that early-stage risk is contained. And the path to full listing gives governance a framework for gradually extending trust.

### Setting the Right Ceiling

How does governance choose a debt ceiling? Several factors:

| Factor | Higher Ceiling | Lower Ceiling |
|--------|---------------|---------------|
| Market cap | Large (\$500M+) | Small (\$10-50M) |
| DEX liquidity | Deep, multiple venues | Thin, concentrated |
| Oracle quality | Battle-tested Chainlink feed | Newer, less validated |
| Historical volatility | Moderate, well-understood | Extreme or unknown |
| Protocol's safety module | Large treasury buffer | Limited reserves |

The ceiling should be set so that even in a total collapse of the isolated asset, the resulting bad debt is absorbable by the Aave safety module and treasury. This is ultimately a judgment call by governance, informed by risk analysis.

---

## Key Takeaways

1. **Isolation Mode lets Aave list riskier assets** without unbounded risk. The debt ceiling caps the protocol's worst-case loss from any single isolated asset.

2. **Three guardrails work together**: debt ceiling (caps total exposure), restricted borrowing (stablecoins only, keeping debt predictable), and no mixed collateral (keeps risk attribution clean).

3. **Entry is automatic.** If your only collateral is an isolated asset, you are in Isolation Mode. No explicit opt-in.

4. **The debt ceiling is global, not per-user.** The protocol cares about aggregate exposure. Whether one user borrows \$5M or 5,000 users each borrow \$1,000, the risk is the same.

5. **Only stablecoins can be borrowed** in Isolation Mode. This keeps the debt side predictable and makes the debt ceiling meaningful in dollar terms.

6. **Isolation Mode and E-Mode can coexist**, allowing new stablecoins to get high capital efficiency while still being risk-bounded by the ceiling.

7. **The debt ceiling is dynamic.** Repayments and liquidations free up capacity. It is a living limit, not a one-time cap.
