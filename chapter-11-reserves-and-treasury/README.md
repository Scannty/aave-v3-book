# Chapter 11: Reserves, Treasury, and Protocol Revenue

Aave V3 is a protocol, and like any protocol that aspires to long-term sustainability, it needs revenue. Unlike a company that charges fees through an invoice, Aave's revenue is embedded directly into its smart contract logic. Every borrow, every flash loan, every liquidation --- the protocol silently skims a small percentage and directs it to the Aave treasury. This chapter explains exactly how that works, what the treasury holds, and how governance configures the parameters that control revenue.

---

## 1. How Aave Generates Revenue

Aave has three sources of revenue:

1. **Reserve factor** --- a percentage of all borrow interest that goes to the protocol instead of suppliers. This is the primary revenue source.
2. **Flash loan premiums** --- a portion of the flash loan fee is directed to the treasury.
3. **Liquidation protocol fee** --- a cut of the liquidation bonus goes to the treasury (new in V3).

All three are configurable by governance, per asset. All three ultimately result in aTokens being minted to the treasury address. The treasury is, in effect, just another aToken holder --- one that continuously accrues interest on its growing balance.

Let's examine each in detail.

---

## 2. The Reserve Factor

The reserve factor is the most important revenue parameter. It determines what percentage of borrow interest the protocol keeps for itself.

### The Concept

When borrowers pay interest, that interest doesn't all go to suppliers. A portion --- the reserve factor --- is diverted to the Aave treasury. If the reserve factor for USDC is 10%, then for every dollar of interest paid by USDC borrowers, 90 cents goes to USDC suppliers and 10 cents goes to the Aave treasury.

This directly affects the supply rate. Recall the supply rate formula from Chapter 2:

```
supplyRate = borrowRate * utilizationRate * (1 - reserveFactor)
```

The `(1 - reserveFactor)` term is the protocol's cut. A higher reserve factor means more revenue for the protocol but lower yields for suppliers. Governance must balance these competing interests.

### Where It's Stored

The reserve factor is packed into the reserve's configuration bitmap. Each reserve in Aave V3 has a `ReserveConfigurationMap` that encodes dozens of parameters into a single `uint256`:

```solidity
struct ReserveConfigurationMap {
    uint256 data;
}
```

The reserve factor occupies bits 64-79 (16 bits), allowing values from 0 to 65535. In practice, this represents a percentage with two decimal places of precision (basis points). A reserve factor of 1000 means 10.00%.

```solidity
library ReserveConfiguration {
    uint256 internal constant RESERVE_FACTOR_MASK       = 0xFFFFFFFFFFFFFFFFFFFFFFFFFFFF0000FFFFFFFFFFFFFFFFFFFFFFFF;
    uint256 internal constant RESERVE_FACTOR_START_BIT_POSITION = 64;

    function setReserveFactor(
        DataTypes.ReserveConfigurationMap memory self,
        uint256 reserveFactor
    ) internal pure {
        require(reserveFactor <= MAX_VALID_RESERVE_FACTOR, Errors.INVALID_RESERVE_FACTOR);
        self.data =
            (self.data & RESERVE_FACTOR_MASK) |
            (reserveFactor << RESERVE_FACTOR_START_BIT_POSITION);
    }

    function getReserveFactor(
        DataTypes.ReserveConfigurationMap memory self
    ) internal pure returns (uint256) {
        return (self.data & ~RESERVE_FACTOR_MASK) >> RESERVE_FACTOR_START_BIT_POSITION;
    }
}
```

### Typical Values

| Asset Category | Typical Reserve Factor |
|---|---|
| Stablecoins (USDC, USDT, DAI) | 10-20% |
| Major assets (ETH, WBTC) | 10-20% |
| Volatile/newer assets | 20-35% |
| High-risk assets | 30-50% |

Higher risk assets tend to have higher reserve factors. This compensates the protocol for the additional risk of listing them and creates a buffer in case of bad debt.

---

## 3. How Treasury Accrual Works

This is where it gets interesting. The treasury doesn't receive a continuous stream of tokens. Instead, treasury revenue is tracked as a running counter and periodically "realized" by minting aTokens to the treasury address.

### The `_accrueToTreasury()` Function

Every time `reserve.updateState()` is called --- which happens on every user interaction with a reserve --- the protocol calculates how much interest has accrued to the treasury since the last update.

Here is the core logic from `ReserveLogic.sol`:

```solidity
function _accrueToTreasury(
    DataTypes.ReserveData storage reserve,
    DataTypes.ReserveCache memory reserveCache
) internal {
    uint256 prevTotalVariableDebt = reserveCache.currScaledVariableDebt.rayMul(
        reserveCache.currVariableBorrowIndex
    );

    uint256 currTotalVariableDebt = reserveCache.currScaledVariableDebt.rayMul(
        reserveCache.nextVariableBorrowIndex
    );

    uint256 prevTotalStableDebt = reserveCache.currTotalStableDebt;
    uint256 currTotalStableDebt = reserveCache.currAvgStableBorrowRate != 0
        ? reserveCache.currPrincipalStableDebt.rayMul(
            MathUtils.calculateCompoundedInterest(
                reserveCache.currAvgStableBorrowRate,
                reserveCache.stableDebtLastUpdateTimestamp,
                block.timestamp
            )
        )
        : 0;

    // Total interest accrued = new debt - old debt for both variable and stable
    uint256 totalDebtAccrued = currTotalVariableDebt +
        currTotalStableDebt -
        prevTotalVariableDebt -
        prevTotalStableDebt;

    // The treasury's share is totalDebtAccrued * reserveFactor
    uint256 amountToMint = totalDebtAccrued.percentMul(
        reserveCache.reserveConfiguration.getReserveFactor()
    );

    if (amountToMint != 0) {
        // Store as scaled amount (divide by liquidity index)
        reserve.accruedToTreasury += amountToMint
            .rayDiv(reserveCache.nextLiquidityIndex)
            .toUint128();
    }
}
```

### Breaking Down the Math

The function performs these steps:

1. **Calculate previous total debt** --- the total amount owed by all borrowers as of the last update, for both variable and stable debt.
2. **Calculate current total debt** --- the total amount owed right now, including interest that has accrued since the last update.
3. **Compute the difference** --- this is the total interest that accrued during the period.
4. **Multiply by reserve factor** --- the treasury's share of that interest.
5. **Convert to scaled amount** --- divide by the current liquidity index to store as a scaled balance (just like any other aToken holder's balance).

The result is added to `reserve.accruedToTreasury`, a running counter stored in `ReserveData`:

```solidity
struct ReserveData {
    // ...
    uint128 accruedToTreasury;
    // ...
}
```

### Why Scaled Amounts?

The treasury accrual is stored as a scaled amount --- divided by the liquidity index --- for the same reason all aToken balances are stored as scaled amounts (Chapter 3). This means the treasury's "balance" automatically grows as the liquidity index increases. The treasury earns interest on its interest, just like any supplier.

### When Are the aTokens Actually Minted?

The `accruedToTreasury` counter accumulates over many interactions. The actual minting of aTokens to the treasury happens when `mintToTreasury()` is called:

```solidity
function mintToTreasury(
    DataTypes.ReserveData storage reserve,
    DataTypes.ReserveCache memory reserveCache
) internal {
    uint256 accruedToTreasury = reserve.accruedToTreasury;

    if (accruedToTreasury != 0) {
        reserve.accruedToTreasury = 0;

        // Convert scaled amount back to actual amount
        uint256 normalizedIncome = reserve.getNormalizedIncome();
        uint256 amountToMint = accruedToTreasury.rayMul(normalizedIncome);

        // Mint aTokens to the treasury address
        IAToken(reserveCache.aTokenAddress).mintToTreasury(
            amountToMint,
            normalizedIncome
        );
    }
}
```

This is called during `updateState()`. The protocol doesn't mint a separate ERC-20 transfer for every accrual --- it batches them. The `accruedToTreasury` counter is the batching mechanism.

### Numerical Example

Suppose:
- Total variable borrow debt was 1,000,000 USDC at the last update
- The variable borrow index increased from `1.050000e27` to `1.050100e27`
- Reserve factor is 10%

Then:
```
Previous debt   = scaledDebt * 1.050000 = 1,000,000
Current debt    = scaledDebt * 1.050100 = 1,000,095.24  (approximately)
Interest accrued = 95.24 USDC
Treasury share   = 95.24 * 0.10 = 9.524 USDC
Scaled amount    = 9.524 / 1.050100 = 9.069 (stored in accruedToTreasury)
```

The suppliers receive the remaining 85.72 USDC (95.24 - 9.52) through the liquidity index increase.

---

## 4. The Treasury Contract

The treasury is not a special contract with complex logic. It is simply an address that holds aTokens. In most Aave V3 deployments, the treasury is a contract controlled by Aave governance (typically through the governance executor or a dedicated treasury controller).

### What the Treasury Holds

The treasury holds aTokens for every asset where a reserve factor is configured. Because these are aTokens, they continuously earn interest. The treasury is the largest "supplier" in many Aave markets.

For example, if the treasury holds 10 million aUSDC, and the USDC supply rate is 3%, the treasury earns 300,000 USDC per year in interest --- on top of the new aTokens being minted to it from the reserve factor.

### Treasury Address Configuration

The treasury address is set per aToken during initialization:

```solidity
function initialize(
    IPool pool,
    address treasury,
    address underlyingAsset,
    IAaveIncentivesController incentivesController,
    uint8 aTokenDecimals,
    string calldata aTokenName,
    string calldata aTokenSymbol,
    bytes calldata params
) external override initializer {
    // ...
    _treasury = treasury;
    // ...
}
```

The treasury address is typically the same across all aTokens in a deployment, but the architecture allows for different treasury addresses per asset if needed.

### Withdrawing from the Treasury

Governance can withdraw funds from the treasury to fund development, grants, bug bounties, or other protocol needs. This is done through governance proposals that call the treasury controller, which in turn redeems aTokens for the underlying assets.

---

## 5. Flash Loan Revenue

Flash loan premiums are the second source of protocol revenue. Every flash loan charges a premium, and that premium is split between suppliers and the treasury.

### The Two Premium Parameters

```solidity
// In Pool storage
uint128 internal _flashLoanPremiumTotal;      // e.g., 9 = 0.09%
uint128 internal _flashLoanPremiumToProtocol; // e.g., 0 = 0%
```

- `flashLoanPremiumTotal` --- the total premium charged on flash loans, in basis points divided by 100. A value of `9` means 0.09% (9 basis points). This is the total fee.
- `flashLoanPremiumToProtocol` --- the portion of the total premium that goes to the treasury. The remainder goes to suppliers.

The premium paid to suppliers simply stays in the aToken contract (increasing the value of all aTokens). The premium paid to the treasury is recorded in `accruedToTreasury`:

```solidity
// From FlashLoanLogic.sol (simplified)
uint256 totalPremium = amount.percentMul(flashLoanPremiumTotal);
uint256 premiumToProtocol = amount.percentMul(flashLoanPremiumToProtocol);
uint256 premiumToLP = totalPremium - premiumToProtocol;

// The premiumToLP stays in the aToken contract automatically
// (the borrower repays amount + totalPremium to the aToken)

// The premiumToProtocol is tracked for later minting
if (premiumToProtocol != 0) {
    reserve.accruedToTreasury += premiumToProtocol
        .rayDiv(reserveCache.nextLiquidityIndex)
        .toUint128();
}
```

### Flash Loan Premium for Whitelisted Borrowers

Aave V3 introduced the `FLASH_BORROWER` role. Addresses with this role pay zero premium on flash loans. This is useful for protocol integrations (e.g., liquidation bots that the protocol wants to incentivize). The check is straightforward:

```solidity
if (ACLManager.isFlashBorrower(msg.sender)) {
    // Premium is 0 for this borrower
    totalPremium = 0;
} else {
    totalPremium = amount.percentMul(flashLoanPremiumTotal);
}
```

---

## 6. Liquidation Protocol Fee

Aave V3 introduced a new revenue source: the liquidation protocol fee. When a liquidation occurs, the liquidator receives a bonus (the liquidation bonus, e.g., 5%). In V3, the protocol can take a cut of that bonus.

### How It Works

The liquidation protocol fee is configured per asset, stored in the reserve configuration bitmap. It represents the percentage of the liquidation bonus that goes to the treasury.

```solidity
// From LiquidationLogic.sol (simplified)
if (vars.liquidationProtocolFeePercentage != 0) {
    uint256 bonusCollateral = vars.actualCollateralToLiquidate - vars.actualDebtToLiquidate;
    vars.liquidationProtocolFee = bonusCollateral.percentMul(
        vars.liquidationProtocolFeePercentage
    );
    vars.actualCollateralToLiquidate -= vars.liquidationProtocolFee;
}
```

### Numerical Example

Suppose a position is liquidated:
- Debt being repaid: 1,000 USDC
- Collateral value at liquidation: 1,050 USDC worth of ETH (5% bonus)
- Liquidation protocol fee: 10% of the bonus

```
Total bonus              = 1,050 - 1,000 = 50 USDC worth of ETH
Protocol fee             = 50 * 10% = 5 USDC worth of ETH
Liquidator receives      = 1,050 - 5 = 1,045 USDC worth of ETH
Treasury receives        = 5 USDC worth of ETH (as aTokens)
```

The liquidator still profits (45 USDC worth of bonus instead of 50), but the protocol captures a portion. This creates meaningful revenue during market turbulence when liquidations are frequent.

### Where the Fee Goes

The liquidation protocol fee is sent directly to the treasury as aTokens (or the underlying collateral, depending on whether the liquidator chose to receive aTokens):

```solidity
if (vars.liquidationProtocolFee != 0) {
    // Transfer the protocol fee to the treasury
    // If liquidator receives aTokens, mint aTokens to treasury
    // If liquidator receives underlying, transfer underlying to treasury
    IAToken(vars.collateralAToken).transferOnLiquidation(
        params.user,
        IAToken(vars.collateralAToken).RESERVE_TREASURY_ADDRESS(),
        vars.liquidationProtocolFee
    );
}
```

---

## 7. Reserve Configuration Parameters

Every asset listed on Aave V3 has a comprehensive set of configurable parameters. These are all packed into the `ReserveConfigurationMap` bitmap. Here is the complete list:

| Parameter | Bits | Description |
|---|---|---|
| LTV | 0-15 | Maximum loan-to-value ratio. How much you can borrow against this collateral. E.g., 8000 = 80%. |
| Liquidation Threshold | 16-31 | At what LTV ratio positions become liquidatable. E.g., 8500 = 85%. |
| Liquidation Bonus | 32-47 | Bonus paid to liquidators. E.g., 10500 = 5% bonus (100% + 5%). |
| Decimals | 48-55 | Token decimals (e.g., 6 for USDC, 18 for ETH). |
| Active | 56 | Whether the reserve is active. If false, no operations are possible. |
| Frozen | 57 | If true, no new supply or borrow. Repay, withdraw, and liquidation still work. |
| Borrowing Enabled | 58 | Whether borrowing is allowed for this asset. |
| Stable Rate Borrowing Enabled | 59 | Whether stable rate borrowing is allowed. |
| Paused | 60 | If true, ALL operations are disabled including repay and withdraw. |
| Borrowable in Isolation | 61 | Whether this asset can be borrowed when the user is in isolation mode. |
| Siloed Borrowing | 62 | If true, borrowing this asset prevents borrowing anything else. |
| Flash Loaning Enabled | 63 | Whether this asset is available for flash loans. |
| Reserve Factor | 64-79 | Protocol's cut of borrow interest (basis points). |
| Borrow Cap | 80-115 | Maximum total borrows (in whole token units). 0 = no cap. |
| Supply Cap | 116-151 | Maximum total supply (in whole token units). 0 = no cap. |
| Liquidation Protocol Fee | 152-167 | Protocol's cut of liquidation bonus (basis points). |
| E-Mode Category | 168-175 | Which E-Mode category this asset belongs to. 0 = none. |
| Unbacked Mint Cap | 176-211 | For Portal: max unbacked aTokens that can be minted. |
| Debt Ceiling | 212-255 | For isolation mode: max debt in USD that can be borrowed against this collateral. |

All 256 bits of a single `uint256` are used. This is an extremely gas-efficient design --- reading all parameters for a reserve requires only a single storage read.

### Reading the Configuration

```solidity
// Get the full configuration for a reserve
DataTypes.ReserveConfigurationMap memory config = pool.getConfiguration(asset);

// Decode individual parameters
(uint256 ltv, uint256 liquidationThreshold, uint256 liquidationBonus,
 uint256 decimals, uint256 reserveFactor, uint256 eModeCategoryId) =
    config.getParams();

// Or read individual flags
bool isActive = config.getActive();
bool isFrozen = config.getFrozen();
bool borrowingEnabled = config.getBorrowingEnabled();
```

---

## 8. PoolConfigurator: How Governance Manages Reserves

The `PoolConfigurator` is the administrative contract through which governance manages reserve parameters. It is the only contract authorized to modify reserve configurations in the Pool. No one --- not even the Pool contract itself --- can change these parameters without going through the PoolConfigurator.

### Listing New Assets: `initReserves()`

To list a new asset on Aave, governance calls `initReserves()` on the PoolConfigurator:

```solidity
function initReserves(
    ConfiguratorInputTypes.InitReserveInput[] calldata input
) external override onlyAssetListingOrPoolAdmins {
    for (uint256 i = 0; i < input.length; i++) {
        // Deploy aToken, stableDebtToken, variableDebtToken proxies
        // Initialize them with the correct parameters
        // Register the reserve in the Pool
        // Set the interest rate strategy

        IPool(pool).initReserve(
            input[i].underlyingAsset,
            input[i].aTokenImpl,
            input[i].stableDebtTokenImpl,
            input[i].variableDebtTokenImpl,
            input[i].interestRateStrategyAddress
        );
    }
}
```

Each `InitReserveInput` specifies:
- The underlying asset address
- Implementation addresses for aToken, stable debt token, and variable debt token
- The interest rate strategy contract
- Treasury address
- Incentives controller
- Token names and symbols

### Setting the Reserve Factor

```solidity
function setReserveFactor(
    address asset,
    uint256 newReserveFactor
) external override onlyRiskOrPoolAdmins {
    DataTypes.ReserveConfigurationMap memory currentConfig = _pool.getConfiguration(asset);
    uint256 oldReserveFactor = currentConfig.getReserveFactor();

    currentConfig.setReserveFactor(newReserveFactor);
    _pool.setConfiguration(asset, currentConfig);

    emit ReserveFactorChanged(asset, oldReserveFactor, newReserveFactor);
}
```

Note the `onlyRiskOrPoolAdmins` modifier. This means either the RISK_ADMIN or POOL_ADMIN role can change the reserve factor. We cover these roles in Chapter 12.

### Configuring Collateral Parameters

```solidity
function configureReserveAsCollateral(
    address asset,
    uint256 ltv,
    uint256 liquidationThreshold,
    uint256 liquidationBonus
) external override onlyRiskOrPoolAdmins {
    DataTypes.ReserveConfigurationMap memory currentConfig = _pool.getConfiguration(asset);

    // Validation: if liquidationThreshold != 0, bonus must be > 10000
    // (because 10000 = 100%, so bonus is relative to 100%)
    if (liquidationThreshold != 0) {
        require(liquidationBonus > PercentageMath.PERCENTAGE_FACTOR, Errors.INVALID_RESERVE_PARAMS);
    }

    // Validation: LTV must be <= liquidation threshold
    require(ltv <= liquidationThreshold, Errors.INVALID_RESERVE_PARAMS);

    currentConfig.setLtv(ltv);
    currentConfig.setLiquidationThreshold(liquidationThreshold);
    currentConfig.setLiquidationBonus(liquidationBonus);

    _pool.setConfiguration(asset, currentConfig);

    emit CollateralConfigurationChanged(asset, ltv, liquidationThreshold, liquidationBonus);
}
```

### Emergency Controls

```solidity
// Freeze a reserve: no new supply or borrow, but repay/withdraw/liquidation still work
function setReserveFreeze(
    address asset,
    bool freeze
) external override onlyRiskOrPoolAdmins {
    DataTypes.ReserveConfigurationMap memory currentConfig = _pool.getConfiguration(asset);
    currentConfig.setFrozen(freeze);
    _pool.setConfiguration(asset, currentConfig);
    emit ReserveFrozen(asset, freeze);
}

// Pause a reserve: ALL operations disabled
function setReservePause(
    address asset,
    bool paused
) external override onlyPoolOrEmergencyAdmin {
    DataTypes.ReserveConfigurationMap memory currentConfig = _pool.getConfiguration(asset);
    currentConfig.setPaused(paused);
    _pool.setConfiguration(asset, currentConfig);
    emit ReservePaused(asset, paused);
}

// Pause the entire pool
function setPoolPause(
    bool paused
) external override onlyEmergencyAdmin {
    address[] memory reserves = _pool.getReservesList();
    for (uint256 i = 0; i < reserves.length; i++) {
        if (reserves[i] != address(0)) {
            setReservePause(reserves[i], paused);
        }
    }
}
```

### Other Configuration Functions

| Function | Who Can Call | What It Does |
|---|---|---|
| `setBorrowableInIsolation()` | POOL_ADMIN | Allow/disallow borrowing in isolation mode |
| `setReserveBorrowing()` | RISK_ADMIN, POOL_ADMIN | Enable/disable borrowing for an asset |
| `setBorrowCap()` | RISK_ADMIN, POOL_ADMIN | Set maximum total borrows |
| `setSupplyCap()` | RISK_ADMIN, POOL_ADMIN | Set maximum total supply |
| `setReserveStableRateBorrowing()` | RISK_ADMIN, POOL_ADMIN | Enable/disable stable rate borrowing |
| `setReserveFlashLoaning()` | RISK_ADMIN, POOL_ADMIN | Enable/disable flash loans for an asset |
| `setAssetEModeCategory()` | RISK_ADMIN, POOL_ADMIN | Assign an asset to an E-Mode category |
| `setDebtCeiling()` | RISK_ADMIN, POOL_ADMIN | Set isolation mode debt ceiling |
| `setLiquidationProtocolFee()` | RISK_ADMIN, POOL_ADMIN | Set the liquidation protocol fee |
| `setSiloedBorrowing()` | RISK_ADMIN, POOL_ADMIN | Enable siloed borrowing |
| `updateAToken()` | POOL_ADMIN | Upgrade the aToken implementation |
| `updateStableDebtToken()` | POOL_ADMIN | Upgrade the stable debt token implementation |
| `updateVariableDebtToken()` | POOL_ADMIN | Upgrade the variable debt token implementation |
| `setReserveInterestRateStrategyAddress()` | RISK_ADMIN, POOL_ADMIN | Change the interest rate model |

### The Pattern

Notice the consistent pattern across all PoolConfigurator functions:

1. Read the current configuration from Pool
2. Validate the new parameter
3. Update the configuration bitmap
4. Write the updated configuration back to Pool
5. Emit an event

This is clean separation of concerns. The PoolConfigurator handles authorization and validation. The Pool stores the data. The configuration bitmap provides gas-efficient storage.

---

## Summary

Aave V3's revenue model is built on three pillars:

- **Reserve factor** on borrow interest --- the steady, predictable revenue stream
- **Flash loan premiums** --- episodic but meaningful during high-activity periods
- **Liquidation protocol fees** --- revenue that scales with market volatility

All revenue flows into the treasury as aTokens, which continue to earn interest. The entire system is configured through the PoolConfigurator, with every parameter packed into a gas-efficient bitmap. Governance has fine-grained control over every aspect of every reserve, and the access control system (covered in Chapter 12) ensures that only authorized roles can make changes.
