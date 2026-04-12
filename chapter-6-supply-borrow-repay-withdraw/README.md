# Chapter 6: Supply, Borrow, Repay, and Withdraw Flows

The previous five chapters introduced the building blocks: the architecture and delegation pattern (Chapter 1), the interest rate model (Chapter 2), indexes and scaled balances (Chapter 3), aTokens (Chapter 4), and debt tokens (Chapter 5). This chapter ties them all together by walking through each core operation from the moment a user calls the Pool contract to the final state change.

Every operation in Aave V3 follows the same high-level pattern:

```
1. Validate inputs
2. Update state (indexes, treasury accrual)
3. Execute the operation (mint/burn tokens, transfer assets)
4. Update interest rates (since utilization changed)
5. Emit events
```

The Pool contract is the entry point for all user-facing operations. It does not contain the logic directly --- instead, it delegates to library contracts (`SupplyLogic`, `BorrowLogic`, `ValidationLogic`, etc.) that are linked at deployment time. This keeps the Pool contract within Ethereum's contract size limits while centralizing the interface.

---

## Supply Flow

<video src="../animations/final/supply_flow.webm" controls autoplay loop muted playsinline style="width:100%;max-width:800px;border-radius:8px;margin:20px 0"></video>

### The User's Perspective

A user calls `Pool.supply()` to deposit assets and begin earning interest:

```solidity
function supply(
    address asset,
    uint256 amount,
    address onBehalfOf,
    uint16 referralCode
) external virtual override {
    SupplyLogic.executeSupply(
        _reserves,
        _reservesList,
        _usersConfig[onBehalfOf],
        DataTypes.ExecuteSupplyParams({
            asset: asset,
            amount: amount,
            onBehalfOf: onBehalfOf,
            referralCode: referralCode
        })
    );
}
```

Parameters:
- `asset`: The address of the underlying token (e.g., USDC).
- `amount`: How much to supply.
- `onBehalfOf`: The address that will receive the aTokens. Usually `msg.sender`, but can be a different address (e.g., for zap contracts).
- `referralCode`: Used for referral tracking. Usually `0`.

### Inside SupplyLogic.executeSupply()

This is where the actual work happens:

```solidity
function executeSupply(
    mapping(address => DataTypes.ReserveData) storage reservesData,
    mapping(uint256 => address) storage reservesList,
    DataTypes.UserConfigurationMap storage userConfig,
    DataTypes.ExecuteSupplyParams memory params
) external {
    DataTypes.ReserveData storage reserve = reservesData[params.asset];
    DataTypes.ReserveCache memory reserveCache = reserve.cache();

    // Step 1: Update indexes
    reserve.updateState(reserveCache);

    // Step 2: Validate
    ValidationLogic.validateSupply(reserveCache, reserve, params.amount);

    // Step 3: Update interest rates
    reserve.updateInterestRates(
        reserveCache,
        params.asset,
        params.amount,  // liquidityAdded
        0               // liquidityRemoved
    );

    // Step 4: Transfer underlying from user to aToken contract
    IERC20(params.asset).safeTransferFrom(
        msg.sender,
        reserveCache.aTokenAddress,
        params.amount
    );

    // Step 5: Mint aTokens
    bool isFirstSupply = IAToken(reserveCache.aTokenAddress).mint(
        msg.sender,
        params.onBehalfOf,
        params.amount,
        reserveCache.nextLiquidityIndex
    );

    // Step 6: If first supply, enable asset as collateral
    if (isFirstSupply) {
        if (
            ValidationLogic.validateAutomaticUseAsCollateral(
                reservesData,
                reservesList,
                userConfig,
                reserveCache.reserveConfiguration,
                reserveCache.aTokenAddress
            )
        ) {
            userConfig.setUsingAsCollateral(reserve.id, true);
            emit ReserveUsedAsCollateralEnabled(params.asset, params.onBehalfOf);
        }
    }

    emit Supply(params.asset, msg.sender, params.onBehalfOf, params.amount, params.referralCode);
}
```

Let's walk through each step in detail.

### Step 1: reserve.updateState()

As covered in Chapter 3, this updates the liquidity index and variable borrow index to account for interest accrued since the last interaction. It also accrues the treasury's share of interest.

This must happen **before** any other operation because minting aTokens requires the current index. If the index were stale, the wrong number of scaled tokens would be minted.

### Step 2: ValidationLogic.validateSupply()

```solidity
function validateSupply(
    DataTypes.ReserveCache memory reserveCache,
    DataTypes.ReserveData storage reserve,
    uint256 amount
) internal view {
    require(amount != 0, Errors.INVALID_AMOUNT);

    (bool isActive, bool isFrozen, , , bool isPaused) = reserveCache
        .reserveConfiguration
        .getFlags();

    require(isActive, Errors.RESERVE_INACTIVE);
    require(!isPaused, Errors.RESERVE_PAUSED);
    require(!isFrozen, Errors.RESERVE_FROZEN);

    uint256 supplyCap = reserveCache.reserveConfiguration.getSupplyCap();
    require(
        supplyCap == 0 ||
            ((IAToken(reserveCache.aTokenAddress).scaledTotalSupply() +
                uint256(reserve.accruedToTreasury))
                .rayMul(reserveCache.nextLiquidityIndex) + amount) <=
            supplyCap * (10 ** reserveCache.reserveConfiguration.getDecimals()),
        Errors.SUPPLY_CAP_EXCEEDED
    );
}
```

Validation checks:
- The amount is non-zero.
- The reserve is **active** (has been properly initialized and not deactivated).
- The reserve is **not paused** (emergency pause is not engaged).
- The reserve is **not frozen** (frozen reserves reject new deposits but allow withdrawals and repays).
- The **supply cap** is not exceeded. Supply caps limit total deposits to control risk exposure.

### Step 3: reserve.updateInterestRates()

Interest rates are recalculated because the supply just increased. More liquidity means lower utilization, which typically means lower rates:

```solidity
function updateInterestRates(
    DataTypes.ReserveData storage reserve,
    DataTypes.ReserveCache memory reserveCache,
    address reserveAddress,
    uint256 liquidityAdded,
    uint256 liquidityRemoved
) internal {
    UpdateInterestRatesLocalVars memory vars;

    vars.totalVariableDebt = reserveCache.nextScaledVariableDebt.rayMul(
        reserveCache.nextVariableBorrowIndex
    );

    (
        vars.nextLiquidityRate,
        vars.nextStableRate,
        vars.nextVariableRate
    ) = IReserveInterestRateStrategy(reserve.interestRateStrategyAddress)
        .calculateInterestRates(
            DataTypes.CalculateInterestRatesParams({
                unbacked: reserve.unbacked,
                liquidityAdded: liquidityAdded,
                liquidityTaken: liquidityRemoved,
                totalStableDebt: reserveCache.nextTotalStableDebt,
                totalVariableDebt: vars.totalVariableDebt,
                averageStableBorrowRate: reserveCache.nextAvgStableBorrowRate,
                reserveFactor: reserveCache.reserveFactor,
                reserve: reserveAddress,
                aToken: reserveCache.aTokenAddress
            })
        );

    reserve.currentLiquidityRate = vars.nextLiquidityRate.toUint128();
    reserve.currentStableBorrowRate = vars.nextStableRate.toUint128();
    reserve.currentVariableBorrowRate = vars.nextVariableRate.toUint128();

    emit ReserveDataUpdated(
        reserveAddress,
        vars.nextLiquidityRate,
        vars.nextStableRate,
        vars.nextVariableRate,
        reserveCache.nextLiquidityIndex,
        reserveCache.nextVariableBorrowIndex
    );
}
```

The `liquidityAdded` parameter tells the rate strategy how much new liquidity is entering. For a supply operation, this equals the deposit amount. The rate strategy (covered in Chapter 2) uses this plus the current debt to compute new utilization and rates.

### Step 4: Transfer Underlying

The user's tokens are transferred directly to the aToken contract. The aToken contract acts as the vault --- it holds all the underlying assets for that reserve.

```solidity
IERC20(params.asset).safeTransferFrom(
    msg.sender,
    reserveCache.aTokenAddress,
    params.amount
);
```

Note: `msg.sender` is always the one sending the tokens, even when `onBehalfOf` is a different address. The caller pays; the beneficiary receives the aTokens.

### Step 5: Mint aTokens

The Pool calls `aToken.mint()`, which calls `_mintScaled()` as detailed in Chapter 4:

```solidity
bool isFirstSupply = IAToken(reserveCache.aTokenAddress).mint(
    msg.sender,
    params.onBehalfOf,
    params.amount,
    reserveCache.nextLiquidityIndex
);
```

The `nextLiquidityIndex` (the freshly updated index) is passed explicitly. The aToken stores `amount / index` as the user's scaled balance.

### Step 6: Auto-Enable as Collateral

If this is the user's first deposit of this asset (`isFirstSupply == true`) and the asset is eligible for collateral use, the protocol automatically enables it as collateral in the user's configuration bitmap.

The user config bitmap is a compact data structure where each bit position represents a reserve, with two bits per reserve: one for "is using as collateral" and one for "is borrowing." This is far cheaper than storing individual boolean mappings.

```solidity
if (isFirstSupply) {
    if (
        ValidationLogic.validateAutomaticUseAsCollateral(
            reservesData,
            reservesList,
            userConfig,
            reserveCache.reserveConfiguration,
            reserveCache.aTokenAddress
        )
    ) {
        userConfig.setUsingAsCollateral(reserve.id, true);
        emit ReserveUsedAsCollateralEnabled(params.asset, params.onBehalfOf);
    }
}
```

The auto-collateral check considers whether the asset has a non-zero LTV, whether the user is in isolation mode (which restricts collateral to a single asset), and other configuration flags.

---

## Borrow Flow

<video src="../animations/final/borrow_flow.webm" controls autoplay loop muted playsinline style="width:100%;max-width:800px;border-radius:8px;margin:20px 0"></video>

### The User's Perspective

A user calls `Pool.borrow()` to take a loan against their collateral:

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
            maxStableRateBorrowSizePercent: _maxStableRateBorrowSizePercent,
            reservesCount: _reservesCount,
            oracle: IPoolAddressesProvider(_addressesProvider)
                .getPriceOracle(),
            userEModeCategory: _usersEModeCategory[onBehalfOf],
            priceOracleSentinel: IPoolAddressesProvider(_addressesProvider)
                .getPriceOracleSentinel()
        })
    );
}
```

Parameters:
- `asset`: The token to borrow.
- `amount`: How much to borrow.
- `interestRateMode`: `1` for stable, `2` for variable.
- `referralCode`: Referral tracking.
- `onBehalfOf`: Who takes on the debt. Usually `msg.sender`, but can be another address if borrow delegation is set up.

### Inside BorrowLogic.executeBorrow()

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

    // Step 1: Update indexes
    reserve.updateState(reserveCache);

    // Step 2: Validate the borrow
    (
        bool isolationModeActive,
        address isolationModeCollateralAddress,
        uint256 isolationModeDebtCeiling
    ) = ValidationLogic.validateBorrow(
        reservesData,
        reservesList,
        eModeCategories,
        DataTypes.ValidateBorrowParams({
            reserveCache: reserveCache,
            userConfig: userConfig,
            asset: params.asset,
            userAddress: params.onBehalfOf,
            amount: params.amount,
            interestRateMode: params.interestRateMode,
            maxStableBorrowPercent: params.maxStableRateBorrowSizePercent,
            reservesCount: params.reservesCount,
            oracle: params.oracle,
            userEModeCategory: params.userEModeCategory,
            priceOracleSentinel: params.priceOracleSentinel
        })
    );

    // Step 3: Mint debt tokens
    bool isFirstBorrowing;
    if (params.interestRateMode == DataTypes.InterestRateMode.VARIABLE) {
        (isFirstBorrowing, reserveCache.nextScaledVariableDebt) = IVariableDebtToken(
            reserveCache.variableDebtTokenAddress
        ).mint(params.user, params.onBehalfOf, params.amount, reserveCache.nextVariableBorrowIndex);
    } else {
        // Stable borrow path
        (
            isFirstBorrowing,
            reserveCache.nextTotalStableDebt,
            reserveCache.nextAvgStableBorrowRate
        ) = IStableDebtToken(reserveCache.stableDebtTokenAddress).mint(
            params.user,
            params.onBehalfOf,
            params.amount,
            reserve.currentStableBorrowRate
        );
    }

    // Step 4: Mark as borrowing in user config
    if (isFirstBorrowing) {
        userConfig.setBorrowing(reserve.id, true);
    }

    // Step 5: Update isolation mode debt if applicable
    if (isolationModeActive) {
        uint256 isolationModeTotalDebt = reservesData[isolationModeCollateralAddress]
            .isolationModeTotalDebt;
        // Update the isolation mode total debt tracking
        // ...
    }

    // Step 6: Update interest rates
    reserve.updateInterestRates(
        reserveCache,
        params.asset,
        0,             // liquidityAdded (none --- borrowing removes liquidity)
        params.releaseUnderlying ? params.amount : 0  // liquidityRemoved
    );

    // Step 7: Transfer underlying to borrower
    if (params.releaseUnderlying) {
        IAToken(reserveCache.aTokenAddress).transferUnderlyingTo(
            params.user,
            params.amount
        );
    }

    emit Borrow(
        params.asset,
        params.user,
        params.onBehalfOf,
        params.amount,
        params.interestRateMode,
        // rate, referralCode...
    );
}
```

### Step 2: Borrow Validation (Detail)

The borrow validation is the most complex validation in the protocol. It checks:

```solidity
// Simplified from ValidationLogic.validateBorrow()

// Basic checks
require(amount != 0, Errors.INVALID_AMOUNT);
require(isActive && !isPaused, Errors.RESERVE_INACTIVE_OR_PAUSED);
require(!isFrozen, Errors.RESERVE_FROZEN);
require(borrowingEnabled, Errors.BORROWING_NOT_ENABLED);

// Borrow cap check
uint256 borrowCap = reserveConfiguration.getBorrowCap();
require(
    borrowCap == 0 ||
        (totalDebt + amount) <= borrowCap * (10 ** decimals),
    Errors.BORROW_CAP_EXCEEDED
);

// If stable rate, check additional constraints
if (interestRateMode == STABLE) {
    require(stableBorrowingEnabled, Errors.STABLE_BORROWING_NOT_ENABLED);
    require(!userConfig.isUsingAsCollateral(reserve.id), Errors.COLLATERAL_SAME_AS_BORROWING_CURRENCY);
    // Stable borrows limited to a percentage of available liquidity
}

// The critical check: health factor
(
    uint256 userCollateralInBaseCurrency,
    uint256 userDebtInBaseCurrency,
    uint256 currentLtv,
    uint256 currentLiquidationThreshold,
    uint256 healthFactor,
    bool hasZeroLtvCollateral
) = GenericLogic.calculateUserAccountData(
    reservesData,
    reservesList,
    eModeCategories,
    params
);

require(userCollateralInBaseCurrency != 0, Errors.COLLATERAL_BALANCE_IS_ZERO);
require(currentLtv != 0, Errors.LTV_VALIDATION_FAILED);

// After adding this borrow, health factor must still be > 1
require(
    healthFactor > HEALTH_FACTOR_LIQUIDATION_THRESHOLD,
    Errors.HEALTH_FACTOR_LOWER_THAN_LIQUIDATION_THRESHOLD
);

// Check that the new borrow doesn't exceed the user's borrowing power
uint256 amountInBaseCurrency = IPriceOracleGetter(oracle)
    .getAssetPrice(asset)
    .mul(amount)
    .div(10 ** decimals);
require(
    (userDebtInBaseCurrency + amountInBaseCurrency) <=
        userCollateralInBaseCurrency.percentMul(currentLtv),
    Errors.COLLATERAL_CANNOT_COVER_NEW_BORROW
);
```

The health factor calculation iterates over all reserves where the user has positions, sums their collateral (weighted by liquidation thresholds) and their debt, and computes:

```
healthFactor = (totalCollateralInBaseCurrency * weightedAvgLiquidationThreshold) / totalDebtInBaseCurrency
```

This must remain above `1.0` (represented as `1e18` in Aave) after the new borrow.

### Step 3: Mint Debt Tokens

For variable borrows (the common path):

```solidity
(isFirstBorrowing, reserveCache.nextScaledVariableDebt) = IVariableDebtToken(
    reserveCache.variableDebtTokenAddress
).mint(params.user, params.onBehalfOf, params.amount, reserveCache.nextVariableBorrowIndex);
```

As detailed in Chapter 5, this stores `amount / variableBorrowIndex` as the user's scaled debt balance. The returned `nextScaledVariableDebt` is the updated total supply, which is cached for the subsequent interest rate update.

### Step 7: Transfer Underlying

The borrowed assets are transferred from the aToken contract (which holds all the underlying) to the borrower:

```solidity
IAToken(reserveCache.aTokenAddress).transferUnderlyingTo(
    params.user,
    params.amount
);
```

This calls the aToken's `transferUnderlyingTo()` function, which performs a simple `safeTransfer` of the underlying token. The aToken contract is the vault, and only the Pool (via the `onlyPool` modifier) can trigger withdrawals from it.

---

## Repay Flow

<video src="../animations/final/repay_withdraw.webm" controls autoplay loop muted playsinline style="width:100%;max-width:800px;border-radius:8px;margin:20px 0"></video>

### The User's Perspective

A user calls `Pool.repay()` to pay back their debt:

```solidity
function repay(
    address asset,
    uint256 amount,
    uint256 interestRateMode,
    address onBehalfOf
) external virtual override returns (uint256) {
    return BorrowLogic.executeRepay(
        _reserves,
        _reservesList,
        _usersConfig[onBehalfOf],
        DataTypes.ExecuteRepayParams({
            asset: asset,
            amount: amount,
            interestRateMode: DataTypes.InterestRateMode(interestRateMode),
            onBehalfOf: onBehalfOf,
            useATokens: false
        })
    );
}
```

A key feature: passing `type(uint256).max` as `amount` means "repay my entire debt." The protocol will compute the exact debt and repay that amount.

### Inside BorrowLogic.executeRepay()

```solidity
function executeRepay(
    mapping(address => DataTypes.ReserveData) storage reservesData,
    mapping(uint256 => address) storage reservesList,
    DataTypes.UserConfigurationMap storage userConfig,
    DataTypes.ExecuteRepayParams memory params
) external returns (uint256) {
    DataTypes.ReserveData storage reserve = reservesData[params.asset];
    DataTypes.ReserveCache memory reserveCache = reserve.cache();

    // Step 1: Update indexes
    reserve.updateState(reserveCache);

    // Step 2: Determine the actual repay amount
    uint256 variableDebt = IERC20(reserveCache.variableDebtTokenAddress)
        .balanceOf(params.onBehalfOf);
    uint256 stableDebt = IERC20(reserveCache.stableDebtTokenAddress)
        .balanceOf(params.onBehalfOf);

    // Validate
    ValidationLogic.validateRepay(
        reserveCache,
        params.amount,
        params.interestRateMode,
        params.onBehalfOf,
        stableDebt,
        variableDebt
    );

    // Determine actual repay amount
    uint256 paybackAmount;
    if (params.interestRateMode == DataTypes.InterestRateMode.VARIABLE) {
        paybackAmount = variableDebt;
    } else {
        paybackAmount = stableDebt;
    }

    // If user passed a specific amount less than full debt, use that
    if (params.amount < paybackAmount) {
        paybackAmount = params.amount;
    }

    // Step 3: Burn debt tokens
    if (params.interestRateMode == DataTypes.InterestRateMode.VARIABLE) {
        reserveCache.nextScaledVariableDebt = IVariableDebtToken(
            reserveCache.variableDebtTokenAddress
        ).burn(params.onBehalfOf, paybackAmount, reserveCache.nextVariableBorrowIndex);
    } else {
        (
            reserveCache.nextTotalStableDebt,
            reserveCache.nextAvgStableBorrowRate
        ) = IStableDebtToken(reserveCache.stableDebtTokenAddress).burn(
            params.onBehalfOf,
            paybackAmount
        );
    }

    // Step 4: Update interest rates
    reserve.updateInterestRates(
        reserveCache,
        params.asset,
        params.useATokens ? 0 : paybackAmount,  // liquidityAdded
        0                                          // liquidityRemoved
    );

    // Step 5: Transfer underlying from user to aToken contract
    if (params.useATokens) {
        // Special path: repay with aTokens (burn aTokens instead of transferring underlying)
        IAToken(reserveCache.aTokenAddress).burn(
            msg.sender,
            reserveCache.aTokenAddress,
            paybackAmount,
            reserveCache.nextLiquidityIndex
        );
    } else {
        // Normal path: transfer underlying from user
        IERC20(params.asset).safeTransferFrom(
            msg.sender,
            reserveCache.aTokenAddress,
            paybackAmount
        );
    }

    // Step 6: If fully repaid, clear borrowing flag
    if (stableDebt + variableDebt - paybackAmount == 0) {
        userConfig.setBorrowing(reserve.id, false);
    }

    emit Repay(params.asset, params.onBehalfOf, msg.sender, paybackAmount, params.useATokens);

    return paybackAmount;
}
```

### The type(uint256).max Pattern

When a user wants to fully repay their debt, they cannot know the exact amount because interest accrues every second. By the time their transaction is mined, the debt may be slightly higher than when they submitted it.

Aave solves this with a convention: pass `type(uint256).max` (the maximum uint256 value) as the amount, and the protocol interprets this as "repay everything":

```solidity
if (params.amount < paybackAmount) {
    paybackAmount = params.amount;
}
// If params.amount == type(uint256).max, this condition is false,
// and paybackAmount stays at the full debt amount.
```

The user must approve more than enough tokens for the transfer. The protocol only transfers exactly what is owed. Any excess approval is not consumed.

### Repay With aTokens

Notice the `useATokens` parameter. If set to `true`, instead of transferring underlying tokens from the user, the protocol burns the user's aTokens:

```solidity
if (params.useATokens) {
    IAToken(reserveCache.aTokenAddress).burn(
        msg.sender,
        reserveCache.aTokenAddress,
        paybackAmount,
        reserveCache.nextLiquidityIndex
    );
}
```

This lets a user repay debt using their supply position in the same asset. For example, if you supplied 2000 USDC and borrowed 500 USDC, you can repay the 500 USDC borrow by burning 500 aUSDC, without needing to hold any USDC in your wallet.

---

## Withdraw Flow

### The User's Perspective

A user calls `Pool.withdraw()` to redeem their aTokens for underlying assets:

```solidity
function withdraw(
    address asset,
    uint256 amount,
    address to
) external virtual override returns (uint256) {
    return SupplyLogic.executeWithdraw(
        _reserves,
        _reservesList,
        _eModeCategories,
        _usersConfig[msg.sender],
        DataTypes.ExecuteWithdrawParams({
            asset: asset,
            amount: amount,
            to: to,
            reservesCount: _reservesCount,
            oracle: IPoolAddressesProvider(_addressesProvider).getPriceOracle(),
            userEModeCategory: _usersEModeCategory[msg.sender]
        })
    );
}
```

Like repay, passing `type(uint256).max` as the amount means "withdraw everything."

### Inside SupplyLogic.executeWithdraw()

```solidity
function executeWithdraw(
    mapping(address => DataTypes.ReserveData) storage reservesData,
    mapping(uint256 => address) storage reservesList,
    mapping(uint8 => DataTypes.EModeCategory) storage eModeCategories,
    DataTypes.UserConfigurationMap storage userConfig,
    DataTypes.ExecuteWithdrawParams memory params
) external returns (uint256) {
    DataTypes.ReserveData storage reserve = reservesData[params.asset];
    DataTypes.ReserveCache memory reserveCache = reserve.cache();

    // Step 1: Update indexes
    reserve.updateState(reserveCache);

    // Step 2: Determine actual withdraw amount
    uint256 userBalance = IAToken(reserveCache.aTokenAddress)
        .balanceOf(msg.sender);

    uint256 amountToWithdraw = params.amount;
    if (params.amount == type(uint256).max) {
        amountToWithdraw = userBalance;
    }

    // Step 3: Validate
    ValidationLogic.validateWithdraw(
        reserveCache,
        amountToWithdraw,
        userBalance
    );

    // Step 4: Update interest rates
    reserve.updateInterestRates(
        reserveCache,
        params.asset,
        0,                  // liquidityAdded
        amountToWithdraw    // liquidityRemoved
    );

    // Step 5: Burn aTokens and transfer underlying
    bool isCollateral = userConfig.isUsingAsCollateral(reserve.id);

    IAToken(reserveCache.aTokenAddress).burn(
        msg.sender,
        params.to,
        amountToWithdraw,
        reserveCache.nextLiquidityIndex
    );

    // Step 6: If withdrawing all, disable as collateral
    if (isCollateral && amountToWithdraw == userBalance) {
        userConfig.setUsingAsCollateral(reserve.id, false);
        emit ReserveUsedAsCollateralDisabled(params.asset, msg.sender);
    }

    // Step 7: Validate health factor (critical!)
    if (userConfig.isBorrowingAny()) {
        require(
            GenericLogic.calculateUserAccountData(
                reservesData,
                reservesList,
                eModeCategories,
                // ... params
            ).healthFactor > HEALTH_FACTOR_LIQUIDATION_THRESHOLD,
            Errors.HEALTH_FACTOR_LOWER_THAN_LIQUIDATION_THRESHOLD
        );
    }

    emit Withdraw(params.asset, msg.sender, params.to, amountToWithdraw);

    return amountToWithdraw;
}
```

### The Health Factor Check

The critical difference between withdrawal and supply is the **post-operation health factor check**. When a user withdraws collateral, they may be reducing the backing for their existing borrows. The protocol must ensure they remain solvent.

This check only applies if the user has any active borrows (`userConfig.isBorrowingAny()`). If the user has no borrows, they can withdraw freely.

If the user has borrows, the protocol calculates what the health factor would be after the withdrawal. If it would drop to or below `1.0`, the transaction reverts. This prevents users from creating undercollateralized positions by withdrawing too much collateral.

This is why the health factor check happens **after** the aToken burn --- the protocol simulates the final state and validates it.

---

## The updateState() + updateInterestRates() Pattern

Every operation in Aave V3 follows the same bookkeeping rhythm:

1. **updateState()** at the beginning --- bring indexes current.
2. **Execute the operation** --- mint/burn tokens, transfer assets.
3. **updateInterestRates()** at the end --- recalculate rates.

This pattern is the heartbeat of the protocol. Let's examine why both are necessary and why they happen in this order.

### Why updateState() Comes First

Indexes must be current before any token operation because mint and burn amounts depend on the index:

```
scaledAmount = amount / currentIndex
```

If the index is stale (reflecting prices from 10 minutes ago instead of now), the wrong number of scaled tokens will be minted or burned. This would create an accounting discrepancy that compounds over time.

`updateState()` also accrues treasury revenue. If this is skipped, the treasury misses its share of interest for the elapsed period.

### Why updateInterestRates() Comes Last

After the operation executes, the reserve's supply and demand have changed:

- **Supply** increases available liquidity and decreases utilization.
- **Borrow** decreases available liquidity and increases utilization.
- **Repay** increases available liquidity and decreases utilization.
- **Withdraw** decreases available liquidity and increases utilization.

The interest rates must be recalculated to reflect the new utilization:

| Operation | Utilization Change | Rate Effect              |
|-----------|-------------------|--------------------------|
| Supply    | Decreases         | Rates decrease           |
| Borrow    | Increases         | Rates increase           |
| Repay     | Decreases         | Rates decrease           |
| Withdraw  | Increases         | Rates increase           |

The new rates are written to storage and will be used by the next `updateState()` call to compute index growth. This creates a feedback loop:

```
updateState() → uses stored rates to compute index growth
                  ↓
Execute operation → changes supply/demand
                  ↓
updateInterestRates() → computes new rates based on new utilization
                  ↓
(next operation) → updateState() uses these new rates
```

### The Reserve Cache

You may have noticed that many functions receive a `ReserveCache memory` parameter. This is a gas optimization. Rather than reading from storage multiple times (which costs 2100 gas for a cold `SLOAD` or 100 gas for a warm one), the protocol reads all needed reserve data once into a memory struct at the beginning of the operation:

```solidity
DataTypes.ReserveCache memory reserveCache = reserve.cache();
```

The cache contains:
- Current and next liquidity index
- Current and next variable borrow index
- Current and next total stable debt
- Current and next average stable borrow rate
- Current scaled variable debt
- Reserve factor
- Token addresses (aToken, stable debt, variable debt)
- Reserve configuration

Functions read from the cache and write "next" values into it as the operation progresses. Only at the end are the final values committed to storage. This pattern saves significant gas, especially for operations that touch many reserve fields.

### Why This Design Is Robust

The update-execute-update pattern has several important properties:

1. **No stale data**: Every operation starts with fresh indexes. There is no window where a stale index can cause incorrect calculations.

2. **Atomic consistency**: All changes to a reserve (indexes, rates, balances, treasury) happen within a single transaction. There is no intermediate state visible to other transactions.

3. **Self-correcting rates**: If no one interacts with a reserve for hours, the first interaction catches up all accumulated interest in one shot. The indexes grow to reflect the elapsed time, and rates are recalculated for the new state. There is no "missed interest" problem.

4. **Composability**: External protocols can safely interact with Aave knowing that a single call to `supply()`, `borrow()`, `repay()`, or `withdraw()` handles all internal accounting. There is no need to call `updateState()` separately.

---

## Summary

This chapter walked through the four core operations that make Aave V3 function as a lending protocol.

**Key takeaways:**

- **All operations flow through the Pool contract**, which delegates to library contracts (`SupplyLogic`, `BorrowLogic`) for the actual logic.
- **Supply** transfers underlying to the aToken vault, mints scaled aTokens, and auto-enables collateral for first-time suppliers.
- **Borrow** validates solvency (health factor > 1), mints scaled debt tokens, and transfers underlying from the aToken vault to the borrower.
- **Repay** burns debt tokens, transfers underlying back to the aToken vault, and clears the borrow flag on full repayment. The `type(uint256).max` pattern handles exact full repayments.
- **Withdraw** burns aTokens, transfers underlying to the user, and validates that the health factor remains above 1 if the user has active borrows.
- **Every operation follows the same pattern**: `updateState()` first (bring indexes current), execute the operation, `updateInterestRates()` last (recalculate for new utilization).
- **The reserve cache** is a gas optimization that reads all reserve data into memory once, avoiding repeated storage reads.

These four operations, combined with the accounting primitives from the previous chapters, form the core lending and borrowing engine of Aave V3. The next chapter covers what happens when things go wrong: liquidations.
