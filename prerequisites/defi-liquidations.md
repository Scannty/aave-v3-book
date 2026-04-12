# DeFi Liquidations and Collateral

Lending protocols allow users to borrow assets by depositing other assets as **collateral**. But what happens when the collateral drops in value and no longer covers the debt? The protocol cannot send a collections agency. It cannot take the borrower to court. It needs an on-chain, automated mechanism to protect itself from bad debt.

That mechanism is **liquidation**.

---

## Overcollateralization: The Foundation

Unlike traditional lending (where credit scores and legal enforcement exist), DeFi lending is **overcollateralized**. This means the borrower must deposit more value than they borrow.

Example:
- A user deposits $10,000 worth of ETH
- The protocol allows them to borrow up to $8,000 worth of USDC
- The extra $2,000 acts as a safety buffer

If ETH's price drops, that buffer shrinks. If it drops enough, the collateral may no longer cover the debt. Overcollateralization gives the protocol a margin of safety, but it is not unlimited.

---

## Loan-to-Value Ratio (LTV)

The **Loan-to-Value ratio** (LTV) defines the maximum amount a user can borrow against their collateral:

```
Maximum Borrow = Collateral Value * LTV
```

Each asset has its own LTV set by governance:

| Asset | Typical LTV | Meaning |
|-------|------------|---------|
| ETH | 80% | Can borrow up to 80% of ETH collateral value |
| WBTC | 73% | Can borrow up to 73% of WBTC collateral value |
| USDC | 77% | Can borrow up to 77% of USDC collateral value |

A lower LTV means the protocol is more conservative about that asset --- it requires a bigger safety buffer. Volatile assets get lower LTVs.

### Example

User deposits 5 ETH at $2,000/ETH = $10,000 collateral.
With an 80% LTV:

```
Maximum Borrow = $10,000 * 0.80 = $8,000
```

They can borrow up to $8,000 in any available asset.

---

## Liquidation Threshold

The **liquidation threshold** is different from the LTV. While LTV determines how much you *can* borrow, the liquidation threshold determines when your position *becomes liquidatable*.

The liquidation threshold is always **higher** than the LTV:

| Asset | LTV | Liquidation Threshold |
|-------|-----|----------------------|
| ETH | 80% | 82.5% |
| WBTC | 73% | 78% |
| USDC | 77% | 80% |

The gap between LTV and liquidation threshold gives borrowers a buffer zone. When you borrow at max LTV, you are not immediately at risk of liquidation --- the price has to move against you enough to cross the liquidation threshold.

<video src="animations/final/ltv_buffer.webm" controls autoplay loop muted playsinline style="width:100%;max-width:800px;border-radius:8px;margin:20px 0"></video>

---

## Health Factor

The **health factor** combines everything into a single number that represents the safety of a position:

```
                    Sum(Collateral_i * Price_i * LiquidationThreshold_i)
Health Factor = --------------------------------------------------------
                              Sum(Debt_j * Price_j)
```

In words: the risk-adjusted collateral value divided by the total debt value.

- **Health Factor > 1**: Position is safe. The higher the number, the safer.
- **Health Factor = 1**: Position is at the liquidation boundary.
- **Health Factor < 1**: Position is liquidatable.

### Example Walkthrough

A user deposits 5 ETH ($2,000/ETH) and borrows 7,000 USDC:

```
Collateral Value = 5 * $2,000 = $10,000
Risk-adjusted Collateral = $10,000 * 0.825 = $8,250
Debt Value = 7,000 USDC = $7,000

Health Factor = $8,250 / $7,000 = 1.179
```

The position is safe. Now ETH drops to $1,700:

```
Collateral Value = 5 * $1,700 = $8,500
Risk-adjusted Collateral = $8,500 * 0.825 = $7,012.50
Debt Value = $7,000 (unchanged --- they borrowed stablecoins)

Health Factor = $7,012.50 / $7,000 = 1.0018
```

The position is barely safe. One more small price drop and the health factor goes below 1.0, making the position liquidatable.

ETH drops to $1,690:

```
Collateral Value = 5 * $1,690 = $8,450
Risk-adjusted Collateral = $8,450 * 0.825 = $6,971.25
Debt Value = $7,000

Health Factor = $6,971.25 / $7,000 = 0.9959
```

Health factor is below 1.0. The position can now be liquidated.

---

## Why Liquidations Exist

Liquidations serve one purpose: **preventing bad debt**.

Bad debt occurs when a borrower's debt exceeds their collateral value. At that point, the protocol (and by extension, its depositors) loses money. No rational borrower would repay a loan that exceeds their collateral --- they would simply walk away.

```
Scenario without liquidation:

1. User deposits $10,000 ETH, borrows $8,000 USDC
2. ETH crashes 50% -> collateral now worth $5,000
3. User has no incentive to repay $8,000 debt (collateral < debt)
4. Protocol absorbs $3,000 loss
5. Depositors cannot withdraw their full balances
```

Liquidations prevent this by closing risky positions **before** the collateral falls below the debt value. The overcollateralization buffer and the liquidation threshold ensure there is always some margin to work with.

---

## How Liquidation Works

When a position's health factor drops below 1.0, anyone can **liquidate** it. The liquidator is an external actor (a bot, a protocol, or any Ethereum address) that performs the following steps:

1. **Identify** a position with health factor < 1.0
2. **Repay** a portion of the borrower's debt (up to a maximum, typically 50% of the debt in Aave)
3. **Receive** the corresponding collateral at a discount

The liquidator does not need permission. The smart contract enforces the rules.

### The Close Factor

The **close factor** limits how much of a position can be liquidated in a single transaction. In Aave V3, this is typically 50%. This means a liquidator can repay at most half the debt in one call.

Why not 100%? Partial liquidation brings the health factor back above 1.0 without completely closing the user's position. The borrower retains some collateral and some debt. If the price continues to fall, another liquidation can occur.

---

## Liquidation Bonus (Incentive)

Liquidators need a reason to act. Monitoring positions, paying gas, and taking on execution risk costs money. The **liquidation bonus** (also called the liquidation incentive or penalty) provides this motivation.

The liquidation bonus means the liquidator receives **more collateral** than the debt they repay:

```
Collateral Received = Debt Repaid * (1 + Liquidation Bonus)
```

Typical liquidation bonuses:

| Asset | Liquidation Bonus |
|-------|------------------|
| ETH | 5% |
| WBTC | 6.5% |
| Stablecoins | 4.5% |

### Example

A liquidator repays 3,500 USDC of the borrower's debt against ETH collateral. ETH price is $1,690, and the liquidation bonus is 5%.

```
Debt Repaid: 3,500 USDC = $3,500
Collateral Received: $3,500 * 1.05 = $3,675 worth of ETH
ETH Received: $3,675 / $1,690 = 2.175 ETH

Liquidator Profit: $3,675 - $3,500 = $175 (before gas costs)
```

The borrower loses $3,675 worth of collateral to clear $3,500 of debt. The extra $175 is the liquidator's reward and the borrower's penalty.

---

## The Liquidation Economy

In practice, liquidation is competitive. Multiple bots monitor the mempool and on-chain state, racing to liquidate profitable positions. This competition has several effects:

- **Speed**: Positions are liquidated quickly, often within the same block they become liquidatable.
- **MEV**: Liquidations are a major source of Maximal Extractable Value. Searchers use flashbots and priority gas auctions to win liquidation opportunities.
- **Flash loans**: Liquidators often use flash loans to perform liquidations without upfront capital. They borrow the repayment amount, execute the liquidation, sell the received collateral, and repay the flash loan --- all in one transaction.

---

## What Happens After Liquidation

After a partial liquidation, the borrower's position looks like this:

| | Before | After |
|---|--------|-------|
| Collateral | 5 ETH ($8,450) | 2.825 ETH ($4,773.25) |
| Debt | 7,000 USDC | 3,500 USDC |
| Health Factor | 0.9959 | 1.124 |

The health factor has been restored above 1.0. The borrower still has a position, but it is smaller and healthier.

If the price continues dropping, the health factor may fall below 1.0 again, triggering another round of liquidation. In extreme cases, multiple successive liquidations can occur until the position is fully closed.

---

## Edge Case: Bad Debt

If the price drops so fast that liquidators cannot act in time (or if it is not profitable to liquidate), the protocol can accumulate **bad debt** --- positions where the debt exceeds the collateral.

Protocols handle this differently:
- **Insurance funds / safety modules**: A reserve of tokens that can cover losses
- **Socialized losses**: Spread the loss across all depositors (last resort)
- **Governance intervention**: DAO votes on how to handle specific bad debt events

Aave V3 uses its Safety Module (a staking mechanism where AAVE holders backstop the protocol) and governance processes to manage this risk.

---

## Summary

| Concept | Definition |
|---------|-----------|
| Overcollateralization | Collateral must exceed debt value |
| LTV (Loan-to-Value) | Maximum borrow ratio against collateral |
| Liquidation Threshold | Ratio at which a position becomes liquidatable |
| Health Factor | Risk-adjusted collateral / total debt (< 1.0 = liquidatable) |
| Close Factor | Maximum % of debt that can be liquidated at once |
| Liquidation Bonus | Extra collateral given to liquidators as incentive |
| Bad Debt | When debt exceeds collateral --- the scenario liquidations prevent |

These concepts are the foundation for Chapter 7 (Liquidations), where we examine Aave V3's specific liquidation implementation, including E-Mode liquidations, grace periods, and the exact on-chain mechanics of the `liquidationCall()` function.
