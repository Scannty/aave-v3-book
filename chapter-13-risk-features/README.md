# Chapter 13: Additional Risk Features

Aave V3 lists hundreds of assets across multiple chains. Each asset carries its own risk profile --- different liquidity depths, different volatility characteristics, different market microstructures. Listing an asset without guardrails would expose the entire protocol to the tail risk of any single token. This chapter covers three features that let governance fine-tune risk at the individual asset level: supply and borrow caps, siloed borrowing, and repay with aTokens.

These features are small in scope but significant in practice. Caps prevent concentration risk. Siloed borrowing isolates exotic assets from the rest of the debt portfolio. And repay-with-aTokens provides an efficient mechanism for users to unwind positions. Together with Isolation Mode (Chapter 10) and E-Mode (Chapter 9), they form the complete toolkit that lets Aave list aggressively while managing risk conservatively.

---

## 1. Supply and Borrow Caps: Limiting Protocol Exposure

### The Problem They Solve

Imagine Aave lists a new governance token, TOKEN-X, with $20 million of on-chain liquidity. Without limits, a whale could supply $500 million of TOKEN-X as collateral, borrow $300 million of USDC against it, and then either manipulate TOKEN-X's price or simply wait for it to crash. Even without manipulation, the protocol would hold more TOKEN-X than the market could absorb in a liquidation. Liquidators could not sell the seized collateral without crashing the price further, creating a cascading liquidation spiral and ultimately bad debt that the protocol cannot recover.

Supply and borrow caps solve this by putting hard limits on how much of any single asset can flow through the protocol.

### What They Are

**Supply cap**: The maximum total amount of an asset that can be deposited into the protocol. Once reached, no new `supply()` calls succeed for that asset. Existing suppliers are completely unaffected --- they can still withdraw, earn interest, and use their positions as collateral.

**Borrow cap**: The maximum total amount of an asset that can be borrowed. Once reached, no new borrows succeed. Existing borrowers are unaffected --- they continue accruing interest and can repay at any time.

Both caps are denominated in whole tokens (not wei). A supply cap of 2,000,000 for USDC means 2 million USDC regardless of USDC having 6 decimals internally.

### How Governance Sizes Caps

Cap sizing is one of the most important risk management decisions in the protocol. The general framework:

| Factor | Impact on Cap |
|---|---|
| On-chain liquidity depth | More liquid = higher cap allowed |
| Token volatility | More volatile = lower cap needed |
| Oracle reliability | Less reliable oracle = lower cap for safety |
| Market cap and distribution | Concentrated holdings = lower cap |
| Historical liquidation performance | Poor liquidation history = lower cap |

### Real-World Comparison

Consider how caps differ between a blue-chip asset and a riskier one:

| Parameter | USDC | CRV |
|---|---|---|
| Supply Cap | 2,000,000,000 | 62,500,000 |
| Borrow Cap | 1,500,000,000 | 7,700,000 |
| Rationale | Deep liquidity, minimal volatility | Lower liquidity, higher volatility |

The CRV caps are roughly 30x tighter than USDC. If CRV's price crashes, Aave needs to ensure the total CRV position is small enough that liquidations can clear the debt without cascading losses. The USDC caps are generous because USDC is deep, stable, and easy to liquidate.

### Important Behaviors

**Caps do not force withdrawals.** If governance lowers a supply cap below the current total supply, existing positions are grandfathered. No one is forced to withdraw. But no new supply is accepted until the total naturally drops below the new cap (through withdrawals).

**Caps are all-or-nothing.** If a supply would push the total over the cap, the entire transaction reverts. There is no partial fill.

**Interest can exceed caps.** Total supply and total debt grow over time as interest accrues. A reserve could technically breach its cap through organic interest accumulation. This is by design --- caps prevent new inflows, not the natural growth of existing positions.

**A cap of zero means uncapped.** This is the default for well-established assets on some deployments. Setting a cap to zero removes the restriction entirely.

### Numerical Example

Suppose the ETH borrow cap is set to 500,000 ETH. Currently, 495,000 ETH is borrowed.

- Alice tries to borrow 6,000 ETH: **reverts** (495,000 + 6,000 = 501,000 > 500,000)
- Bob tries to borrow 4,000 ETH: **succeeds** (495,000 + 4,000 = 499,000 < 500,000)
- Interest accrues, pushing total debt to 500,200 ETH: **no problem** (organic growth is allowed)
- Carol tries to borrow 1 ETH: **reverts** (total is already above cap)

---

## 2. Siloed Borrowing: Quarantining Risky Debt

### The Problem It Solves

Some assets have unusual mechanics that create complex risk interactions when borrowed alongside other assets. Rebasing tokens change their balance automatically. Tokens with transfer fees lose value on every transfer. Tokens with low or fragmented liquidity can be difficult to liquidate. When a user borrows one of these alongside a normal asset like USDC, the risk model for the combined position becomes much harder to reason about --- and much harder to liquidate safely.

### The Rule

Siloed borrowing is a per-asset flag that says: **if you borrow this asset, it must be your only borrow.** You cannot hold any other borrows simultaneously.

The restriction works in both directions:
1. If you already have any borrows and try to borrow a siloed asset --- the transaction reverts.
2. If you already have a siloed borrow and try to borrow anything else (siloed or not) --- the transaction reverts.
3. If you already have a siloed borrow, you can borrow **more of the same** siloed asset --- that is allowed.

Your collateral is not affected. You can use any combination of collateral assets. Siloed borrowing only restricts the debt side of your position.

### Practical Scenarios

**Scenario A: Starting with a siloed borrow**

| Step | Action | Result |
|---|---|---|
| 1 | Supply ETH as collateral | Succeeds |
| 2 | Borrow 10,000 GHO (siloed asset) | Succeeds --- no existing borrows |
| 3 | Borrow 5,000 USDC | **Reverts** --- already have a siloed borrow |
| 4 | Borrow 5,000 more GHO | Succeeds --- same siloed asset |

**Scenario B: Starting with a regular borrow**

| Step | Action | Result |
|---|---|---|
| 1 | Supply ETH as collateral | Succeeds |
| 2 | Borrow 5,000 USDC | Succeeds --- USDC is not siloed |
| 3 | Borrow 10,000 GHO (siloed asset) | **Reverts** --- user already has borrows |
| 4 | Borrow 3,000 DAI | Succeeds --- neither USDC nor DAI is siloed |

### How Siloed Borrowing Differs from Isolation Mode and E-Mode

This is one of the most commonly confused distinctions in Aave V3. The three features are orthogonal --- they restrict different things and can be active simultaneously:

| Feature | What It Restricts | Which Side of the Position | Example |
|---|---|---|---|
| **Isolation Mode** | Which assets can be used as collateral | Collateral side | "TOKEN-X is isolated --- if it is your only collateral, you can only borrow approved stablecoins, up to a debt ceiling" |
| **Siloed Borrowing** | Which assets can be borrowed together | Debt side | "GHO is siloed --- if you borrow GHO, you cannot also borrow USDC" |
| **E-Mode** | What LTV and liquidation parameters apply | Both sides | "In stablecoin E-Mode, your USDC collateral gets 97% LTV instead of 77%" |

A user could theoretically be in Isolation Mode (using an isolated collateral asset), borrowing a siloed asset, and be in E-Mode --- all at the same time. The features compose independently because they operate on different dimensions of the position.

### Why Not Just Use Isolation Mode?

Because they address fundamentally different threats:

- **Isolation Mode** protects against collateral risk: a risky collateral asset crashing and leaving bad debt. It limits the total debt backed by that collateral.

- **Siloed Borrowing** protects against debt interaction risk: complex behaviors (rebasing, transfer fees, unusual liquidation dynamics) of a borrowed asset contaminating a multi-asset debt position. It keeps the risky debt isolated from other debts.

Think of it this way: Isolation Mode says "we don't fully trust this collateral." Siloed borrowing says "we don't fully trust this borrowed asset."

### When Is Siloed Borrowing Used?

Governance typically applies siloed borrowing to assets with one or more of these characteristics:

- Rebasing mechanics (balance changes without transfers)
- Transfer fees or taxes
- Very low or fragmented liquidity
- Non-standard ERC-20 behavior
- Novel economic mechanisms that complicate liquidation

GHO itself is a notable example --- it is siloed because its minting/burning mechanics differ from pool-based borrowing, and mixing GHO debt with regular pool debt in the same position would complicate the risk model.

---

## 3. Repay with aTokens: Unwinding Positions Efficiently

### The Scenario

You supplied 10,000 USDC to Aave and received 10,000 aUSDC. Later, you borrowed 5,000 USDC. Your position:

- **Assets**: 10,000 aUSDC (earning interest)
- **Liabilities**: 5,000 variable debt USDC (accruing interest)

You want to close the borrow. The normal path requires two transactions:
1. Withdraw 5,000 USDC (burn aUSDC, receive USDC)
2. Repay 5,000 USDC (send USDC back to the protocol)

This is wasteful. Two transactions, two gas fees, and you temporarily hold USDC in your wallet for no economic reason. The USDC leaves the protocol only to immediately re-enter it.

### The Efficient Alternative

Repay with aTokens collapses this into a single step. When you call `repayWithATokens()`:

1. The protocol burns 5,000 of your aUSDC (reducing your supply position)
2. The protocol burns 5,000 of your variable debt tokens (eliminating your debt)
3. **No underlying USDC moves anywhere**

No tokens leave the protocol. No ERC-20 transfers of the underlying asset occur. The protocol simply cancels your deposit against your debt. It is an accounting operation, not a funds transfer.

### Why No Tokens Need to Move

The underlying USDC was already sitting in the aToken contract. Your aUSDC represented a claim on that USDC. Your debt represented an obligation to return USDC. By burning both simultaneously, the claim and the obligation cancel out. The USDC stays in the pool, available for other borrowers.

### When This Is Especially Useful

**Unwinding leveraged positions.** If you have been looping (supply, borrow, re-supply, borrow more) to create a leveraged position, repay-with-aTokens is the cleanest way to peel off each layer. One transaction per layer instead of two.

**When you do not hold the underlying.** If all your USDC is deposited as aUSDC, you may not have any USDC in your wallet. Repay-with-aTokens lets you repay without needing to withdraw first.

**Gas savings.** One transaction instead of two, and no ERC-20 transfer or approval needed for the underlying token.

### Example with Numbers

Before repay-with-aTokens:

| Position | Amount |
|---|---|
| aUSDC balance | 10,000 |
| Variable debt USDC | 5,000 |
| Net position | 5,000 (net supplier) |

After repaying 5,000 debt with aTokens:

| Position | Amount |
|---|---|
| aUSDC balance | 5,000 |
| Variable debt USDC | 0 |
| Net position | 5,000 (net supplier) |

The net position is identical. But the debt is gone and the user's position is simpler and cleaner.

### Limitations

**Same asset only.** You can only use aUSDC to repay USDC debt, aWETH to repay WETH debt, and so on. You cannot cross assets --- aUSDC cannot repay WETH debt.

**Self-only.** You can only burn your own aTokens to repay your own debt. Unlike normal `repay()`, where you can repay on behalf of another user, `repayWithATokens()` is restricted to the caller.

**Reduces collateral.** Burning aTokens reduces your supply position, which may reduce your collateral. If the repayment would leave you with insufficient collateral for your remaining borrows, the transaction reverts --- the health factor check still applies. You cannot use this to put yourself into a liquidatable state.

**No effect on pool liquidity.** Normal repayment adds liquidity to the pool (the underlying tokens flow back in). Repay-with-aTokens does not add liquidity --- it reduces both supply and debt by the same amount. This means the utilization rate may change differently than with a normal repay, which slightly affects interest rates.

---

## 4. The Economics of Risk Parameterization

Before looking at how these features compose, it is worth stepping back to consider the economic trade-offs governance faces when setting these parameters.

### The Listing Dilemma

Every new asset listing is a trade-off between growth and risk. Listing an asset attracts new users and capital (more supply, more borrowing, more revenue). But every asset also introduces tail risk --- the chance of a black swan event (oracle manipulation, sudden liquidity collapse, smart contract exploit) that creates bad debt.

Without caps and siloed borrowing, governance would face a binary choice: list the asset with full exposure (risky) or don't list it at all (missed revenue). With these features, governance can list assets on a spectrum:

| Risk Tier | Configuration | Example |
|---|---|---|
| Tier 1: Blue chip | High caps, no silo, collateral-enabled, E-Mode eligible | ETH, USDC |
| Tier 2: Established | Moderate caps, no silo, collateral-enabled | LINK, AAVE |
| Tier 3: Volatile | Low caps, possibly siloed, collateral-enabled with low LTV | CRV, MKR |
| Tier 4: Exotic | Very low caps, siloed, isolated collateral, high reserve factor | New governance tokens |

This tiered approach means Aave can list hundreds of assets --- generating revenue and attracting users from every corner of DeFi --- while containing the risk of each asset to a level governance is comfortable with.

### The Revenue Angle

Risk parameters also interact with revenue. Higher reserve factors on risky assets mean the protocol earns more per dollar of borrowing from those assets. Higher liquidation protocol fees on volatile assets mean the protocol earns more during the market stress events that those assets are likely to trigger. The risk management system is simultaneously a revenue optimization system.

---

## 5. How These Features Work Together

The three features in this chapter, combined with Isolation Mode (Chapter 10), E-Mode (Chapter 9), and the liquidation mechanism (Chapter 7), give governance a complete toolkit for managing risk at the individual asset level:

| Risk Concern | Feature | How It Helps |
|---|---|---|
| Too much of one asset in the protocol | Supply cap | Hard limit on total deposits |
| Too much borrowing of one asset | Borrow cap | Hard limit on total borrows |
| Complex debt interactions | Siloed borrowing | Risky debt cannot mix with other debts |
| Risky collateral | Isolation Mode | Limits debt backed by risky collateral |
| Correlated assets needing better terms | E-Mode | Higher LTV for similar assets |
| Inefficient position unwinding | Repay with aTokens | One-step debt cancellation |

Each asset can be independently tuned: capped to limit exposure, siloed to prevent complex debt interactions, isolated to limit collateral risk, and grouped with similar assets in E-Mode for better capital efficiency. The result is a protocol flexible enough to list hundreds of assets while remaining robust against the tail risks of any individual one.

---

## Summary

Aave V3's additional risk features are targeted guardrails:

- **Supply and borrow caps** prevent concentration risk by limiting how much of any single asset can enter the protocol. Governance sizes caps based on liquidity depth, volatility, and oracle reliability.
- **Siloed borrowing** quarantines risky debt. Assets with unusual mechanics (rebasing, transfer fees, low liquidity) are flagged so they cannot be borrowed alongside other assets, simplifying risk modeling and liquidation.
- **Repay with aTokens** is an efficiency feature: cancel your deposit against your debt in one step, with no token transfers. Useful for unwinding leveraged positions and saving gas.

Together with Isolation Mode and E-Mode from earlier chapters, these features form a layered risk management system where each asset can be independently constrained according to its unique risk profile.
