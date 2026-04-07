# Chapter 10: Isolation Mode

Not all assets are created equal. ETH and USDC are battle-tested, deeply liquid, and well-understood. But DeFi moves fast, and there is constant demand to list new assets on Aave --- governance tokens, liquid staking derivatives, real-world asset tokens. These assets bring liquidity and users, but they also bring risk. A newly listed token with thin liquidity could crash 50% in minutes, leaving the protocol with bad debt if it was used as collateral for large borrows.

Aave V3 solves this with **Isolation Mode**. It allows governance to list riskier assets as collateral, but with strict guardrails: a cap on total debt, restrictions on what can be borrowed, and a prohibition on mixing the isolated collateral with other assets. This lets Aave expand its asset coverage without exposing the protocol to unbounded risk from any single new listing.

---

## 1. What Isolation Mode Is

Isolation Mode is a set of restrictions applied to specific collateral assets that governance has marked as "isolated." When a user supplies an isolated asset and uses it as their only collateral, they enter Isolation Mode automatically. The restrictions are:

1. **Debt ceiling**: There is a maximum total debt (in USD) that can be backed by this isolated collateral across all users. Once the ceiling is reached, no one else can borrow against it.

2. **Restricted borrowing**: The user can only borrow assets that governance has flagged as "borrowable in isolation" --- typically safe, liquid stablecoins like USDC, DAI, and USDT.

3. **No additional collateral**: The user cannot enable other supplied assets as collateral alongside the isolated asset. The isolated asset must be their sole collateral.

These restrictions contain the blast radius if something goes wrong with the isolated asset. Even in a worst-case scenario where the isolated asset goes to zero, the protocol's losses are bounded by the debt ceiling.

---

## 2. How Isolation Mode Works

### The Lifecycle

Here is the typical user flow:

1. Governance lists Token X as isolated collateral with a $10M debt ceiling
2. User supplies Token X to Aave (receiving aToken X)
3. User enables Token X as collateral
4. Since Token X is their only collateral and it is an isolated asset, they are now in Isolation Mode
5. User can borrow USDC or DAI (assets flagged as borrowable in isolation)
6. User cannot borrow WETH, WBTC, or any asset not marked as borrowable in isolation
7. User cannot enable ETH, WBTC, or any other asset as additional collateral

### How the Protocol Detects Isolation Mode

There is no explicit "enter isolation mode" function. The protocol determines if a user is in Isolation Mode by examining their collateral configuration at the time of borrowing. The check happens in `ValidationLogic.validateBorrow()`:

```solidity
// Simplified from ValidationLogic.sol
(
    bool isolationModeActive,
    address isolationModeCollateralAddress,
    uint256 isolationModeDebtCeiling
) = userConfig.getIsolationModeState(reservesData, reservesList);
```

The `getIsolationModeState()` function works as follows:

```solidity
function getIsolationModeState(
    DataTypes.UserConfigurationMap memory self,
    mapping(address => DataTypes.ReserveData) storage reservesData,
    mapping(uint256 => address) storage reservesList
) internal view returns (
    bool,    // isIsolated
    address, // isolationModeCollateralAddress
    uint256  // isolationModeDebtCeiling
) {
    uint256 firstAssetAsCollateral = self.getFirstAssetIdByMask(
        self._data & COLLATERAL_MASK  // bitmask for collateral bits
    );

    // Check: user has exactly one collateral asset
    // AND that collateral asset has a non-zero debt ceiling (i.e., is isolated)
    uint256 debtCeiling = reservesData[reservesList[firstAssetAsCollateral]]
        .configuration
        .getDebtCeiling();

    if (debtCeiling != 0) {
        // User is in isolation mode
        return (true, reservesList[firstAssetAsCollateral], debtCeiling);
    }

    return (false, address(0), 0);
}
```

The logic is:
1. Find the user's first (and only) collateral asset
2. Check if that asset has a debt ceiling configured
3. If yes, the user is in Isolation Mode

An asset has a debt ceiling of 0 by default, meaning it is not isolated. Governance sets a non-zero debt ceiling to make an asset isolated.

---

## 3. Debt Ceiling

The debt ceiling is the most important safety mechanism in Isolation Mode. It caps the total USD value of debt that can be backed by a given isolated collateral asset, across all users.

### How It Is Stored

The debt ceiling is stored in the reserve configuration bitmap:

```solidity
// From ReserveConfiguration.sol
uint256 internal constant DEBT_CEILING_MASK =
    0xF0000000000FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF;
uint256 internal constant DEBT_CEILING_START_BIT_POSITION = 212;
uint256 internal constant DEBT_CEILING_DECIMALS = 2;

function getDebtCeiling(
    DataTypes.ReserveConfigurationMap memory self
) internal pure returns (uint256) {
    return (self.data & ~DEBT_CEILING_MASK) >> DEBT_CEILING_START_BIT_POSITION;
}
```

The ceiling is denominated in the protocol's base currency (USD on mainnet) with **2 decimals of precision**. A stored value of 1000000 means a $10,000.00 ceiling. A value of 1000000000 means $10,000,000.00.

### Tracking Current Debt

The actual amount of debt currently backed by an isolated collateral is tracked in the reserve data:

```solidity
// From DataTypes.sol
struct ReserveData {
    // ... other fields ...
    uint128 isolationModeTotalDebt;
    // ... other fields ...
}
```

This counter is updated whenever a user in Isolation Mode borrows or repays:

**On borrow** (in `BorrowLogic.executeBorrow()`):

```solidity
if (isolationModeActive) {
    uint256 nextIsolationModeTotalDebt =
        reservesData[isolationModeCollateralAddress].isolationModeTotalDebt
        + (params.amount / 10 ** (reserveDecimals - DEBT_CEILING_DECIMALS)).toUint128();

    reservesData[isolationModeCollateralAddress].isolationModeTotalDebt =
        nextIsolationModeTotalDebt.toUint128();
}
```

The amount is scaled to match the debt ceiling's 2-decimal precision. If a user borrows 5000.123456 USDC (6 decimals), the isolation mode debt increases by 5000.12 (2 decimals).

**On repay** (in `BorrowLogic.executeRepay()`):

```solidity
if (isolationModeActive) {
    uint128 isolationModeTotalDebt =
        reservesData[isolationModeCollateralAddress].isolationModeTotalDebt;

    uint128 debtRepaid = (params.amount / 10 ** (reserveDecimals - DEBT_CEILING_DECIMALS))
        .toUint128();

    reservesData[isolationModeCollateralAddress].isolationModeTotalDebt =
        isolationModeTotalDebt > debtRepaid
            ? isolationModeTotalDebt - debtRepaid
            : 0;
}
```

### Validation at Borrow Time

The debt ceiling is checked in `ValidationLogic.validateBorrow()`:

```solidity
if (isolationModeActive) {
    // 1. Check that the borrowed asset is flagged as borrowable in isolation
    require(
        reserveConfig.getBorrowableInIsolation(),
        Errors.ASSET_NOT_BORROWABLE_IN_ISOLATION
    );

    // 2. Check that the debt ceiling is not exceeded
    require(
        reservesData[isolationModeCollateralAddress].isolationModeTotalDebt
            + (params.amount / 10 ** (params.reserveDecimals - DEBT_CEILING_DECIMALS))
            <= isolationModeDebtCeiling,
        Errors.DEBT_CEILING_EXCEEDED
    );
}
```

Two checks happen:
1. The asset being borrowed must be flagged as borrowable in isolation
2. Adding this borrow must not push the total isolation mode debt above the ceiling

If either check fails, the borrow reverts.

### Why a Global Ceiling Instead of Per-User

The debt ceiling is **global** --- it limits the total debt across all users using this isolated collateral. This is deliberate. If 100 users each borrow $100K against isolated Token X, the protocol's total exposure is $10M. If Token X collapses, the protocol could face up to $10M in bad debt (minus whatever liquidators recover). The debt ceiling caps this worst-case scenario.

A per-user limit would not achieve the same safety guarantee. 10,000 users each borrowing $1K would create the same $10M exposure.

---

## 4. Entering and Exiting Isolation Mode

### Entering Isolation Mode

There is no explicit "enter" function. Isolation Mode is a consequence of the user's collateral configuration:

1. User supplies an isolated asset (e.g., Token X with a debt ceiling)
2. User calls `Pool.setUserUseReserveAsCollateral(tokenX, true)`
3. If Token X is their **only** enabled collateral, they are now in Isolation Mode
4. The next time they borrow, the isolation mode checks apply

The detection happens dynamically at borrow time via `getIsolationModeState()`.

### The Collateral Restriction

Once a user has an isolated asset as collateral, they cannot enable additional collateral. This is enforced in `ValidationLogic.validateSupply()` and the collateral-enabling logic:

```solidity
// When the user tries to enable an asset as collateral, the protocol checks:
// If the user already has an isolated collateral enabled,
// they cannot enable a second collateral asset.

// And vice versa: if the user has non-isolated collateral enabled,
// they cannot enable an isolated asset as additional collateral.
```

More specifically, in `SupplyLogic.executeSupply()`, after minting aTokens, the function checks whether to automatically enable the asset as collateral. If the user is already in Isolation Mode (has an isolated asset as collateral), additional assets are not auto-enabled as collateral.

The validation in `validateUseAsCollateral()` ensures:

```solidity
// From ValidationLogic.sol
function validateSetUserUseReserveAsCollateral(
    mapping(address => DataTypes.ReserveData) storage reservesData,
    mapping(uint256 => address) storage reservesList,
    DataTypes.UserConfigurationMap memory userConfig,
    DataTypes.ReserveConfigurationMap memory reserveConfig
) internal view {
    // ... basic checks ...

    // If the user already has any collateral enabled:
    //   - Cannot enable an isolated asset (would create mixed isolation)
    //   - If the existing collateral is isolated, cannot enable another asset

    bool hasOtherCollateral = userConfig.isUsingAsCollateralAny();

    if (hasOtherCollateral) {
        // Check: the user's existing collateral is not isolated
        (bool isolationModeActive, , ) = userConfig.getIsolationModeState(
            reservesData,
            reservesList
        );
        require(!isolationModeActive, Errors.USER_IN_ISOLATION_MODE);
    }

    // If the asset being enabled is isolated, user must not have other collateral
    if (reserveConfig.getDebtCeiling() != 0) {
        require(!hasOtherCollateral, Errors.USER_IN_ISOLATION_MODE);
    }
}
```

This two-way check ensures:
- A user in Isolation Mode cannot add more collateral
- A user with existing non-isolated collateral cannot add an isolated asset

### Exiting Isolation Mode

To exit, the user disables the isolated asset as collateral:

```solidity
Pool.setUserUseReserveAsCollateral(tokenX, false);
```

This removes Token X from the collateral set. The user is no longer in Isolation Mode and can:
- Enable other assets as collateral
- Borrow any asset (not just isolation-borrowable ones)

However, the user must not have outstanding debt that depends on the isolated collateral. If disabling the collateral would drop the health factor below 1, the transaction reverts.

Alternatively, the user can supply and enable a non-isolated asset as collateral and then disable the isolated one --- effectively swapping their collateral base.

---

## 5. Borrowable in Isolation

Not every asset can be borrowed in Isolation Mode. Governance explicitly flags which assets are safe to borrow against isolated collateral. This is stored as a boolean in the reserve configuration:

```solidity
// From ReserveConfiguration.sol
uint256 internal constant BORROWABLE_IN_ISOLATION_MASK =
    0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFDFFFFFFFFFFFFFFF;
uint256 internal constant BORROWABLE_IN_ISOLATION_START_BIT_POSITION = 61;

function getBorrowableInIsolation(
    DataTypes.ReserveConfigurationMap memory self
) internal pure returns (bool) {
    return (self.data & ~BORROWABLE_IN_ISOLATION_MASK) != 0;
}
```

Typically, only well-established stablecoins are marked as borrowable in isolation:
- USDC
- DAI
- USDT
- Sometimes FRAX or other widely-used stablecoins

The rationale: if a user borrows a volatile asset (like WETH) against isolated collateral, and the collateral drops in value, the debt could exceed the collateral before liquidators act. Stablecoins are predictable in value, making the debt side of the equation more stable and easier for the protocol to manage.

Governance sets this flag via `PoolConfigurator.setBorrowableInIsolation(asset, true)`.

---

## 6. Practical Example

Let us walk through a complete example. Suppose governance has just listed a new token --- let us call it NEW --- on Aave V3.

### Governance Configuration

| Parameter | Value |
|-----------|-------|
| Asset | NEW |
| Can be supplied | Yes |
| Can be collateral | Yes (isolated) |
| Debt ceiling | $5,000,000 (stored as 500000000 with 2 decimals) |
| LTV | 50% |
| Liquidation threshold | 55% |
| Liquidation bonus | 10% |

Assets marked as borrowable in isolation: USDC, DAI, USDT.

### User Actions

**Step 1: Supply NEW**

Alice holds 100,000 NEW tokens, currently worth $10 each ($1,000,000 total). She calls:

```solidity
Pool.supply(NEW, 100000e18, alice, 0);
```

Alice receives aNEW tokens. She is not yet in Isolation Mode --- she has not enabled NEW as collateral.

**Step 2: Enable as Collateral**

```solidity
Pool.setUserUseReserveAsCollateral(NEW, true);
```

Now Alice is in Isolation Mode because:
- NEW is her only collateral
- NEW has a non-zero debt ceiling (it is an isolated asset)

**Step 3: Borrow USDC**

Alice wants to borrow USDC. She calls:

```solidity
Pool.borrow(USDC, 400000e6, 2, 0, alice); // Variable rate, 400K USDC
```

The protocol checks:
1. Is Alice in Isolation Mode? Yes (only collateral is NEW, which has a debt ceiling).
2. Is USDC borrowable in isolation? Yes.
3. Does this borrow exceed the debt ceiling?
   - Current `isolationModeTotalDebt` for NEW: let us say $3,200,000 (from other users)
   - Alice's borrow: $400,000
   - New total: $3,600,000
   - Debt ceiling: $5,000,000
   - $3,600,000 <= $5,000,000 --- ceiling not exceeded.
4. Health factor check:
   - Collateral: 100,000 NEW * $10 = $1,000,000
   - LTV: 50%
   - Max borrow: $500,000
   - Actual borrow: $400,000
   - Health factor: ($1,000,000 * 55%) / $400,000 = 1.375 --- healthy.

The borrow succeeds. Alice receives 400,000 USDC.

**Step 4: What Alice Cannot Do**

Alice tries to borrow WETH:
```solidity
Pool.borrow(WETH, 10e18, 2, 0, alice); // REVERTS: ASSET_NOT_BORROWABLE_IN_ISOLATION
```
WETH is not marked as borrowable in isolation.

Alice tries to enable her ETH as collateral:
```solidity
Pool.setUserUseReserveAsCollateral(WETH, true); // REVERTS: USER_IN_ISOLATION_MODE
```
She cannot have additional collateral while in Isolation Mode.

**Step 5: Debt Ceiling Reached**

Later, other users have also borrowed against NEW. The total `isolationModeTotalDebt` for NEW reaches $5,000,000. Bob tries to borrow:

```solidity
Pool.borrow(USDC, 100000e6, 2, 0, bob); // REVERTS: DEBT_CEILING_EXCEEDED
```

No more borrowing against NEW as collateral until some users repay. The protocol's maximum exposure to NEW-backed debt is capped at $5M.

**Step 6: Exiting Isolation Mode**

Alice repays her USDC debt:
```solidity
Pool.repay(USDC, 400000e6, 2, alice);
```

Now she can disable NEW as collateral:
```solidity
Pool.setUserUseReserveAsCollateral(NEW, false);
```

Alice is no longer in Isolation Mode. She can now enable other assets as collateral and borrow freely.

---

## 7. Isolation Mode in the Code

Let us trace the complete code path for a borrow in Isolation Mode.

### Entry Point: `Pool.borrow()`

```solidity
function borrow(
    address asset,
    uint256 amount,
    uint256 interestRateMode,
    uint16 referralCode,
    address onBehalfOf
) external virtual override {
    BorrowLogic.executeBorrow(
        _reserves,
        _reservesList,
        _eModeCategories,
        _usersConfig[onBehalfOf],
        DataTypes.ExecuteBorrowParams({
            asset: asset,
            user: msg.sender,
            onBehalfOf: onBehalfOf,
            amount: amount,
            interestRateMode: DataTypes.InterestRateMode(interestRateMode),
            referralCode: referralCode,
            releaseUnderlying: true,
            reservesCount: _reservesCount,
            oracle: IPoolAddressesProvider(_addressesProvider).getPriceOracle(),
            userEModeCategory: _usersEModeCategory[onBehalfOf],
            priceOracleSentinel: IPoolAddressesProvider(_addressesProvider).getPriceOracleSentinel()
        })
    );
}
```

### `BorrowLogic.executeBorrow()`

Inside `executeBorrow`, the isolation mode state is determined and passed to validation:

```solidity
function executeBorrow(
    mapping(address => DataTypes.ReserveData) storage reservesData,
    mapping(uint256 => address) storage reservesList,
    mapping(uint8 => DataTypes.EModeCategory) storage eModeCategories,
    DataTypes.UserConfigurationMap storage userConfig,
    DataTypes.ExecuteBorrowParams memory params
) public {
    DataTypes.ReserveData storage reserve = reservesData[params.asset];
    DataTypes.ReserveCache memory reserveCache = reserve.cache();
    reserve.updateState(reserveCache);

    // Determine isolation mode state
    (
        bool isolationModeActive,
        address isolationModeCollateralAddress,
        uint256 isolationModeDebtCeiling
    ) = userConfig.getIsolationModeState(reservesData, reservesList);

    // Validate the borrow
    ValidationLogic.validateBorrow(
        reservesData,
        reservesList,
        eModeCategories,
        DataTypes.ValidateBorrowParams({
            reserveCache: reserveCache,
            userConfig: userConfig,
            asset: params.asset,
            amount: params.amount,
            interestRateMode: params.interestRateMode,
            // ...
            isolationModeActive: isolationModeActive,
            isolationModeCollateralAddress: isolationModeCollateralAddress,
            isolationModeDebtCeiling: isolationModeDebtCeiling
        })
    );
```

### Validation: The Two Isolation Checks

Inside `validateBorrow()`, the isolation checks are straightforward:

```solidity
if (params.isolationModeActive) {
    // Check 1: asset must be borrowable in isolation
    require(
        params.reserveCache.reserveConfiguration.getBorrowableInIsolation(),
        Errors.ASSET_NOT_BORROWABLE_IN_ISOLATION
    );

    // Check 2: debt ceiling must not be exceeded
    require(
        reservesData[params.isolationModeCollateralAddress].isolationModeTotalDebt
            + (params.amount / 10 ** (params.reserveDecimals - ReserveConfiguration.DEBT_CEILING_DECIMALS))
            .toUint128()
            <= params.isolationModeDebtCeiling,
        Errors.DEBT_CEILING_EXCEEDED
    );
}
```

### After Validation: Update Debt Counter

Back in `executeBorrow()`, after validation passes and the debt tokens are minted:

```solidity
    // ... mint debt tokens, transfer underlying, update rates ...

    // Update isolation mode total debt if applicable
    if (isolationModeActive) {
        uint256 nextIsolationModeTotalDebt =
            reservesData[isolationModeCollateralAddress].isolationModeTotalDebt
            + (params.amount / 10 ** (reserveDecimals - ReserveConfiguration.DEBT_CEILING_DECIMALS))
            .toUint128();

        reservesData[isolationModeCollateralAddress].isolationModeTotalDebt =
            nextIsolationModeTotalDebt.toUint128();

        emit IsolationModeTotalDebtUpdated(
            isolationModeCollateralAddress,
            nextIsolationModeTotalDebt
        );
    }
}
```

### Repayment: Decrement the Counter

In `BorrowLogic.executeRepay()`, the counter is decremented:

```solidity
if (isolationModeActive) {
    uint128 isolationModeTotalDebt =
        reservesData[isolationModeCollateralAddress].isolationModeTotalDebt;

    uint128 isolationModeRepaymentAmount =
        (actualPaybackAmount / 10 ** (reserveDecimals - ReserveConfiguration.DEBT_CEILING_DECIMALS))
        .toUint128();

    // Saturating subtraction to avoid underflow from rounding
    reservesData[isolationModeCollateralAddress].isolationModeTotalDebt =
        isolationModeTotalDebt > isolationModeRepaymentAmount
            ? isolationModeTotalDebt - isolationModeRepaymentAmount
            : 0;
}
```

The saturating subtraction (using `> ? - : 0` instead of plain subtraction) handles edge cases where rounding could cause the repayment amount to slightly exceed the tracked debt.

### Liquidation and Isolation Mode

When a position in Isolation Mode is liquidated, the same debt counter is updated. In `LiquidationLogic.executeLiquidationCall()`, after the debt is repaid on behalf of the liquidated user:

```solidity
if (vars.userDebtInBaseCurrency == vars.actualDebtToLiquidate) {
    // Full liquidation: the user's total debt is being repaid
    // The isolation mode debt counter decreases by the full amount
}

// The isolation mode total debt is decremented by the liquidated amount
// This frees up capacity under the debt ceiling for other users
```

This ensures the debt ceiling accurately reflects current outstanding debt and does not permanently consume capacity when positions are liquidated.

---

## Isolation Mode and E-Mode Interaction

A user can be in both Isolation Mode and E-Mode simultaneously. For example, if governance lists a new stablecoin (let us call it nUSD) as:
- Isolated with a $5M debt ceiling
- E-Mode category 1 (Stablecoins)

A user could supply nUSD, enter E-Mode for stablecoins, and borrow USDC with the E-Mode's boosted 93% LTV instead of nUSD's default LTV. However:
- The debt ceiling still applies
- Only isolation-borrowable assets can be borrowed
- The E-Mode restriction (borrows must match the category) also applies
- Both constraint sets must be satisfied simultaneously

---

## Key Takeaways

1. **Isolation Mode restricts riskier collateral assets** by capping total debt, limiting borrowable assets, and preventing mixed collateral. This bounds the protocol's exposure to newly listed or volatile tokens.

2. **The debt ceiling is global** --- it limits total debt across all users, not per-user. This caps the protocol's worst-case loss if the isolated asset collapses.

3. **Entry is automatic.** If a user's only collateral is an isolated asset, they are in Isolation Mode. No explicit opt-in is needed.

4. **Only stablecoins (and governance-approved assets) can be borrowed** in Isolation Mode. This keeps the debt side predictable and reduces the chance of cascading liquidations.

5. **The isolation mode total debt counter** in `reserveData.isolationModeTotalDebt` is incremented on borrow and decremented on repay/liquidation. It uses 2 decimal precision to match the debt ceiling's denomination.

6. **Exiting requires disabling the isolated collateral**, which is only possible if the user's health factor remains >= 1 without it.

7. **Isolation Mode and E-Mode can coexist**, with both sets of constraints applying simultaneously. This allows new stablecoins to benefit from E-Mode capital efficiency while still being risk-bounded by the debt ceiling.
