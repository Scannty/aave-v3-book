# Chapter 6: Supply, Borrow, Repay, and Withdraw - The Four Core Operations

The previous chapters introduced the building blocks: interest rate models (Chapter 2), indexes and scaled balances (Chapter 3), aTokens (Chapter 4), and debt tokens (Chapter 5). This chapter ties them together by walking through the lifecycle of a lending position - from supplying assets to earning interest to borrowing, repaying, and withdrawing.

Every operation in Aave V3 follows the same rhythm:

1. Settle all pending interest (bring indexes up to date)
2. Validate the action (can this user do this?)
3. Execute the action (move tokens, mint or burn)
4. Recalculate interest rates (because supply/demand just changed)

Understanding this rhythm is more important than understanding any individual line of code.

---

## The Lifecycle of a Lending Position

Before diving into each operation, here is the big picture. A typical user journey looks like this:

```
1. SUPPLY    →  Deposit USDC, receive aUSDC, start earning interest
2. EARN      →  aUSDC balance grows every second (no action needed)
3. BORROW    →  Post aUSDC as collateral, borrow ETH, pay interest
4. REPAY     →  Return borrowed ETH, debt tokens burn
5. WITHDRAW  →  Redeem aUSDC for USDC (original deposit + interest)
```

Each step changes the protocol's supply-demand balance, which in turn moves interest rates for everyone. When you supply, you add liquidity and push rates down. When you borrow, you remove liquidity and push rates up. The protocol continuously adjusts to find equilibrium.

---

## Supply: Depositing Assets into the Pool

```solidity
function supply(address asset, uint256 amount, address onBehalfOf, uint16 referralCode) external;
```

<video src="animations/final/supply_flow.webm" controls autoplay loop muted playsinline style="width:100%;max-width:800px;border-radius:8px;margin:20px 0"></video>

### What Happens Economically

When you supply 1,000 USDC to Aave:

1. Your USDC leaves your wallet and enters the protocol's vault (the aToken contract)
2. You receive aUSDC in return - a receipt that earns interest
3. Your aUSDC is automatically enabled as collateral (if eligible and it is your first deposit of this asset)
4. Interest rates for USDC adjust downward slightly, because there is now more liquidity available

From this moment, you are earning interest. Your aUSDC balance increases every second. You can hold it, transfer it, use it as collateral, or redeem it at any time.

### The Flow Step by Step

**Step 1: Update state.** Before anything else, the protocol settles all pending interest by updating the liquidity index and variable borrow index. This ensures the correct number of scaled aTokens will be minted. If the index were stale, you would receive too many or too few tokens.

**Step 2: Validate.** The protocol checks several conditions:

```solidity
function validateSupply(DataTypes.ReserveCache memory reserveCache, uint256 amount, uint256 supplyCap) internal view {
    require(amount != 0, Errors.INVALID_AMOUNT);
    require(reserveCache.reserveConfiguration.getActive(), Errors.RESERVE_INACTIVE);
    require(!reserveCache.reserveConfiguration.getPaused(), Errors.RESERVE_PAUSED);
    require(!reserveCache.reserveConfiguration.getFrozen(), Errors.RESERVE_FROZEN);

    if (supplyCap != 0) {
        require(
            (IAToken(reserveCache.aTokenAddress).scaledTotalSupply().rayMul(reserveCache.nextLiquidityIndex) + amount)
                <= supplyCap * (10 ** reserveCache.reserveConfiguration.getDecimals()),
            Errors.SUPPLY_CAP_EXCEEDED
        );
    }
}
```

Supply caps are a V3 innovation. They prevent any single asset from dominating the protocol's risk exposure. If the USDC supply cap is \$500M and there is already \$499M deposited, you can deposit at most \$1M more.

**Step 3: Update interest rates.** Adding liquidity decreases utilization, which typically decreases borrow and supply rates. The protocol recalculates rates now, using the new liquidity level.

**Step 4: Transfer underlying.** Your USDC moves from your wallet to the aToken contract via `safeTransferFrom`. The aToken contract is the vault - it holds all the underlying assets for that reserve.

Note: the caller (`msg.sender`) always sends the tokens, even if the aTokens are being minted to a different address via the `onBehalfOf` parameter. This enables zap contracts and other integrations where one contract deposits on behalf of a user.

**Step 5: Mint aTokens.** The protocol mints scaled aTokens to the recipient:

```solidity
IERC20(params.asset).safeTransferFrom(msg.sender, reserveCache.aTokenAddress, params.amount);

bool isFirstSupply = IAToken(reserveCache.aTokenAddress).mint(
    msg.sender, params.onBehalfOf, params.amount, reserveCache.nextLiquidityIndex
);
```

As covered in Chapter 4, `mint()` stores `amount / liquidityIndex` and your `balanceOf()` immediately reflects the full deposited amount.

**Step 6: Auto-enable as collateral.** If this is your first deposit of this asset, the protocol checks whether it is eligible for collateral use (non-zero LTV, compatible with isolation mode, etc.) and automatically enables it. This saves users a separate transaction.

### Numerical Example

You supply 10,000 USDC. The current liquidity index is 1.03. The supply cap is 100M USDC, and current deposits total 45M.

- Validation: 10,000 < 55M remaining cap - passes
- Scaled aTokens minted: 10,000 / 1.03 = 9,708.74
- Your `balanceOf()`: 9,708.74 × 1.03 = 10,000.00 aUSDC
- After one year at 3% APY: 9,708.74 × 1.0609 = 10,300.00 aUSDC

---

## Borrow: Taking a Loan Against Your Collateral

```solidity
function borrow(
    address asset, uint256 amount, uint256 interestRateMode, uint16 referralCode, address onBehalfOf
) external;
```

<video src="animations/final/borrow_flow.webm" controls autoplay loop muted playsinline style="width:100%;max-width:800px;border-radius:8px;margin:20px 0"></video>

### What Happens Economically

Borrowing is the most scrutinized operation in the protocol. When you borrow:

1. You are taking assets from the pool - assets that belong to depositors
2. You are creating an obligation (debt) that grows with interest
3. Your existing deposits serve as collateral guaranteeing you will repay
4. If your collateral value drops too far relative to your debt, you can be liquidated

The protocol must ensure, at the moment of borrowing, that you have enough collateral to safely cover the new debt. This is the **health factor check** - the single most important safety mechanism in the protocol.

### The Health Factor

Before any borrow is approved, the protocol computes:

$$HF = \frac{\sum(collateral_i \times price_i \times liqThreshold_i)}{totalDebt}$$

All values are converted to a common base currency (typically USD) using oracle prices. The **liquidation threshold** is a per-asset parameter (e.g., 85% for ETH) that reflects how much of the collateral's value is considered "safe."

The health factor must remain above 1.0 after the new borrow. If it would not, the transaction reverts.

### Example: The Health Factor in Action

You have deposited 10 ETH (worth \$20,000). ETH has a liquidation threshold of 85%.

$$\$20{,}000 \times 85\% = \$17{,}000$$

You want to borrow 10,000 USDC:

$$HF = \frac{\$17{,}000}{\$10{,}000} = 1.70 \quad \checkmark \text{ (above 1.0 - borrow allowed)}$$

You want to borrow 16,000 USDC:

$$HF = \frac{\$17{,}000}{\$16{,}000} = 1.0625 \quad \checkmark \text{ (barely above 1.0 - risky but allowed)}$$

You want to borrow 18,000 USDC:

$$HF = \frac{\$17{,}000}{\$18{,}000} = 0.944 \quad \times \text{ (below 1.0 - borrow rejected)}$$

The protocol also checks against the **LTV (Loan-to-Value)** ratio, which is typically lower than the liquidation threshold. LTV determines the maximum you can borrow; liquidation threshold determines when you get liquidated. The gap between them provides a buffer.

### The Flow Step by Step

**Step 1: Update state.** Same as supply - settle pending interest, update indexes.

**Step 2: Validate.** This is the most complex validation in the protocol:

```solidity
function validateBorrow(/* params */) internal view {
    require(params.amount != 0, Errors.INVALID_AMOUNT);
    require(reserveCache.reserveConfiguration.getActive(), Errors.RESERVE_INACTIVE);
    require(!reserveCache.reserveConfiguration.getPaused(), Errors.RESERVE_PAUSED);
    require(reserveCache.reserveConfiguration.getBorrowingEnabled(), Errors.BORROWING_NOT_ENABLED);

    // Borrow cap check
    if (vars.borrowCap != 0) {
        require(
            vars.totalDebt + params.amount <= vars.borrowCap * (10 ** vars.decimals),
            Errors.BORROW_CAP_EXCEEDED
        );
    }

    // Health factor and LTV check after the new borrow
    require(vars.userCollateralInBaseCurrency != 0, Errors.COLLATERAL_BALANCE_IS_ZERO);
    require(vars.healthFactor > HEALTH_FACTOR_LIQUIDATION_THRESHOLD, Errors.HEALTH_FACTOR_LOWER_THAN_LIQUIDATION_THRESHOLD);
    require(
        vars.totalDebtInBaseCurrency + vars.amountInBaseCurrency <= vars.collateralNeededInBaseCurrency,
        Errors.COLLATERAL_CANNOT_COVER_NEW_BORROW
    );
}
```

If the user is borrowing via **delegation** (someone else's collateral), the protocol also checks that the delegator has granted sufficient borrow allowance.

**Step 3: Mint debt tokens.** For variable borrows (the standard path), scaled debt tokens are minted: `borrowAmount / variableBorrowIndex`. For stable borrows (deprecated on most deployments), the user's personal rate is recorded and the principal is stored directly.

**Step 4: Update interest rates.** Borrowing removes liquidity from the pool, increasing utilization. Rates go up.

**Step 5: Transfer underlying to borrower.** The borrowed assets are transferred from the aToken contract (the vault) to the borrower's wallet.

### Isolation Mode

Aave V3 introduced **isolation mode** for newly listed or riskier assets. When a user's only collateral is an isolated asset, they can only borrow specific stablecoins up to a debt ceiling. This prevents a risky collateral asset from being used to borrow unlimited amounts.

The borrow flow checks isolation mode constraints and tracks the isolated asset's total debt against its ceiling.

---

## Repay: Returning What You Borrowed

```solidity
function repay(address asset, uint256 amount, uint256 interestRateMode, address onBehalfOf) external returns (uint256);
```

<video src="animations/final/repay_withdraw.webm" controls autoplay loop muted playsinline style="width:100%;max-width:800px;border-radius:8px;margin:20px 0"></video>

### What Happens Economically

Repaying is conceptually simple: you return borrowed assets to the pool, and your debt decreases. Interest rates adjust downward because utilization decreases.

But there are practical nuances that the protocol must handle.

### The Full-Repay Problem

How do you repay your *exact* debt when interest accrues every second? By the time your transaction is mined, your debt may be a few cents higher than when you submitted it.

Aave solves this elegantly: pass `type(uint256).max` as the repay amount. The protocol interprets this as "repay everything I owe":

```solidity
uint256 paybackAmount = variableDebt;

if (params.amount < paybackAmount) {
    paybackAmount = params.amount;  // Partial repay
}
```

It reads your exact debt at execution time and transfers only that amount - not the maximum. You just need to have approved enough tokens.

For partial repayment, just pass the specific amount. The protocol will burn debt tokens proportional to what you repay.

### The Flow Step by Step

**Step 1: Update state.** Settle pending interest, update indexes.

**Step 2: Determine the actual repay amount.** Read the borrower's current debt (which includes all accrued interest as of this second), then cap the repay amount to the lesser of what the user specified and the actual debt.

**Step 3: Validate.** Checks are minimal compared to borrowing:

```solidity
function validateRepay(DataTypes.ReserveCache memory reserveCache, uint256 amountSent, uint256 variableDebt) internal view {
    require(amountSent != 0, Errors.INVALID_AMOUNT);
    require(amountSent != type(uint256).max || msg.sender == onBehalfOf, Errors.NO_EXPLICIT_AMOUNT_TO_REPAY_ON_BEHALF);
    require(variableDebt != 0, Errors.NO_DEBT_OF_SELECTED_TYPE);
    require(reserveCache.reserveConfiguration.getActive(), Errors.RESERVE_INACTIVE);
}
```

No health factor check - repaying debt always improves (or maintains) the user's position. The protocol also allows anyone to repay on behalf of someone else - there is no security risk in reducing someone's debt.

**Step 4: Burn debt tokens.** The protocol burns `repayAmount / currentIndex` in scaled terms from the borrower's address.

**Step 5: Update interest rates.** Repaying adds liquidity back to the pool (the repaid assets go to the aToken vault), decreasing utilization and rates.

**Step 6: Transfer underlying from repayer to vault.** The repaid assets move from the repayer's wallet to the aToken contract.

**Step 7: Clear borrow flag if fully repaid.** If the user's total debt (variable + stable) drops to zero, the protocol clears their borrowing flag in the user configuration bitmap. This is a gas optimization that speeds up future health factor calculations.

### Repay With aTokens

Aave V3 offers a neat shortcut: **repay using your aTokens** instead of holding the underlying asset. If you supplied 5,000 USDC and borrowed 1,000 USDC, you can repay the 1,000 USDC debt by burning 1,000 aUSDC - without needing any USDC in your wallet.

In this flow, the protocol burns aTokens from the repayer instead of pulling underlying tokens. The debt tokens are burned as usual. It is equivalent to withdrawing and then repaying in a single atomic step, saving gas and complexity.

---

## Withdraw: Redeeming Your Deposit

```solidity
function withdraw(address asset, uint256 amount, address to) external returns (uint256);
```

### What Happens Economically

Withdrawing is the reverse of supplying: you return aTokens to the protocol and receive your underlying assets (original deposit plus interest).

$$\text{Deposited } \$10{,}000 \text{ USDC 6 months ago at } {\sim}3\% \text{ APY}$$

$$\text{aUSDC balance now} = 10{,}150 \implies \text{withdraw } 10{,}150 \text{ aUSDC, receive } 10{,}150 \text{ USDC}$$

Like repaying, you can pass `type(uint256).max` to withdraw everything.

### The Health Factor Check: Why Withdrawals Can Fail

Here is the critical difference between withdrawals and supplies: if you have active borrows, withdrawing collateral reduces the backing for your debt. The protocol must prevent you from creating an undercollateralized position.

**Example:** You have 10 ETH (\$20,000) as collateral and 12,000 USDC borrowed.

$$HF = \frac{\$20{,}000 \times 85\%}{\$12{,}000} = 1.42 \quad \checkmark$$

You try to withdraw 5 ETH (\$10,000):

$$HF = \frac{\$10{,}000 \times 85\%}{\$12{,}000} = 0.71 \quad \times \text{ REVERTS}$$

The protocol computes the post-withdrawal health factor and rejects the transaction if it would drop to or below 1.0. You cannot extract collateral that is actively supporting debt.

If you have **no borrows**, you can withdraw freely. The health factor check only applies when debt exists.

### The Flow Step by Step

**Step 1: Update state.** Settle pending interest, update indexes.

**Step 2: Determine withdraw amount.** Read the user's current aToken balance. If they passed `type(uint256).max`, withdraw everything.

**Step 3: Validate.** Basic checks:

```solidity
function validateWithdraw(DataTypes.ReserveCache memory reserveCache, uint256 amount, uint256 userBalance) internal view {
    require(amount != 0, Errors.INVALID_AMOUNT);
    require(amount <= userBalance, Errors.NOT_ENOUGH_AVAILABLE_USER_BALANCE);
    require(reserveCache.reserveConfiguration.getActive(), Errors.RESERVE_INACTIVE);
}
```

**Step 4: Update interest rates.** Withdrawing removes liquidity, increasing utilization and rates.

**Step 5: Burn aTokens and transfer underlying.** The protocol burns `withdrawAmount / currentIndex` scaled aTokens and transfers the underlying assets from the aToken contract to the user.

**Step 6: Disable as collateral if fully withdrawn.** If the user withdrew their entire position, the collateral flag is cleared.

**Step 7: Validate health factor.** If the user has any active borrows, the protocol computes the health factor after the withdrawal. If it would be at or below 1.0, the entire transaction reverts. This check happens *after* the burn, not before, so the protocol validates the final state.

---

## The "Update State Then Update Rates" Pattern

Every operation in Aave V3 follows the same bookkeeping pattern. Understanding it conceptually is more important than reading the code.

### Why State Must Be Updated First

Before any token operation, the protocol must bring its indexes up to date. Indexes represent accumulated interest since the protocol's inception. If the last interaction with a reserve was 10 minutes ago, those 10 minutes of interest need to be calculated and added to the indexes.

Why? Because minting and burning depend on the current index:

$$scaledTokens = \frac{amount}{currentIndex}$$

A stale index means minting or burning the wrong number of scaled tokens. This would create an accounting error that compounds over time. Even a tiny error, accumulated across millions of transactions, could create a serious discrepancy.

The state update also accrues treasury revenue. If skipped, the protocol would miss its share of interest for the elapsed period.

### Why Rates Must Be Updated Last

After the operation executes, the reserve's supply-demand balance has changed:

| Operation | What Changed                  | Utilization | Rates      |
|-----------|------------------------------|-------------|------------|
| Supply    | More liquidity available      | Decreases   | Go down    |
| Borrow    | Less liquidity, more debt     | Increases   | Go up      |
| Repay     | Less debt, more liquidity     | Decreases   | Go down    |
| Withdraw  | Less liquidity available      | Increases   | Go up      |

The rates must be recalculated to reflect the new reality. These new rates are stored and used by the *next* state update to compute how much interest accrues over the intervening period.

### The Feedback Loop

This creates a self-correcting cycle:

```
State update → uses stored rates to compute interest for elapsed time
     ↓
Execute operation → changes supply and/or demand
     ↓
Rate update → computes new rates based on new utilization
     ↓
(time passes, no one interacts)
     ↓
Next state update → uses those rates to compute interest for elapsed time
```

If no one interacts with a reserve for hours or days, no problem. The first interaction catches up all accumulated interest in one shot. The indexes "jump" to account for the elapsed time at the stored rates. There is no "missed interest" problem.

### Why This Design Is Robust

1. **No stale data.** Every operation starts with fresh indexes. There is no window where incorrect values can cause wrong calculations.

2. **Atomic consistency.** All changes (indexes, rates, balances, treasury) happen within a single transaction. No intermediate state is visible to other transactions.

3. **Self-correcting.** Idle reserves catch up automatically on the next interaction. Active reserves update every time someone touches them.

4. **Simple for integrators.** A single call to `supply()`, `borrow()`, `repay()`, or `withdraw()` handles all internal bookkeeping. External protocols do not need to call `updateState()` separately.

---

## What the Protocol Prevents: A Summary of Safety Checks

Across all four operations, the protocol enforces these invariants:

| Invariant                                   | Enforced During           |
|--------------------------------------------|--------------------------|
| Cannot deposit into inactive/paused reserve | Supply                   |
| Cannot exceed supply cap                    | Supply                   |
| Cannot borrow without sufficient collateral | Borrow                   |
| Health factor must stay above 1.0           | Borrow, Withdraw, Transfer |
| Cannot exceed borrow cap                    | Borrow                   |
| Cannot borrow from supply-only assets       | Borrow                   |
| Cannot withdraw more than you have          | Withdraw                 |
| Cannot repay more than you owe              | Repay (amount is capped) |
| Debt tokens cannot be transferred           | Always                   |
| Only the Pool can mint/burn tokens          | Always                   |

These checks make Aave a **permissionless but safe** protocol. Anyone can supply, borrow, repay, or withdraw at any time, but the protocol will never allow an action that would compromise its solvency.

---

## Summary

This chapter walked through the four core operations that make Aave V3 function as a lending protocol.

**Key takeaways:**

- **Supply** deposits assets into the vault, mints aTokens, and auto-enables collateral. Rates decrease because utilization drops.

- **Borrow** is the most heavily validated operation. The protocol checks health factor, LTV limits, borrow caps, and isolation mode constraints before minting debt tokens and releasing funds. Rates increase because utilization rises.

- **Repay** burns debt tokens and returns assets to the vault. The `type(uint256).max` pattern solves the problem of repaying exact debt when interest accrues every second. Anyone can repay on behalf of anyone else.

- **Withdraw** burns aTokens and sends underlying assets to the user. If the user has active borrows, the health factor is checked *after* the burn to ensure the position remains solvent.

- **Every operation follows the same rhythm:** update state first (settle interest), execute the action, update rates last (recalculate for new utilization). This pattern ensures consistency, prevents stale-data bugs, and makes idle reserves self-correcting.

- **The protocol is permissionless but safe.** Anyone can interact at any time, but every action is validated against solvency constraints. You cannot create a position that puts the protocol at risk.

These four operations, combined with the accounting primitives from previous chapters, form the core lending engine of Aave V3. The next chapter covers what happens when things go wrong: **liquidations**.
