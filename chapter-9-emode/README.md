# Chapter 9: E-Mode (Efficiency Mode)

Aave V3 treats all assets as independent by default. ETH has its own LTV, USDC has its own LTV, and every borrowing position is evaluated using these per-asset parameters. This is the safe default --- assets with different volatility profiles should have different risk parameters.

But sometimes a user is borrowing one asset against another that is highly correlated. Borrowing USDC against DAI. Borrowing stETH against WETH. Borrowing WBTC against BTC. In these cases, the risk of the collateral losing value relative to the debt is dramatically lower than the general case. Forcing a user to overcollateralize by 25% when the two assets are pegged to the same underlying is capital-inefficient.

E-Mode (Efficiency Mode) solves this. It allows Aave to define categories of correlated assets and assign them boosted risk parameters --- higher LTV, higher liquidation threshold, and lower liquidation bonus. Users who opt into an E-Mode category get significantly better capital efficiency for positions involving correlated assets.

<video src="../animations/final/emode_comparison.webm" controls autoplay loop muted playsinline style="width:100%;max-width:800px;border-radius:8px;margin:20px 0"></video>

---

## 1. What E-Mode Solves

Consider a user who wants to borrow DAI using USDC as collateral. Both are USD stablecoins. Under normal parameters:

- USDC LTV: ~77%
- Supply $10,000 USDC, borrow up to ~$7,700 DAI

But USDC and DAI are both pegged to $1. The chance that USDC drops to $0.95 while DAI stays at $1.00 (or vice versa) is extremely low. The overcollateralization is protecting against a risk that barely exists.

With E-Mode for stablecoins:

- E-Mode LTV: 93%
- Supply $10,000 USDC, borrow up to ~$9,300 DAI

That is $1,600 more borrowing power from the same collateral. For users running delta-neutral strategies, providing liquidity, or doing yield farming, this difference is enormous.

The same logic applies to ETH-correlated assets. If you are supplying stETH and borrowing WETH, both track the price of ETH. The risk of divergence is much lower than, say, borrowing USDC against ETH. E-Mode captures this reduced risk in the protocol's math.

---

## 2. E-Mode Categories

An E-Mode category is a named group of correlated assets with custom risk parameters. Each category is defined by:

```solidity
// From DataTypes.sol
struct EModeCategory {
    uint16 ltv;                  // Custom LTV (in basis points, e.g., 9300 = 93%)
    uint16 liquidationThreshold; // Custom liquidation threshold (e.g., 9500 = 95%)
    uint16 liquidationBonus;     // Custom liquidation bonus (e.g., 10100 = 1%)
    address priceSource;         // Optional custom oracle (address(0) = use default)
    string label;                // Human-readable label (e.g., "Stablecoins")
}
```

Key fields:

- **`ltv`**: The maximum loan-to-value ratio when both collateral and debt belong to this category. Stored in basis points --- 9300 means 93%.
- **`liquidationThreshold`**: The threshold at which the position becomes liquidatable. Typically slightly above the LTV. Stored in basis points --- 9500 means 95%.
- **`liquidationBonus`**: The bonus a liquidator receives. Stored as 10000 + bonus. A value of 10100 means a 1% bonus (the liquidator gets $101 of collateral per $100 of debt repaid). This is lower than the default 5-10% bonus because correlated assets carry less risk.
- **`priceSource`**: An optional custom oracle. If set, the protocol uses this oracle to price assets in the category instead of the default Chainlink feeds. This is powerful for stablecoins --- you can set a fixed 1:1 oracle to avoid spurious liquidations from minor depeg events.
- **`label`**: A human-readable string like "ETH correlated" or "Stablecoins".

### Category ID

Each category has a `uint8` ID. Category 0 is special --- it means "no E-Mode" and is the default for all users.

Categories are stored in the Pool's state:

```solidity
// In PoolStorage.sol
mapping(uint8 => DataTypes.EModeCategory) internal _eModeCategories;
```

### Asset-to-Category Mapping

Each reserve can be assigned to an E-Mode category by governance. This is stored in the reserve configuration bitmap:

```solidity
// From ReserveConfiguration.sol
uint256 internal constant EMODE_CATEGORY_MASK =
    0xFFFFFFFFFFFFFFFFFFFF00FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF;
uint256 internal constant EMODE_CATEGORY_START_BIT_POSITION = 168;

function getEModeCategory(
    DataTypes.ReserveConfigurationMap memory self
) internal pure returns (uint256) {
    return (self.data & ~EMODE_CATEGORY_MASK) >> EMODE_CATEGORY_START_BIT_POSITION;
}
```

An asset with E-Mode category 1 (e.g., "Stablecoins") can participate in E-Mode 1 positions. An asset with category 0 cannot participate in any E-Mode.

Governance assigns categories via `PoolConfigurator.setAssetEModeCategory(asset, categoryId)`. A typical deployment might look like:

| Asset  | Default LTV | Default Liq. Threshold | E-Mode Category |
|--------|-------------|------------------------|------------------|
| USDC   | 77%         | 80%                    | 1 (Stablecoins)  |
| DAI    | 67%         | 77%                    | 1 (Stablecoins)  |
| USDT   | 75%         | 78%                    | 1 (Stablecoins)  |
| WETH   | 80%         | 82.5%                  | 2 (ETH correlated)|
| stETH  | 69%         | 79.5%                  | 2 (ETH correlated)|
| wstETH | 69%         | 79.5%                  | 2 (ETH correlated)|
| WBTC   | 70%         | 75%                    | 0 (none)          |

E-Mode Category 1 (Stablecoins): LTV 93%, Liquidation Threshold 95%, Liquidation Bonus 1%
E-Mode Category 2 (ETH correlated): LTV 93%, Liquidation Threshold 95%, Liquidation Bonus 1%

---

## 3. How E-Mode Modifies Risk Parameters

<video src="../animations/final/emode_barchart.webm" controls autoplay loop muted playsinline style="width:100%;max-width:800px;border-radius:8px;margin:20px 0"></video>

When a user activates E-Mode for category X, the protocol changes how it evaluates their health factor. Instead of using each asset's default LTV and liquidation threshold, it substitutes the E-Mode category's values --- but only for assets that belong to the active category.

The critical function is `GenericLogic.calculateUserAccountData()`. This is called whenever the protocol needs to determine a user's borrowing capacity or health factor --- during borrows, withdrawals, liquidation checks, and E-Mode changes.

Here is how it handles E-Mode:

```solidity
function calculateUserAccountData(
    mapping(address => DataTypes.ReserveData) storage reservesData,
    mapping(uint256 => address) storage reservesList,
    mapping(uint8 => DataTypes.EModeCategory) storage eModeCategories,
    DataTypes.CalculateUserAccountDataParams memory params
) internal view returns (
    uint256 totalCollateralBase,
    uint256 totalDebtBase,
    uint256 avgLtv,
    uint256 avgLiquidationThreshold,
    uint256 healthFactor,
    bool hasZeroLtvCollateral
) {
    // ...

    // If the user is in E-Mode, load the category parameters
    if (params.userEModeCategory != 0) {
        vars.eModeCategory = eModeCategories[params.userEModeCategory];
        vars.eModePriceSource = vars.eModeCategory.priceSource;
        vars.eModeLtv = vars.eModeCategory.ltv;
        vars.eModeLiqThreshold = vars.eModeCategory.liquidationThreshold;
    }
```

Then, for each asset in the user's portfolio:

```solidity
    while (vars.i < params.reservesCount) {
        // ... load the reserve and check if the user is using it ...

        // Get the asset's E-Mode category
        uint256 assetEModeCategory = currentReserveConfiguration.getEModeCategory();

        // Determine which LTV and liquidation threshold to use
        uint256 currentLtv;
        uint256 currentLiquidationThreshold;

        if (params.userEModeCategory != 0 && assetEModeCategory == params.userEModeCategory) {
            // Asset belongs to the user's E-Mode category: use E-Mode parameters
            currentLtv = vars.eModeLtv;
            currentLiquidationThreshold = vars.eModeLiqThreshold;
        } else {
            // Asset does not belong to the E-Mode category: use default parameters
            currentLtv = currentReserveConfiguration.getLtv();
            currentLiquidationThreshold = currentReserveConfiguration.getLiquidationThreshold();
        }
```

This is a per-asset check. If a user is in E-Mode category 1 (Stablecoins) and they have USDC (category 1) and WETH (category 2), only the USDC gets the boosted parameters. The WETH uses its default LTV and liquidation threshold.

### The Weighted Average

The health factor is not calculated per-asset --- it uses a **weighted average** of LTV and liquidation threshold across all collateral:

```solidity
    // Accumulate weighted values
    if (isUsingAsCollateral) {
        vars.totalCollateralInBaseCurrency += vars.userBalanceInBaseCurrency;
        vars.avgLtv += vars.userBalanceInBaseCurrency * currentLtv;
        vars.avgLiquidationThreshold +=
            vars.userBalanceInBaseCurrency * currentLiquidationThreshold;
    }

    if (isUsingAsBorrow) {
        vars.totalDebtInBaseCurrency += vars.userDebtInBaseCurrency;
    }
```

After the loop:

```solidity
    // Calculate weighted averages
    vars.avgLtv = vars.totalCollateralInBaseCurrency != 0
        ? vars.avgLtv / vars.totalCollateralInBaseCurrency
        : 0;
    vars.avgLiquidationThreshold = vars.totalCollateralInBaseCurrency != 0
        ? vars.avgLiquidationThreshold / vars.totalCollateralInBaseCurrency
        : 0;

    // Health Factor = (totalCollateral * avgLiquidationThreshold) / totalDebt
    vars.healthFactor = (vars.totalDebtInBaseCurrency == 0)
        ? type(uint256).max
        : (vars.totalCollateralInBaseCurrency.percentMul(vars.avgLiquidationThreshold))
            .wadDiv(vars.totalDebtInBaseCurrency);
```

If 90% of the user's collateral is in the E-Mode category, the weighted average will be close to the E-Mode parameters. If only 10% is in the category, the benefit is marginal.

---

## 4. Setting User E-Mode

A user activates E-Mode by calling `Pool.setUserEMode(categoryId)`:

```solidity
// In Pool.sol
function setUserEMode(uint8 categoryId) external virtual override {
    EModeLogic.executeSetUserEMode(
        _reserves,
        _reservesList,
        _eModeCategories,
        _usersEModeCategory,
        _usersConfig[msg.sender],
        DataTypes.ExecuteSetUserEModeParams({
            reservesCount: _reservesCount,
            oracle: IPoolAddressesProvider(_addressesProvider).getPriceOracle(),
            categoryId: categoryId
        })
    );
}
```

The implementation in `EModeLogic.executeSetUserEMode()` does the following:

### Step 1: Validate Borrows

If the user is switching to a non-zero category, the function checks that all of the user's current borrows are allowed in the new E-Mode category:

```solidity
function executeSetUserEMode(
    mapping(address => DataTypes.ReserveData) storage reservesData,
    mapping(uint256 => address) storage reservesList,
    mapping(uint8 => DataTypes.EModeCategory) storage eModeCategories,
    mapping(address => uint8) storage usersEModeCategory,
    DataTypes.UserConfigurationMap storage userConfig,
    DataTypes.ExecuteSetUserEModeParams memory params
) external {
    // If entering an E-Mode (not exiting to 0), validate borrows
    if (params.categoryId != 0) {
        // Iterate over all reserves
        // For each reserve the user is borrowing:
        //   check that the reserve's E-Mode category == params.categoryId
        ValidationLogic.validateSetUserEMode(
            reservesData,
            reservesList,
            userConfig,
            params.reservesCount,
            params.categoryId
        );
    }
```

The validation iterates through the user's borrowed assets and ensures each one belongs to the target E-Mode category:

```solidity
function validateSetUserEMode(
    mapping(address => DataTypes.ReserveData) storage reservesData,
    mapping(uint256 => address) storage reservesList,
    DataTypes.UserConfigurationMap memory userConfig,
    uint256 reservesCount,
    uint8 categoryId
) internal view {
    // For each reserve the user is borrowing...
    for (uint256 i = 0; i < reservesCount; i++) {
        if (userConfig.isBorrowing(i)) {
            address reserveAddress = reservesList[i];
            DataTypes.ReserveConfigurationMap memory config =
                reservesData[reserveAddress].configuration;

            require(
                config.getEModeCategory() == categoryId,
                Errors.INCONSISTENT_EMODE_CATEGORY
            );
        }
    }
}
```

This is a strict check. You cannot enter E-Mode category 1 (Stablecoins) if you are currently borrowing WETH (category 2). You would need to repay the WETH borrow first.

Note: the check is only on **borrows**, not on collateral. You can have any collateral while in E-Mode. Only collateral that matches the E-Mode category gets the boosted parameters --- other collateral simply uses its default parameters.

### Step 2: Set the Category

```solidity
    // Store the user's new E-Mode category
    usersEModeCategory[msg.sender] = params.categoryId;
```

### Step 3: Validate Health Factor

After changing the E-Mode, the function recalculates the user's health factor with the new parameters:

```solidity
    // Recalculate health factor with the new E-Mode parameters
    (, , , , uint256 healthFactor, ) = GenericLogic.calculateUserAccountData(
        reservesData,
        reservesList,
        eModeCategories,
        DataTypes.CalculateUserAccountDataParams({
            userConfig: userConfig,
            reservesCount: params.reservesCount,
            user: msg.sender,
            oracle: params.oracle,
            userEModeCategory: params.categoryId
        })
    );

    require(
        healthFactor >= HEALTH_FACTOR_LIQUIDATION_THRESHOLD,
        Errors.HEALTH_FACTOR_LOWER_THAN_LIQUIDATION_THRESHOLD
    );
```

This is critical. If the user is exiting E-Mode (setting category to 0), their risk parameters revert to the per-asset defaults, which are lower. This means their health factor will decrease. If the health factor drops below 1, the transaction reverts --- the user cannot exit E-Mode if doing so would make them immediately liquidatable.

### Exiting E-Mode

To exit E-Mode, the user calls `setUserEMode(0)`. The same function runs:
- No borrow validation is needed (category 0 has no restrictions)
- The health factor is recalculated using default parameters
- If the health factor is still >= 1, the exit succeeds

If the user's position is too leveraged to survive the switch back to default parameters, they must either repay some debt or add more collateral before exiting.

---

## 5. E-Mode Oracle Override

One of the most powerful features of E-Mode is the optional custom price oracle. When an E-Mode category has a non-zero `priceSource`, the protocol uses that oracle to price all assets in the category.

### Why This Matters

Consider the stablecoin E-Mode category. USDC, DAI, and USDT are all supposed to be worth $1. But Chainlink price feeds report real market prices, and stablecoins occasionally depeg slightly. If DAI drops to $0.997 on Chainlink while USDC stays at $1.000, a user borrowing DAI against USDC could face an unnecessary liquidation --- even though the actual risk is negligible.

A custom oracle can be set to price all stablecoins at exactly $1.00, eliminating liquidations caused by minor price fluctuations between pegged assets. The health factor becomes a function of the quantity borrowed, not market microstructure noise.

### How It Works in the Code

In `GenericLogic.calculateUserAccountData()`, when determining asset prices:

```solidity
    // If E-Mode has a custom price source, use it for assets in the category
    uint256 assetPrice;
    if (
        vars.eModePriceSource != address(0) &&
        assetEModeCategory == params.userEModeCategory
    ) {
        assetPrice = IPriceOracleGetter(vars.eModePriceSource).getAssetPrice(
            currentReserveAddress
        );
    } else {
        assetPrice = IPriceOracleGetter(params.oracle).getAssetPrice(
            currentReserveAddress
        );
    }
```

If the E-Mode category has a price source and the asset belongs to that category, the custom oracle is used. Otherwise, the default Aave price oracle is used.

### The Trade-off

Custom oracles introduce trust assumptions. A fixed 1:1 oracle for stablecoins means that even if a stablecoin genuinely depegs to $0.80, the protocol still treats it as $1.00 within E-Mode. This could lead to bad debt if the depeg is severe and persistent.

In practice, this risk is managed by:
1. Only applying custom oracles to genuinely correlated assets
2. Governance monitoring and the ability to remove assets from E-Mode categories
3. The debt ceiling mechanism (discussed in the next chapter) providing an additional safety layer

Most Aave V3 deployments use the default oracle even for E-Mode categories, relying solely on the boosted LTV and liquidation threshold parameters for capital efficiency. The custom oracle is available as a governance tool but is used conservatively.

---

## 6. Practical Examples

### Example 1: Stablecoin E-Mode

**Without E-Mode:**

| Parameter | Value |
|-----------|-------|
| Supply | 10,000 USDC |
| USDC default LTV | 77% |
| Max borrow | 7,700 DAI |
| Capital locked (not borrowable) | 2,300 USDC |

**With E-Mode (Stablecoin category):**

| Parameter | Value |
|-----------|-------|
| Supply | 10,000 USDC |
| E-Mode LTV | 93% |
| Max borrow | 9,300 DAI |
| Capital locked (not borrowable) | 700 USDC |

Capital efficiency improvement: the user can borrow **$1,600 more** from the same collateral. The locked capital drops from $2,300 to $700 --- a 70% reduction in idle capital.

For a yield farmer who supplies USDC and borrows DAI to deploy elsewhere, this means significantly higher effective leverage and returns.

### Example 2: ETH Correlated E-Mode

A user wants to leverage their stETH exposure. stETH earns staking yield (~3-4% APR), and the user wants to amplify it.

**Without E-Mode:**

| Parameter | Value |
|-----------|-------|
| Supply | 100 stETH (worth ~$300,000) |
| stETH default LTV | 69% |
| Max WETH borrow | 69 WETH |
| Net exposure | 100 stETH - 69 WETH debt = 31 stETH equivalent |

**With E-Mode (ETH correlated category):**

| Parameter | Value |
|-----------|-------|
| Supply | 100 stETH (worth ~$300,000) |
| E-Mode LTV | 93% |
| Max WETH borrow | 93 WETH |
| Net exposure | 100 stETH - 93 WETH debt = 7 stETH equivalent |

The user can borrow 93 WETH instead of 69 WETH. If they use the borrowed WETH to buy more stETH and supply it (the classic loop), they can build a much larger leveraged staking position.

**The looping strategy in practice:**

1. Start with 10 stETH
2. Enter ETH E-Mode
3. Supply 10 stETH, borrow 9.3 WETH (93% LTV)
4. Swap 9.3 WETH for ~9.3 stETH
5. Supply 9.3 stETH, borrow 8.65 WETH
6. Repeat...

After several loops (or via a flash loan), the user might end up with ~100 stETH supplied and ~90 WETH borrowed. They are earning staking yield on 100 stETH while paying borrow interest on 90 WETH. If the staking yield exceeds the borrow rate, the strategy is profitable --- and E-Mode makes the leverage much higher than would otherwise be possible.

### Example 3: Mixed Collateral in E-Mode

What happens if a user in Stablecoin E-Mode has mixed collateral?

| Asset | Amount | Value | E-Mode Category | LTV Used |
|-------|--------|-------|------------------|----------|
| USDC  | 8,000  | $8,000 | 1 (Stablecoins) | **93%** (E-Mode) |
| WETH  | 1 ETH  | $3,000 | 2 (ETH correlated) | **80%** (default) |

Weighted average LTV = (8000 * 93 + 3000 * 80) / 11000 = **89.45%**

Max borrow = $11,000 * 89.45% = **$9,839** (only stablecoins, since borrows must match E-Mode category)

The WETH contributes as collateral using its default LTV. Only the USDC gets the E-Mode boost. The user's borrowing power is a blend of the two parameter sets, weighted by collateral value.

---

## 7. E-Mode and Liquidations

When a position in E-Mode is liquidated, the E-Mode liquidation parameters apply.

### Lower Liquidation Bonus

The E-Mode liquidation bonus is typically much lower than the default. For stablecoins:

- Default liquidation bonus: ~5% (10500 in basis points encoding)
- E-Mode liquidation bonus: ~1% (10100 in basis points encoding)

This makes sense. If you are being liquidated on a stablecoin-against-stablecoin position, the price deviation is small. The liquidator does not need a 5% bonus to be incentivized --- a 1% bonus on a large stable position is still profitable.

### How Liquidation Checks E-Mode

In `LiquidationLogic.executeLiquidationCall()`, the function loads the user's E-Mode category and passes it through to the health factor calculation:

```solidity
(
    vars.userCollateralInBaseCurrency,
    vars.userDebtInBaseCurrency,
    ,
    vars.avgLiquidationThreshold,
    vars.healthFactor,
) = GenericLogic.calculateUserAccountData(
    reservesData,
    reservesList,
    eModeCategories,
    DataTypes.CalculateUserAccountDataParams({
        userConfig: userConfig,
        reservesCount: params.reservesCount,
        user: params.user,
        oracle: params.priceOracle,
        userEModeCategory: usersEModeCategory[params.user]
    })
);
```

The health factor already incorporates the E-Mode parameters. If the health factor is below 1, the position is liquidatable.

When calculating the liquidation bonus to give the liquidator:

```solidity
// Determine which liquidation bonus to use
uint256 liquidationBonus;
if (
    userEModeCategory != 0 &&
    collateralReserve.configuration.getEModeCategory() == userEModeCategory
) {
    liquidationBonus = eModeCategories[userEModeCategory].liquidationBonus;
} else {
    liquidationBonus = collateralReserve.configuration.getLiquidationBonus();
}
```

If the collateral asset belongs to the user's E-Mode category, the E-Mode liquidation bonus is used. Otherwise, the asset's default liquidation bonus applies.

### Liquidation Threshold and E-Mode

Because E-Mode gives a higher liquidation threshold (e.g., 95% vs 82.5%), positions in E-Mode tolerate much more debt relative to collateral before becoming liquidatable. A stablecoin E-Mode position with $10,000 USDC and $9,400 DAI debt is healthy (health factor = 10000 * 0.95 / 9400 = 1.01). The same position without E-Mode would have a health factor of 10000 * 0.80 / 9400 = 0.85 --- deep into liquidation territory.

This is the whole point of E-Mode. The tighter parameters are safe because the assets are correlated, and if liquidation does happen, the lower bonus is appropriate because the collateral and debt are closely priced.

---

## Key Takeaways

1. **E-Mode allows higher capital efficiency** for positions involving correlated assets. Users opt in per category and receive boosted LTV, liquidation threshold, and reduced liquidation bonus.

2. **Categories are governance-defined.** Each has an ID, custom risk parameters, an optional oracle, and a label. Category 0 is the default (no E-Mode).

3. **Only borrows are restricted.** When in E-Mode, all borrowed assets must belong to the same category. Collateral can be any asset, but only collateral in the matching category receives boosted parameters.

4. **The health factor calculation in `GenericLogic.calculateUserAccountData()`** conditionally uses E-Mode parameters for assets matching the user's active category. Non-matching assets use their default parameters.

5. **The custom oracle** is a powerful but conservative tool. It can eliminate spurious liquidations from minor price deviations between pegged assets, but introduces risk if the peg genuinely breaks.

6. **Entering E-Mode requires all borrows to match** the target category. Exiting requires the health factor to remain >= 1 under default parameters.

7. **Liquidations in E-Mode** use the E-Mode liquidation bonus and threshold, which are tighter (lower bonus, higher threshold) reflecting the lower risk of correlated asset pairs.
