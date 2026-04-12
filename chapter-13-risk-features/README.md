# Chapter 13: Additional Risk Features

Aave V3 has three risk-management features that are conceptually important but don't fit neatly into earlier chapters. Supply and borrow caps limit how much of any single asset can flow through the protocol. Siloed borrowing prevents risky assets from being co-borrowed with other assets. And repay-with-aTokens lets users unwind positions efficiently by burning their deposit tokens to cover debt. Each feature is small in code but significant in practice --- they are the guardrails that let Aave list hundreds of assets without exposing the entire protocol to the tail risk of any one of them.

---

## 1. Supply and Borrow Caps

### The Problem

Imagine Aave lists a new governance token, TOKEN-X, with $20M of on-chain liquidity. Without any limits, a whale could supply $500M of TOKEN-X as collateral, borrow $300M of USDC against it, and then manipulate TOKEN-X's price. Even without manipulation, the protocol would hold more TOKEN-X than the market could absorb in a liquidation. The result: bad debt.

Supply and borrow caps solve this by putting hard limits on how much of any single asset the protocol can hold or lend out.

### What They Are

- **Supply cap**: The maximum total amount of an asset that can be supplied to the protocol. Once the cap is reached, no more `supply()` calls succeed for that asset. Existing suppliers are unaffected --- they can still withdraw, earn interest, and use their positions normally.

- **Borrow cap**: The maximum total amount of an asset that can be borrowed. Once the cap is reached, no new borrows succeed. Existing borrowers are unaffected --- they can still repay, and their interest continues to accrue normally.

Both caps are denominated in **whole tokens** (not wei). A supply cap of 2,000,000 for USDC means 2 million USDC, regardless of USDC having 6 decimals.

### How They Are Stored

Like most reserve parameters, caps are packed into the reserve configuration bitmap:

```solidity
// From ReserveConfiguration.sol
uint256 internal constant SUPPLY_CAP_MASK =
    0xFFFFFFFFFFFFFFFFFFFFFFFFFF000000000FFFFFFFFFFFFFFFFFFFFFFFFFFFFF;
uint256 internal constant SUPPLY_CAP_START_BIT_POSITION = 116;

uint256 internal constant BORROW_CAP_MASK =
    0xFFFFFFFFFFFFFFFFFFFFFFF000000000FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF;
uint256 internal constant BORROW_CAP_START_BIT_POSITION = 80;

function getSupplyCap(
    DataTypes.ReserveConfigurationMap memory self
) internal pure returns (uint256) {
    return (self.data & ~SUPPLY_CAP_MASK) >> SUPPLY_CAP_START_BIT_POSITION;
}

function getBorrowCap(
    DataTypes.ReserveConfigurationMap memory self
) internal pure returns (uint256) {
    return (self.data & ~BORROW_CAP_MASK) >> BORROW_CAP_START_BIT_POSITION;
}
```

A cap value of 0 means "no cap" --- the asset is uncapped. This is the default for established assets like ETH and USDC on most deployments.

### Validation: Supply Cap

When a user calls `Pool.supply()`, the validation logic checks the supply cap in `ValidationLogic.validateSupply()`:

```solidity
function validateSupply(
    DataTypes.ReserveCache memory reserveCache,
    DataTypes.ReserveData storage reserve,
    uint256 amount
) internal view {
    // ... other checks (active, not paused, not frozen) ...

    uint256 supplyCap = reserveCache.reserveConfiguration.getSupplyCap();

    require(
        supplyCap == 0 ||
            ((IAToken(reserveCache.aTokenAddress).scaledTotalSupply() +
                uint256(reserve.accruedToTreasury)).rayMul(
                    reserveCache.nextLiquidityIndex
                ) + amount) <=
            supplyCap * (10 ** reserveCache.reserveConfiguration.getDecimals()),
        Errors.SUPPLY_CAP_EXCEEDED
    );
}
```

The key calculation:
1. Get the current total supply: `scaledTotalSupply * liquidityIndex + accruedToTreasury`
2. Add the new supply amount
3. Compare against `supplyCap * 10^decimals` (converting from whole tokens to wei)
4. If it exceeds the cap, revert with `SUPPLY_CAP_EXCEEDED`

Note that `accruedToTreasury` is included. This is the treasury's unclaimed share of interest --- it counts toward the cap because it represents real supply that has not yet been minted as aTokens.

### Validation: Borrow Cap

Similarly, `ValidationLogic.validateBorrow()` checks the borrow cap:

```solidity
if (vars.reserveBorrowCap != 0) {
    uint256 totalDebt =
        reserveCache.currTotalStableDebt + reserveCache.currTotalVariableDebt;

    unchecked {
        require(
            totalDebt + params.amount <= vars.reserveBorrowCap * (10 ** reserveCache.reserveConfiguration.getDecimals()),
            Errors.BORROW_CAP_EXCEEDED
        );
    }
}
```

The logic is simpler: total stable debt plus total variable debt plus the new borrow must not exceed the cap.

### How Governance Sets Caps

Caps are set through the PoolConfigurator, which is restricted to addresses with the `RISK_ADMIN` or `POOL_ADMIN` role:

```solidity
// PoolConfigurator.sol
function setSupplyCap(
    address asset,
    uint256 newSupplyCap
) external override onlyRiskOrPoolAdmins {
    DataTypes.ReserveConfigurationMap memory currentConfig =
        _pool.getConfiguration(asset);
    currentConfig.setSupplyCap(newSupplyCap);
    _pool.setConfiguration(asset, currentConfig);
    emit SupplyCapChanged(asset, newSupplyCap);
}

function setBorrowCap(
    address asset,
    uint256 newBorrowCap
) external override onlyRiskOrPoolAdmins {
    DataTypes.ReserveConfigurationMap memory currentConfig =
        _pool.getConfiguration(asset);
    currentConfig.setBorrowCap(newBorrowCap);
    _pool.setConfiguration(asset, currentConfig);
    emit BorrowCapChanged(asset, newBorrowCap);
}
```

### Practical Example

Consider USDC on Aave V3 Ethereum:

| Parameter | Value |
|---|---|
| Supply Cap | 2,000,000,000 USDC |
| Borrow Cap | 1,500,000,000 USDC |

And compare with a riskier asset like CRV:

| Parameter | Value |
|---|---|
| Supply Cap | 62,500,000 CRV |
| Borrow Cap | 7,700,000 CRV |

The CRV caps are much tighter because CRV has lower liquidity and higher volatility. If CRV's price crashed, Aave needs to ensure the total CRV position is small enough that liquidations can clear the debt without cascading losses.

### Important Edge Cases

**Caps do not force withdrawals.** If governance lowers a supply cap below the current total supply, existing positions are grandfathered in. No one is forced to withdraw. However, no new supply is accepted until the total drops below the new cap.

**Caps are checked pre-operation.** The validation happens before the supply or borrow executes. If the operation would push the total over the cap, it reverts entirely --- there is no partial fill.

**Caps interact with interest accrual.** Total supply and total debt grow over time as interest accrues. A reserve could theoretically breach its cap through interest alone, but this is by design --- the caps prevent new inflows, not organic growth of existing positions.

---

## 2. Siloed Borrowing

### The Problem

Some assets have unusual mechanics that create complex risk interactions when borrowed alongside other assets. Rebasing tokens change their balance automatically. Tokens with transfer fees lose value on every transfer. Tokens with low liquidity can be difficult to liquidate. If a user borrows one of these alongside a normal asset like USDC, the risk model for the combined position becomes much harder to reason about.

### What Siloed Borrowing Is

Siloed borrowing is a per-asset flag that says: **if you borrow this asset, it must be your only borrow.** You cannot hold any other borrows simultaneously.

The restriction works in both directions:
1. If you already have borrows and try to borrow a siloed asset, the transaction reverts.
2. If you already have a siloed borrow and try to borrow anything else (siloed or not), the transaction reverts.

Your collateral is not affected. You can use any combination of collateral assets --- siloed borrowing only restricts the debt side of your position.

### How It Differs from Isolation Mode

This is one of the most commonly confused distinctions in Aave V3. The two features are orthogonal:

| Feature | What It Restricts | Direction | Example |
|---|---|---|---|
| **Isolation Mode** | Which assets can be used as **collateral** | Collateral side | "TOKEN-X is isolated --- if it is your collateral, you can only borrow stablecoins" |
| **Siloed Borrowing** | Which assets can be **borrowed together** | Debt side | "GHO is siloed --- if you borrow GHO, you cannot also borrow USDC" |
| **E-Mode** | What **LTV and liquidation threshold** apply | Both sides | "In stablecoin E-Mode, your USDC collateral gets 97% LTV instead of 77%" |

A user could theoretically be in Isolation Mode (using an isolated collateral) and borrowing a siloed asset simultaneously. The features compose independently.

### How It Works in Code

The siloed borrowing flag is stored in the reserve configuration bitmap:

```solidity
// From ReserveConfiguration.sol
uint256 internal constant SILOED_BORROWING_MASK =
    0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFBFFFFFFFFFFFFFFF;
uint256 internal constant SILOED_BORROWING_START_BIT_POSITION = 62;

function getSiloedBorrowing(
    DataTypes.ReserveConfigurationMap memory self
) internal pure returns (bool) {
    return (self.data & ~SILOED_BORROWING_MASK) != 0;
}
```

The enforcement happens in `ValidationLogic.validateBorrow()`. There are two checks:

**Check 1: Is the user trying to borrow a siloed asset while already having other borrows?**

```solidity
if (params.reserveConfiguration.getSiloedBorrowing()) {
    require(
        !userConfig.isBorrowingAny(),
        Errors.SILOED_BORROWING_VIOLATION
    );
}
```

If the asset being borrowed is siloed, the user must not have any existing borrows at all. `isBorrowingAny()` checks the user's configuration bitmap for any active borrow flags.

**Check 2: Is the user trying to borrow any asset while already having a siloed borrow?**

```solidity
if (userConfig.isBorrowingAny()) {
    // Find what the user is already borrowing
    // Check if any of their current borrows are siloed
    bool siloedBorrowingEnabled;
    // ... iterate through user's borrows ...

    require(
        !siloedBorrowingEnabled || params.asset == siloedBorrowingAddress,
        Errors.SILOED_BORROWING_VIOLATION
    );
}
```

This second check ensures that if the user already has a siloed borrow, the only thing they can borrow more of is that same siloed asset. They cannot add a different asset to their borrow position.

The full check in context looks like this:

```solidity
// Simplified from ValidationLogic.validateBorrow()
if (reserveConfiguration.getSiloedBorrowing()) {
    // New borrow is a siloed asset --- user must have no other borrows
    require(!userConfig.isBorrowingAny(), Errors.SILOED_BORROWING_VIOLATION);
}

if (userConfig.isBorrowingAny()) {
    // User already has borrows --- check if any are siloed
    (bool siloedBorrowingEnabled, address siloedBorrowingAddress) =
        _getSiloedBorrowingState(userConfig, reservesData, reservesList);

    if (siloedBorrowingEnabled) {
        // User has a siloed borrow --- they can only borrow more of the same asset
        require(
            params.asset == siloedBorrowingAddress,
            Errors.SILOED_BORROWING_VIOLATION
        );
    }
}
```

### Governance Configuration

Governance sets the siloed borrowing flag through the PoolConfigurator:

```solidity
function setSiloedBorrowing(
    address asset,
    bool newSiloed
) external override onlyRiskOrPoolAdmins {
    // Can only be set before any borrows have been taken
    // (to avoid trapping existing borrowers in an invalid state)
    DataTypes.ReserveConfigurationMap memory currentConfig =
        _pool.getConfiguration(asset);

    if (!newSiloed) {
        require(
            currentConfig.getSiloedBorrowing(),
            Errors.INVALID_SILOED_BORROWING_STATE
        );
    }

    currentConfig.setSiloedBorrowing(newSiloed);
    _pool.setConfiguration(asset, currentConfig);
    emit SiloedBorrowingChanged(asset, newSiloed);
}
```

### Practical Scenario

Consider a user who wants to borrow GHO (Aave's stablecoin), which is flagged as siloed:

**Scenario A: Clean slate**
1. User supplies ETH as collateral
2. User borrows 10,000 GHO --- succeeds (no existing borrows, siloed check passes)
3. User tries to borrow 5,000 USDC --- **reverts** with `SILOED_BORROWING_VIOLATION`
4. User can borrow more GHO --- succeeds (same siloed asset)

**Scenario B: Existing borrows**
1. User supplies ETH as collateral
2. User borrows 5,000 USDC --- succeeds (USDC is not siloed)
3. User tries to borrow 10,000 GHO --- **reverts** with `SILOED_BORROWING_VIOLATION`
4. User borrows 3,000 DAI --- succeeds (neither USDC nor DAI is siloed)

### Why Not Just Use Isolation Mode?

Isolation Mode restricts collateral. Siloed borrowing restricts debt. They address different threat vectors:

- **Isolation Mode** protects against: a risky collateral asset crashing and leaving bad debt. It limits the total debt that can be backed by the risky collateral.

- **Siloed Borrowing** protects against: complex interactions between a risky borrowed asset and other borrows. For example, if a rebasing borrow changes its balance unexpectedly, having it isolated from other debts makes the position easier to reason about and liquidate.

---

## 3. Repay with aTokens

### The Scenario

You supplied 10,000 USDC to Aave and received 10,000 aUSDC. Later, you borrowed 5,000 USDC from Aave. Your position is now:

- **Assets**: 10,000 aUSDC (earning interest)
- **Liabilities**: 5,000 variable debt USDC (accruing interest)

You want to close out the borrow. Normally, you would need to:
1. Call `withdraw()` to convert aUSDC back to USDC
2. Call `repay()` to send the USDC back to the protocol

This requires two transactions, two gas fees, and temporarily holding USDC in your wallet. It also reduces the protocol's liquidity during the brief window between withdraw and repay.

Repay with aTokens collapses this into a single step.

### How It Works

When you call `Pool.repayWithATokens()` (or `Pool.repay()` with the `useATokens` flag), the protocol:

1. Burns your aTokens (reducing your supply position)
2. Burns your debt tokens (reducing your debt)
3. Does **not** transfer any underlying tokens

No underlying tokens move because they are already in the protocol. The aTokens represent a claim on underlying that is sitting in the aToken contract. By burning the aTokens, you are giving up that claim. By burning the debt tokens, the protocol forgives the debt. The underlying stays where it was --- it was backing both your supply and the pool's lending capacity.

### The Entry Point

```solidity
// Pool.sol
function repayWithATokens(
    address asset,
    uint256 amount,
    uint256 interestRateMode
) external virtual override returns (uint256) {
    return BorrowLogic.executeRepay(
        _reserves,
        _reservesList,
        _usersConfig[msg.sender],
        DataTypes.ExecuteRepayParams({
            asset: asset,
            amount: amount,
            interestRateMode: DataTypes.InterestRateMode(interestRateMode),
            onBehalfOf: msg.sender,
            useATokens: true  // <-- The key flag
        })
    );
}
```

Note that `onBehalfOf` is always `msg.sender` when repaying with aTokens. You can only use your own aTokens to repay your own debt --- you cannot burn someone else's aTokens to repay your debt, or burn your aTokens to repay someone else's debt.

### Inside BorrowLogic.executeRepay()

The repay function branches based on the `useATokens` flag:

```solidity
function executeRepay(
    mapping(address => DataTypes.ReserveData) storage reservesData,
    mapping(uint256 => address) storage reservesList,
    DataTypes.UserConfigurationMap storage userConfig,
    DataTypes.ExecuteRepayParams memory params
) external returns (uint256) {
    DataTypes.ReserveData storage reserve = reservesData[params.asset];
    DataTypes.ReserveCache memory reserveCache = reserve.cache();
    reserve.updateState(reserveCache);

    // Determine the actual payback amount
    uint256 paybackAmount;
    if (params.interestRateMode == DataTypes.InterestRateMode.STABLE) {
        paybackAmount = IERC20(reserveCache.stableDebtTokenAddress)
            .balanceOf(params.onBehalfOf);
    } else {
        paybackAmount = IERC20(reserveCache.variableDebtTokenAddress)
            .balanceOf(params.onBehalfOf);
    }

    // If user specified less than full debt, use their amount
    if (params.amount < paybackAmount) {
        paybackAmount = params.amount;
    }

    // Validate the repay
    ValidationLogic.validateRepay(reserveCache, paybackAmount, params.onBehalfOf);

    // Burn debt tokens
    if (params.interestRateMode == DataTypes.InterestRateMode.STABLE) {
        IStableDebtToken(reserveCache.stableDebtTokenAddress).burn(
            params.onBehalfOf, paybackAmount
        );
    } else {
        IVariableDebtToken(reserveCache.variableDebtTokenAddress).burn(
            params.onBehalfOf, paybackAmount, reserveCache.nextVariableBorrowIndex
        );
    }

    // *** HERE IS THE BRANCH ***
    if (params.useATokens) {
        // Burn aTokens instead of transferring underlying
        IAToken(reserveCache.aTokenAddress).burn(
            msg.sender,        // burn from the caller
            reserveCache.aTokenAddress,  // underlying stays in the aToken contract
            paybackAmount,
            reserveCache.nextLiquidityIndex
        );
    } else {
        // Normal repay: transfer underlying from user to aToken contract
        IAToken(reserveCache.aTokenAddress).handleRepayment(
            msg.sender, params.onBehalfOf, paybackAmount
        );
        IERC20(params.asset).safeTransferFrom(
            msg.sender, reserveCache.aTokenAddress, paybackAmount
        );
    }

    // Update interest rates
    reserve.updateInterestRates(reserveCache, params.asset, 
        params.useATokens ? 0 : paybackAmount,  // liquidityAdded
        0                                         // liquidityRemoved
    );

    // If debt is fully repaid, clear the borrowing flag
    if (
        IStableDebtToken(reserveCache.stableDebtTokenAddress).balanceOf(params.onBehalfOf) == 0 &&
        IVariableDebtToken(reserveCache.variableDebtTokenAddress).balanceOf(params.onBehalfOf) == 0
    ) {
        userConfig.setBorrowing(reserve.id, false);
    }

    emit Repay(params.asset, params.onBehalfOf, msg.sender, paybackAmount, params.useATokens);
    return paybackAmount;
}
```

### The Critical Detail: Interest Rate Update

Notice the `updateInterestRates` call:

```solidity
reserve.updateInterestRates(reserveCache, params.asset,
    params.useATokens ? 0 : paybackAmount,  // liquidityAdded
    0                                         // liquidityRemoved
);
```

When repaying normally, the underlying tokens physically move from the user to the aToken contract, so `liquidityAdded = paybackAmount`. The protocol has more liquidity available for borrows.

When repaying with aTokens, no underlying moves. The pool's total liquidity decreases (aTokens burned) and total debt decreases (debt tokens burned) by the same amount. The net effect on utilization depends on the relative magnitudes, but no new liquidity enters the pool, so `liquidityAdded = 0`.

### When Repay with aTokens Is Useful

**1. Unwinding a position.** You want to close out a borrow without the hassle of withdrawing first. One transaction instead of two.

**2. Self-deleveraging.** If you have been looping (supply, borrow, supply, borrow...) to create a leveraged position, repaying with aTokens is the cleanest way to unwind each layer.

**3. Gas savings.** One transaction instead of two means roughly half the gas. No ERC-20 approval or transfer of the underlying token is needed.

**4. When you do not hold the underlying.** If all your USDC is deposited in Aave as aUSDC, you may not have any USDC in your wallet. Repay with aTokens lets you repay without needing to withdraw first.

### Limitations

- **Same asset only.** You can only use aUSDC to repay USDC debt, aWETH to repay WETH debt, etc. You cannot use aUSDC to repay WETH debt.

- **Self-only.** You can only burn your own aTokens. Unlike normal `repay()`, where you can repay on behalf of another user, `repayWithATokens()` is restricted to `msg.sender`.

- **Reduces collateral.** Burning aTokens reduces your supply position, which reduces your collateral (if that asset is enabled as collateral). If the repayment would leave you with insufficient collateral for your remaining borrows, the transaction reverts --- the health factor check still applies.

---

## Summary

These three features fill important gaps in Aave V3's risk framework:

| Feature | What It Does | Who Configures It | Where It Is Enforced |
|---|---|---|---|
| **Supply Cap** | Limits total deposits of an asset | Risk Admin / Pool Admin via PoolConfigurator | `ValidationLogic.validateSupply()` |
| **Borrow Cap** | Limits total borrows of an asset | Risk Admin / Pool Admin via PoolConfigurator | `ValidationLogic.validateBorrow()` |
| **Siloed Borrowing** | Restricts a risky asset to being the only borrow in a position | Risk Admin / Pool Admin via PoolConfigurator | `ValidationLogic.validateBorrow()` |
| **Repay with aTokens** | Lets users burn aTokens to cover debt without transferring underlying | N/A (always available) | `BorrowLogic.executeRepay()` |

Together with Isolation Mode (Chapter 10), E-Mode (Chapter 9), and the liquidation mechanism (Chapter 7), these features give Aave governance fine-grained control over protocol risk. Each asset can be tuned independently: capped to limit exposure, siloed to prevent complex debt interactions, isolated to limit collateral risk, and grouped with similar assets in E-Mode to improve capital efficiency. The result is a protocol flexible enough to list hundreds of assets while remaining robust against the tail risks of any individual one.
