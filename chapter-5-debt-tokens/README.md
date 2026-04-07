# Chapter 5: Debt Tokens --- Variable and Stable

In the previous chapter, we saw how aTokens represent a user's supply position using the scaled balance pattern. Debt tokens are the mirror image: they represent what a user **owes**. When you borrow from Aave V3, you do not just receive tokens and a database entry. You receive debt tokens --- on-chain ERC-20-shaped tokens that track your obligation to the protocol.

This chapter covers how both `VariableDebtToken` and `StableDebtToken` work, why they are non-transferable, and how mint/burn flows connect to the broader borrow and repay lifecycle.

---

## What Are Debt Tokens?

Every reserve in Aave V3 has up to two debt token contracts deployed alongside its aToken:

| Token Type         | Contract              | Tracks                     |
|-------------------|-----------------------|----------------------------|
| Variable debt     | `VariableDebtToken`   | Debt at the floating rate  |
| Stable debt       | `StableDebtToken`     | Debt at a locked-in rate   |

When a user borrows 1000 USDC at the variable rate, the protocol mints 1000 variable debt tokens to the borrower's address. These tokens represent the borrower's obligation. As interest accrues, the `balanceOf()` on those debt tokens increases --- just like aTokens, but on the liability side.

When the borrower repays, debt tokens are burned. Full repayment burns all debt tokens. Partial repayment burns a proportional amount.

The core lifecycle:

```
Borrow:  Pool → BorrowLogic → DebtToken.mint() → debt tokens appear in borrower's wallet
Repay:   Pool → BorrowLogic → DebtToken.burn() → debt tokens disappear
```

Debt tokens serve three purposes:

1. **On-chain accounting**: The protocol can compute exactly how much any user owes by calling `balanceOf()` on the debt token.
2. **Indexing and analytics**: Transfer events emitted on mint/burn allow off-chain systems (subgraphs, block explorers) to track borrowing activity.
3. **Integration surface**: Other contracts can read a user's debt position via standard ERC-20 interfaces without needing to understand Aave's internal storage.

---

## Why Debt Tokens Are Non-Transferable

This is one of the most important design decisions in Aave. Debt tokens implement the ERC-20 interface, but the `transfer()` and `transferFrom()` functions always revert:

```solidity
function transfer(address, uint256) external virtual override returns (bool) {
    revert(Errors.OPERATION_NOT_SUPPORTED);
}

function transferFrom(
    address,
    address,
    uint256
) external virtual override returns (bool) {
    revert(Errors.OPERATION_NOT_SUPPORTED);
}

function approve(address, uint256) external virtual override returns (bool) {
    revert(Errors.OPERATION_NOT_SUPPORTED);
}

function allowance(
    address,
    address
) external view virtual override returns (uint256) {
    return 0;
}
```

Why? Because debt is an obligation backed by collateral. If debt tokens were transferable, a malicious user could:

1. Deposit collateral and borrow assets.
2. Transfer the debt tokens to a random address (or a contract with no collateral).
3. Walk away with the borrowed assets, leaving unbacked debt in the protocol.

The recipient of the debt tokens would have no collateral to cover the position, and there would be no way to liquidate them. The protocol would be instantly insolvent.

By making debt tokens non-transferable, Aave ensures that the borrower who minted the debt is always the one responsible for it. The collateral backing that debt stays linked to the same account.

The ERC-20 interface is still implemented (rather than using a completely custom interface) because it gives you `balanceOf()`, `totalSupply()`, and Transfer events. These are useful for off-chain tracking and for other contracts that want to read debt balances. The interface is kept; only the mutation functions are blocked.

---

## VariableDebtToken

The `VariableDebtToken` uses exactly the same scaled balance pattern as the aToken, but with the **variable borrow index** instead of the liquidity index.

### How balanceOf Works

```solidity
function balanceOf(address user) public view virtual override returns (uint256) {
    uint256 scaledBalance = super.balanceOf(user);

    if (scaledBalance == 0) {
        return 0;
    }

    return scaledBalance.rayMul(
        POOL.getReserveNormalizedVariableDebt(_underlyingAsset)
    );
}
```

This is the debt-side mirror of the aToken's `balanceOf()`:

- `super.balanceOf(user)` returns the **scaled balance** --- the raw stored value.
- `POOL.getReserveNormalizedVariableDebt()` returns the current variable borrow index (projected to the current timestamp, just like `getReserveNormalizedIncome()` does for the liquidity index).
- The result is the user's **actual debt** --- their original borrow amount plus all accrued interest.

### getReserveNormalizedVariableDebt

This is the borrow-side equivalent of `getReserveNormalizedIncome()`:

```solidity
function getReserveNormalizedVariableDebt(
    address asset
) external view override returns (uint256) {
    DataTypes.ReserveData storage reserve = _reserves[asset];

    uint40 timestamp = reserve.lastUpdateTimestamp;
    if (timestamp == block.timestamp) {
        return reserve.variableBorrowIndex;
    }

    uint256 cumulated = MathUtils.calculateCompoundedInterest(
        reserve.currentVariableBorrowRate,
        timestamp
    );
    return cumulated.rayMul(reserve.variableBorrowIndex);
}
```

Note the key difference from the supply side: this uses **compound interest** (`calculateCompoundedInterest`) rather than linear interest. As explained in Chapter 3, borrow-side interest is compounded because borrow rates are higher and precision matters more for debt tracking.

### scaledBalanceOf

Returns the raw stored balance without any index multiplication:

```solidity
function scaledBalanceOf(address user) public view virtual override returns (uint256) {
    return super.balanceOf(user);
}
```

This is the "principal-equivalent" value --- the user's borrow amount normalized to the index at the time they borrowed.

### totalSupply and scaledTotalSupply

```solidity
function totalSupply() public view virtual override returns (uint256) {
    return super.totalSupply().rayMul(
        POOL.getReserveNormalizedVariableDebt(_underlyingAsset)
    );
}

function scaledTotalSupply() public view virtual override returns (uint256) {
    return super.totalSupply();
}
```

The `totalSupply()` returns the total variable debt across all borrowers, with interest accrued up to the current second. The `scaledTotalSupply()` returns the raw stored value.

### Numerical Example

Alice borrows 1000 USDC when the variable borrow index is `1.02`:

```
scaledDebt(Alice) = 1000 / 1.02 = 980.39
```

Time passes. The variable borrow index grows to `1.08`:

```
balanceOf(Alice) = 980.39 * 1.08 = 1058.82 USDC
```

Alice now owes 1058.82 USDC. The 58.82 USDC of interest accrued without any transaction. The mechanism is identical to aTokens --- only the index used is different.

### Quick Reference

| Function              | Returns                      | Uses Index? |
|-----------------------|------------------------------|-------------|
| `balanceOf(user)`     | Actual debt with interest    | Yes (variable borrow index) |
| `totalSupply()`       | Total variable debt          | Yes |
| `scaledBalanceOf(user)` | Raw stored (scaled) debt   | No |
| `scaledTotalSupply()` | Raw stored total debt        | No |

---

## StableDebtToken

The `StableDebtToken` is significantly more complex than the variable debt token. Instead of using a shared, continuously-updating index, each user **locks in a stable rate** at the time they borrow. Their debt compounds individually based on that locked rate.

### Per-User Rate Tracking

When a user borrows at the stable rate, the protocol records their individual rate in the user state:

```solidity
// In StableDebtToken
// _userState[user].additionalData stores the user's stable rate
```

The `_userState` mapping comes from `IncentivizedERC20`. For variable debt tokens, `additionalData` stores the last-updated index (like aTokens). For stable debt tokens, it stores the **user's personal stable borrow rate**.

### How balanceOf Works

Unlike the variable debt token (which multiplies by a global index), the stable debt token computes compound interest individually for each user:

```solidity
function balanceOf(address account) public view virtual override returns (uint256) {
    uint256 accountBalance = super.balanceOf(account);
    uint256 stableRate = _userState[account].additionalData;

    if (accountBalance == 0) {
        return 0;
    }

    uint256 cumulatedInterest = MathUtils.calculateCompoundedInterest(
        stableRate,
        _timestamps[account]
    );

    return accountBalance.rayMul(cumulatedInterest);
}
```

Breaking this down:

- `super.balanceOf(account)` returns the **principal** --- the amount originally borrowed (not a scaled balance like variable debt).
- `stableRate` is the rate locked in at borrow time, stored in `additionalData`.
- `_timestamps[account]` is the timestamp of the user's last stable borrow or rebalance.
- `calculateCompoundedInterest` computes `(1 + stableRate)^timeDelta` using the Taylor expansion from Chapter 3.

The result is `principal * (1 + rate)^timeDelta` --- standard compound interest, applied per-user.

This is fundamentally different from the variable debt model. Variable debt uses a shared index that everyone multiplies by. Stable debt computes interest individually because each user can have a different rate.

### The Average Stable Rate

Since each user can have a different stable rate, the protocol also tracks a **weighted average stable rate** across all stable borrowers. This average rate is needed for the interest rate model --- the total interest generated by stable borrowers feeds into the reserve's overall utilization and rate calculations.

```solidity
function getAverageStableRate() external view virtual override returns (uint256) {
    return _avgStableRate;
}
```

When a user borrows at a stable rate, the average is updated:

```solidity
// Simplified from the mint logic
uint256 currentAvgStableRate = _avgStableRate;

_avgStableRate = (
    (currentAvgStableRate.rayMul(previousSupply))
    + (rate.rayMul(amount))
).rayDiv(nextSupply);
```

This is a weighted average: `newAvg = (oldAvg * oldSupply + newRate * newAmount) / newSupply`.

### Mint Flow

When a user borrows at the stable rate, `StableDebtToken.mint()` is called:

```solidity
function mint(
    address user,
    address onBehalfOf,
    uint256 amount,
    uint256 rate
) external virtual override onlyPool returns (bool, uint256, uint256) {
    MintLocalVars memory vars;

    if (user != onBehalfOf) {
        _decreaseBorrowAllowance(onBehalfOf, user, amount);
    }

    (, uint256 currentBalance, uint256 balanceIncrease) = _calculateBalanceIncrease(
        onBehalfOf
    );

    vars.previousSupply = totalSupply();
    vars.currentAvgStableRate = _avgStableRate;
    vars.nextSupply = vars.previousSupply + amount;

    vars.currentStableRate = _userState[onBehalfOf].additionalData;

    // Compute new weighted average for this user
    vars.nextStableRate = (
        vars.currentStableRate.rayMul(currentBalance.wadToRay())
        + rate.rayMul(amount.wadToRay())
    ).rayDiv((currentBalance + amount).wadToRay());

    _userState[onBehalfOf].additionalData = vars.nextStableRate.toUint128();

    // Update the global average stable rate
    _avgStableRate = (
        (vars.currentAvgStableRate.rayMul(vars.previousSupply.wadToRay()))
        + (rate.rayMul(amount.wadToRay()))
    ).rayDiv(vars.nextSupply.wadToRay()).toUint128();

    _mint(onBehalfOf, (amount + balanceIncrease).toUint128());

    // Update timestamp for the user
    _timestamps[onBehalfOf] = uint40(block.timestamp);

    emit Transfer(address(0), onBehalfOf, amount + balanceIncrease);
    emit Mint(
        user,
        onBehalfOf,
        amount + balanceIncrease,
        currentBalance,
        balanceIncrease,
        vars.nextStableRate,
        _avgStableRate,
        vars.nextSupply
    );

    return (currentBalance == 0, vars.nextSupply, _avgStableRate);
}
```

Key details:

1. **The stored balance is principal, not scaled**: Unlike variable debt, the stable debt token stores the actual principal. When the user borrows more, it adds the accrued interest (`balanceIncrease`) to the stored balance and resets the timestamp.

2. **Per-user rate blending**: If a user already has a stable borrow and takes another, their rate is blended: `newRate = (oldRate * oldBalance + currentRate * newAmount) / totalBalance`.

3. **Global average update**: The protocol-wide average stable rate is updated to include the new borrow.

4. **Timestamp reset**: The user's timestamp is set to `block.timestamp`. This is the anchor for future `balanceOf()` calculations.

### Rebalancing

Stable rates provide borrowers with predictability, but they create a risk for the protocol. If market rates rise significantly above a user's locked-in stable rate, that user is paying less than they should, and the protocol earns less interest than it needs to remain solvent.

To handle this, Aave allows anyone to call `rebalanceStableBorrowRate()` on the Pool contract:

```solidity
// In Pool.sol
function rebalanceStableBorrowRate(
    address asset,
    address user
) external virtual override {
    BorrowLogic.executeRebalanceStableBorrowRate(
        _reserves[asset],
        _usersConfig[user],
        asset,
        user
    );
}
```

The rebalance logic checks whether the user's current stable rate is too far from the current market rate:

```solidity
// From ValidationLogic.validateRebalanceStableBorrowRate
uint256 stableRateRebalanceCondition = reserve.currentStableBorrowRate;

// Rebalance is allowed if the user's rate differs significantly from current rates
// or if utilization is very high and supply rate exceeds the optimal threshold
```

When a rebalance executes:

1. The user's existing stable debt is effectively "burned" and "re-minted" at the current stable rate.
2. The user's locked rate is updated to the current market stable rate.
3. The global average stable rate is recalculated.

This mechanism prevents users from holding artificially cheap stable rates forever. It is a safety valve for the protocol.

### Why Stable Rates Are Being Deprecated

In practice, stable rate borrowing has been a source of significant complexity and edge cases in Aave:

1. **Governance attack surface**: The rebalancing conditions are parameterized, and getting them wrong can either make rebalancing too easy (disrupting borrowers) or too hard (exposing the protocol to rate risk).

2. **Capital inefficiency**: The protocol must maintain higher reserve requirements to account for the possibility that stable borrowers are paying below-market rates.

3. **Low adoption**: Most borrowers prefer variable rates because they are typically lower. The stable rate premium has not justified the complexity.

4. **Oracle dependency for rate-setting**: Determining a "fair" stable rate requires assumptions about future rate trajectories that are difficult to encode on-chain.

As a result, newer Aave V3 deployments on many chains have stable borrowing **disabled** at the configuration level. The contracts are still deployed, but the pool configuration sets `stableBorrowingEnabled = false` for reserves, preventing new stable borrows. Aave's governance has been moving toward variable-only markets, and the upcoming Aave V4 architecture does not include stable rate borrowing at all.

---

## The Mint and Burn Flow

Let's trace through the complete lifecycle of variable debt tokens, since they are the standard path in modern Aave deployments.

### Borrow: Minting Variable Debt Tokens

When a user borrows, the Pool delegates to `BorrowLogic.executeBorrow()`, which eventually calls `VariableDebtToken.mint()`:

```solidity
// VariableDebtToken.mint()
function mint(
    address user,
    address onBehalfOf,
    uint256 amount,
    uint256 index
) external virtual override onlyPool returns (bool, uint256) {
    if (user != onBehalfOf) {
        _decreaseBorrowAllowance(onBehalfOf, user, amount);
    }
    return (
        _mintScaled(user, onBehalfOf, amount, index),
        scaledTotalSupply()
    );
}
```

The `_mintScaled()` function (inherited from `ScaledBalanceTokenBase`, the same base class used by aTokens) does the work:

```solidity
function _mintScaled(
    address caller,
    address onBehalfOf,
    uint256 amount,
    uint256 index
) internal returns (bool) {
    uint256 amountScaled = amount.rayDiv(index);
    require(amountScaled != 0, Errors.INVALID_MINT_AMOUNT);

    uint256 scaledBalance = super.balanceOf(onBehalfOf);
    uint256 balanceIncrease = scaledBalance.rayMul(index)
        - scaledBalance.rayMul(_userState[onBehalfOf].additionalData);

    _userState[onBehalfOf].additionalData = index.toUint128();

    _mint(onBehalfOf, amountScaled.toUint128());

    uint256 amountToMint = amount + balanceIncrease;
    emit Transfer(address(0), onBehalfOf, amountToMint);
    emit Mint(caller, onBehalfOf, amountToMint, balanceIncrease, index);

    return scaledBalance == 0;
}
```

Step by step:

1. **Compute scaled amount**: `amountScaled = borrowAmount / currentVariableBorrowIndex`. If the user borrows 1000 USDC and the index is 1.05, the protocol mints approximately 952.38 scaled debt tokens.

2. **Compute balance increase**: Any interest that has accrued on the user's existing debt since their last interaction is calculated. This is emitted in the event for tracking but is not separately stored --- it is already captured by the index growth.

3. **Update additionalData**: The user's `additionalData` is set to the current index. This is used for the `balanceIncrease` calculation on the next interaction.

4. **Mint scaled tokens**: The internal ERC-20 `_mint()` adds the scaled amount to the user's balance and the total supply.

5. **Emit events**: A `Transfer` event from `address(0)` and a `Mint` event are emitted with the actual (non-scaled) amounts.

6. **Return first-borrow flag**: Returns `true` if this is the user's first borrow of this asset. The calling code uses this to update the user's configuration bitmap.

### Repay: Burning Variable Debt Tokens

On repay, the flow is reversed. `BorrowLogic.executeRepay()` calls `VariableDebtToken.burn()`:

```solidity
// VariableDebtToken.burn()
function burn(
    address from,
    uint256 amount,
    uint256 index
) external virtual override onlyPool returns (uint256) {
    _burnScaled(from, address(0), amount, index);
    return scaledTotalSupply();
}
```

The `_burnScaled()` function:

```solidity
function _burnScaled(
    address user,
    address target,
    uint256 amount,
    uint256 index
) internal {
    uint256 amountScaled = amount.rayDiv(index);
    require(amountScaled != 0, Errors.INVALID_BURN_AMOUNT);

    uint256 scaledBalance = super.balanceOf(user);
    uint256 balanceIncrease = scaledBalance.rayMul(index)
        - scaledBalance.rayMul(_userState[user].additionalData);

    _userState[user].additionalData = index.toUint128();

    _burn(user, amountScaled.toUint128());

    if (target != address(0)) {
        // For aTokens, this would transfer underlying. Debt tokens pass address(0).
    }

    uint256 amountToBurn = amount + balanceIncrease;
    emit Transfer(user, address(0), amountToBurn);
    emit Burn(user, amountToBurn, balanceIncrease, index);
}
```

The flow mirrors minting:

1. **Compute scaled amount to burn**: `amountScaled = repayAmount / currentVariableBorrowIndex`.
2. **Compute balance increase**: Interest accrued since last interaction.
3. **Update additionalData**: Store the current index.
4. **Burn scaled tokens**: Remove from the user's balance and total supply.
5. **Emit events**: A `Transfer` event to `address(0)` and a `Burn` event.

### How Scaled Total Supply Tracks Protocol Debt

The scaled total supply of the variable debt token is one of the most important values in the protocol. Multiplied by the current variable borrow index, it gives the **total variable debt** across all borrowers:

```
totalVariableDebt = scaledTotalSupply * variableBorrowIndex
```

This value feeds directly into:

- **Utilization calculation**: `utilization = totalDebt / (totalLiquidity + totalDebt)`, which determines interest rates.
- **Treasury accrual**: The difference in total debt between updates is how the protocol computes interest earned.
- **Reserve solvency checks**: The protocol ensures that total aToken supply (representing depositor claims) is always backed by underlying assets plus outstanding debt.

Every mint increases scaled total supply. Every burn decreases it. The index handles the rest.

---

## Debt Token Events

Debt tokens emit standard ERC-20 `Transfer` events on mint and burn, even though they are non-transferable:

```
On mint (borrow):
  Transfer(address(0), borrower, amount)

On burn (repay):
  Transfer(borrower, address(0), amount)
```

The `amount` in these events is the **actual** (non-scaled) value, including any accrued interest since the last interaction. This is deliberate --- it ensures that:

1. **Block explorers** show correct borrow/repay amounts in human-readable terms.
2. **Subgraphs and indexers** can track total debt by summing Transfer events without needing to understand scaled balances.
3. **Event-driven systems** can monitor borrowing activity using standard ERC-20 event filters.

In addition to the standard `Transfer` event, debt tokens emit custom `Mint` and `Burn` events with additional data:

```solidity
event Mint(
    address indexed caller,
    address indexed onBehalfOf,
    uint256 value,           // actual amount including interest
    uint256 balanceIncrease, // interest accrued since last interaction
    uint256 index            // current variable borrow index
);

event Burn(
    address indexed from,
    uint256 value,           // actual amount including interest
    uint256 balanceIncrease, // interest accrued since last interaction
    uint256 index            // current variable borrow index
);
```

The `balanceIncrease` field is particularly useful: it tells you exactly how much interest the user accrued between their previous interaction and this one, without needing to track the index history yourself.

---

## Delegation: Borrowing on Behalf of Others

Both debt token types support **borrow delegation** via the `approveDelegation()` and `borrowAllowance()` functions:

```solidity
function approveDelegation(
    address delegatee,
    uint256 amount
) external override {
    _borrowAllowances[_msgSender()][delegatee] = amount;
    emit BorrowAllowanceDelegated(
        _msgSender(),
        delegatee,
        _underlyingAsset,
        amount
    );
}

function borrowAllowance(
    address fromUser,
    address toUser
) external view override returns (uint256) {
    return _borrowAllowances[fromUser][toUser];
}
```

This allows user A to approve user B to borrow against A's collateral. When B calls `borrow()` with `onBehalfOf = A`:

1. The protocol checks that B has sufficient borrow allowance from A.
2. Debt tokens are minted to **A's address** (A holds the debt).
3. The borrowed assets are sent to **B's address** (B receives the funds).
4. B's borrow allowance from A is decreased by the borrowed amount.

This is used for credit delegation --- a powerful DeFi primitive where users with excess collateral can allow others to borrow against it, often in exchange for off-chain agreements or integration with other protocols.

Note that borrow delegation is separate from token transfers. Even with delegation, the debt tokens themselves never move between addresses. Delegation controls who can *create* debt, not who *holds* it.

---

## VariableDebtToken vs StableDebtToken: A Comparison

| Property                  | VariableDebtToken                    | StableDebtToken                       |
|--------------------------|--------------------------------------|---------------------------------------|
| Rate model               | Shared variable borrow index         | Per-user locked rate                  |
| `balanceOf()` computation | `scaledBalance * variableBorrowIndex` | `principal * (1 + rate)^timeDelta`    |
| Internal storage          | Scaled balance (÷ index)             | Principal amount                      |
| `additionalData` stores   | Last-updated index                   | User's stable rate                    |
| Rate changes              | Automatically, with every index update | Only on new borrow, repay, or rebalance |
| Gas cost for `balanceOf` | Cheaper (single multiplication)       | More expensive (compound interest calc) |
| Current status            | Active on all deployments             | Disabled on most new deployments      |
| Transferable              | No                                   | No                                    |

---

## Summary

Debt tokens complete the dual-sided accounting of Aave V3. Where aTokens track what depositors are owed, debt tokens track what borrowers owe.

**Key takeaways:**

- **Debt tokens are non-transferable ERC-20s**: They implement the interface for balance tracking and event emission, but `transfer()` and `transferFrom()` revert. This prevents users from offloading their obligations.
- **VariableDebtToken mirrors the aToken pattern**: It uses a scaled balance divided by the variable borrow index. `balanceOf()` returns `scaledBalance * variableBorrowIndex`, and debt grows automatically as the index increases.
- **StableDebtToken locks in per-user rates**: Each borrower's rate is stored individually, and `balanceOf()` computes compound interest from the borrow timestamp. A global average stable rate is maintained for the interest rate model.
- **Rebalancing is a safety mechanism**: If a user's stable rate diverges too far from market rates, anyone can trigger a rebalance to update their rate.
- **Stable rates are being deprecated**: Due to complexity, low adoption, and governance risks, newer Aave deployments disable stable borrowing entirely.
- **Borrow delegation allows borrowing on behalf of others**: Users can approve others to take debt against their collateral, enabling credit delegation use cases.
- **Events use actual (non-scaled) amounts**: Transfer events on mint/burn report real values for accurate off-chain indexing.

In the next chapter, we tie everything together by walking through the complete supply, borrow, repay, and withdraw flows end-to-end.
