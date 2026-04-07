# Chapter 7: Collateral, Liquidations, and the Health Factor

Aave V3 is a lending protocol. Lending protocols survive because borrowers must always post more collateral than they borrow. But asset prices move. If a borrower's collateral loses value --- or their debt grows --- the protocol needs a mechanism to close out the position before it becomes insolvent. That mechanism is **liquidation**.

This chapter covers the risk parameters that define borrowing limits, the health factor that measures account solvency, and the liquidation flow that enforces it all.

---

## 1. Risk Parameters per Asset

Every asset listed on Aave V3 has a set of risk parameters configured by governance. These parameters control how much you can borrow against the asset and what happens when things go wrong.

### Loan-to-Value (LTV)

The LTV is the maximum percentage of collateral value that a user can borrow. If ETH has an LTV of 80%, then for every $1,000 of ETH supplied, you can borrow up to $800.

LTV is used when **opening** a position. It determines the initial borrowing limit.

### Liquidation Threshold

The liquidation threshold is the collateral ratio at which a position becomes liquidatable. It is always higher than the LTV. If ETH has a liquidation threshold of 82.5%, then a position backed by ETH becomes liquidatable when the debt exceeds 82.5% of the collateral value.

The gap between LTV and liquidation threshold creates a **safety buffer**. You can borrow up to 80% of your collateral, but you won't be liquidated until your debt reaches 82.5% of collateral value. This gives borrowers time to react to price movements.

### Liquidation Bonus

The liquidation bonus is the extra collateral a liquidator receives as a reward for performing the liquidation. If the liquidation bonus is 5%, the liquidator gets $105 worth of collateral for every $100 of debt they repay.

This is the economic incentive that keeps the liquidation market competitive. Without it, nobody would bother liquidating underwater positions.

### Liquidation Protocol Fee

A portion of the liquidation bonus is redirected to the Aave treasury. If the liquidation bonus is 5% and the protocol fee is 10% of the bonus, then the liquidator gets 4.5% extra and the treasury gets 0.5%.

### How These Are Stored

All risk parameters are packed into a single `uint256` bitmap in the reserve configuration. This is a gas optimization --- instead of storing each parameter in a separate storage slot, Aave encodes everything into one word using bitwise operations.

```solidity
// From ReserveConfiguration.sol

uint256 internal constant LTV_MASK =                       0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF0000;
uint256 internal constant LIQUIDATION_THRESHOLD_MASK =     0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF0000FFFF;
uint256 internal constant LIQUIDATION_BONUS_MASK =         0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF0000FFFFFFFF;

function getLtv(
    DataTypes.ReserveConfigurationMap memory self
) internal pure returns (uint256) {
    return self.data & ~LTV_MASK;
}

function getLiquidationThreshold(
    DataTypes.ReserveConfigurationMap memory self
) internal pure returns (uint256) {
    return (self.data & ~LIQUIDATION_THRESHOLD_MASK) >> LIQUIDATION_THRESHOLD_START_BIT_POSITION;
}

function getLiquidationBonus(
    DataTypes.ReserveConfigurationMap memory self
) internal pure returns (uint256) {
    return (self.data & ~LIQUIDATION_BONUS_MASK) >> LIQUIDATION_BONUS_START_BIT_POSITION;
}
```

Each parameter occupies a specific bit range within the `uint256`. Reading a value means applying a bitmask and shifting. Writing means clearing the old bits and setting the new ones. This pattern repeats throughout the protocol.

Typical values for major assets:

| Asset | LTV  | Liquidation Threshold | Liquidation Bonus |
|-------|------|-----------------------|-------------------|
| WETH  | 80%  | 82.5%                 | 5%                |
| WBTC  | 70%  | 75%                   | 10%               |
| USDC  | 86.5%| 89%                   | 4.5%              |
| DAI   | 75%  | 80%                   | 5%                |

Note: actual values vary by deployment and governance decisions. These are illustrative.

---

## 2. The Health Factor

The health factor (HF) is the single number that tells you whether an account is solvent. It is defined as:

```
                Σ (collateral_i × price_i × liquidationThreshold_i)
Health Factor = ──────────────────────────────────────────────────────
                              totalDebt (in base currency)
```

Where the sum runs over all assets the user has enabled as collateral.

**When HF >= 1**, the position is healthy. The user cannot be liquidated.

**When HF < 1**, the position is liquidatable. Anyone can call `liquidationCall()` to partially or fully close the position.

### A Numerical Example

Alice supplies **10 ETH** as collateral, where ETH is worth **$2,000**. ETH has a liquidation threshold of **82.5%**.

She borrows **$15,000 USDC**.

Her initial health factor:

```
HF = (10 × $2,000 × 0.825) / $15,000
   = $16,500 / $15,000
   = 1.10
```

Alice is safe with a health factor of 1.10.

Now ETH drops to **$1,800**:

```
HF = (10 × $1,800 × 0.825) / $15,000
   = $14,850 / $15,000
   = 0.99
```

The health factor is now below 1. Alice's position is liquidatable.

Note that Alice borrowed $15,000 against $20,000 of collateral (75% LTV), which was within the 80% LTV limit. But when the price dropped, her collateral-to-debt ratio fell below the 82.5% liquidation threshold. The safety buffer between LTV and liquidation threshold gave her some breathing room, but not enough.

---

## 3. The `GenericLogic.calculateUserAccountData()` Function

This is the function that computes everything needed to evaluate a user's position: total collateral value, total debt value, average LTV, average liquidation threshold, and the health factor.

The logic lives in `GenericLogic.sol` and is called during borrows, withdrawals, and liquidations --- any operation where the protocol needs to verify solvency.

```solidity
function calculateUserAccountData(
    mapping(address => DataTypes.ReserveData) storage reservesData,
    mapping(uint256 => address) storage reservesList,
    mapping(uint8 => DataTypes.EModeCategory) storage eModeCategories,
    DataTypes.CalculateUserAccountDataParams memory params
) internal view returns (
    uint256,  // totalCollateralBase
    uint256,  // totalDebtBase
    uint256,  // avgLtv
    uint256,  // avgLiquidationThreshold
    uint256,  // healthFactor
    bool      // hasZeroLtvCollateral
) {
```

The function iterates through every active reserve, checking whether the user has a balance (collateral or debt) in each one:

```solidity
while (vars.i < params.reservesCount) {
    if (!userConfig.isUsingAsReserveOrBorrowing(vars.i)) {
        unchecked { ++vars.i; }
        continue;
    }

    // Load reserve data
    vars.currentReserveAddress = reservesList[vars.i];
    DataTypes.ReserveData storage currentReserve = reservesData[vars.currentReserveAddress];
    DataTypes.ReserveConfigurationMap memory currentConfig = currentReserve.configuration;

    // Get the asset price from the oracle
    vars.assetPrice = IPriceOracleGetter(params.oracle).getAssetPrice(vars.currentReserveAddress);
    vars.assetUnit = 10 ** currentConfig.getDecimals();
```

For each asset, the function accumulates collateral and debt in the **base currency** (usually USD or ETH, depending on the deployment):

```solidity
    // If the user is using this asset as collateral
    if (userConfig.isUsingAsCollateral(vars.i)) {
        vars.userBalanceInBaseCurrency = _getUserBalanceInBaseCurrency(
            user, currentReserve, vars.assetPrice, vars.assetUnit
        );

        vars.totalCollateralInBaseCurrency += vars.userBalanceInBaseCurrency;

        if (vars.liquidationThreshold != 0) {
            vars.avgLtv += vars.userBalanceInBaseCurrency * vars.ltv;
            vars.avgLiquidationThreshold +=
                vars.userBalanceInBaseCurrency * vars.liquidationThreshold;
        } else {
            vars.hasZeroLtvCollateral = true;
        }
    }

    // If the user has debt in this asset
    if (userConfig.isBorrowing(vars.i)) {
        vars.totalDebtInBaseCurrency += _getUserDebtInBaseCurrency(
            user, currentReserve, vars.assetPrice, vars.assetUnit
        );
    }
```

After the loop, the weighted averages are finalized and the health factor is computed:

```solidity
    // Compute weighted average LTV and liquidation threshold
    vars.avgLtv = vars.totalCollateralInBaseCurrency != 0
        ? vars.avgLtv / vars.totalCollateralInBaseCurrency
        : 0;
    vars.avgLiquidationThreshold = vars.totalCollateralInBaseCurrency != 0
        ? vars.avgLiquidationThreshold / vars.totalCollateralInBaseCurrency
        : 0;

    // Health factor
    vars.healthFactor = (vars.totalDebtInBaseCurrency == 0)
        ? type(uint256).max
        : (vars.totalCollateralInBaseCurrency.percentMul(vars.avgLiquidationThreshold))
            .wadDiv(vars.totalDebtInBaseCurrency);
```

A few things to note:

- If the user has **no debt**, the health factor is set to `type(uint256).max` --- effectively infinity. You cannot liquidate someone who has not borrowed.
- The average LTV and liquidation threshold are **weighted by collateral value**. If you supply $10,000 of ETH (82.5% threshold) and $5,000 of USDC (89% threshold), your average threshold is not a simple average of 82.5% and 89%. It is weighted: `(10000 * 82.5 + 5000 * 89) / 15000 = 84.67%`.
- The function handles E-Mode adjustments, which can override the per-asset risk parameters when assets are in the same category (covered in Chapter 9).

---

## 4. The Liquidation Flow

When a user's health factor drops below 1, anyone can call `Pool.liquidationCall()`:

```solidity
function liquidationCall(
    address collateralAsset,    // which collateral to seize
    address debtAsset,          // which debt to repay
    address user,               // the user being liquidated
    uint256 debtToCover,        // how much debt the liquidator wants to repay
    bool receiveAToken          // receive aTokens or underlying?
) external override;
```

The caller (the liquidator) specifies:
- Which collateral asset to seize from the underwater user
- Which debt asset to repay on behalf of the user
- How much debt to repay
- Whether they want the seized collateral as aTokens or the underlying asset

The actual logic is delegated to `LiquidationLogic.executeLiquidationCall()`. Here is the flow step by step.

### Step 1: Validate the Position

First, the function fetches the user's account data and checks that the position is actually liquidatable:

```solidity
(
    vars.userCollateralInBaseCurrency,
    vars.userDebtInBaseCurrency,
    ,
    ,
    vars.healthFactor,
) = GenericLogic.calculateUserAccountData(
    reservesData,
    reservesList,
    eModeCategories,
    params
);

// Revert if the user is not liquidatable
if (vars.healthFactor >= HEALTH_FACTOR_LIQUIDATION_THRESHOLD) {
    revert Errors.HEALTH_FACTOR_NOT_BELOW_THRESHOLD;
}
```

`HEALTH_FACTOR_LIQUIDATION_THRESHOLD` is `1e18` (1.0 in WAD format).

### Step 2: Determine the Close Factor

```solidity
// If health factor is very low, allow full liquidation
vars.closeFactor = vars.healthFactor > CLOSE_FACTOR_HF_THRESHOLD
    ? DEFAULT_LIQUIDATION_CLOSE_FACTOR   // 50%
    : MAX_LIQUIDATION_CLOSE_FACTOR;       // 100%
```

This is the close factor logic (discussed in detail in Section 5 below).

### Step 3: Calculate Debt to Cover

The liquidator may try to repay more than the close factor allows. The protocol caps it:

```solidity
vars.maxLiquidatableDebt = vars.userDebt.percentMul(vars.closeFactor);

vars.actualDebtToLiquidate = debtToCover > vars.maxLiquidatableDebt
    ? vars.maxLiquidatableDebt
    : debtToCover;
```

### Step 4: Calculate Collateral to Seize

This is where the liquidation bonus comes in:

```solidity
(vars.maxCollateralToLiquidate, vars.debtAmountNeeded) =
    _calculateAvailableCollateralToLiquidate(
        collateralReserve,
        debtReserveCache,
        collateralAsset,
        debtAsset,
        vars.actualDebtToLiquidate,
        vars.userCollateralBalance,
        vars.liquidationBonus,
        IPriceOracleGetter(params.priceOracle)
    );
```

Inside `_calculateAvailableCollateralToLiquidate()`, the core formula is:

```solidity
// How much collateral corresponds to the debt being repaid, plus the bonus
vars.baseCollateral = (debtToCover * debtAssetPrice * collateralAssetUnit)
    / (collateralPrice * debtAssetUnit);

vars.maxCollateralToLiquidate = vars.baseCollateral.percentMul(liquidationBonus);
```

The liquidation bonus is stored as `10000 + bonus_bps`. For a 5% bonus, the stored value is `10500`. So `percentMul(10500)` multiplies by 1.05 --- the liquidator gets 5% more collateral than the debt is worth.

If the user does not have enough collateral to cover the full amount (including bonus), the calculation is reversed: the available collateral determines how much debt can actually be repaid.

### Step 5: Execute the Liquidation

With the amounts determined, the protocol executes several state changes:

```solidity
// Burn the liquidated user's debt tokens
_burnDebtTokens(params, vars);

// Handle collateral: either transfer aTokens or withdraw underlying
if (params.receiveAToken) {
    // Transfer aTokens from the liquidated user to the liquidator
    _liquidateATokens(...);
} else {
    // Burn aTokens and send underlying to the liquidator
    _burnCollateralATokens(...);
}

// Deduct the liquidation protocol fee (if any)
if (vars.liquidationProtocolFeeAmount != 0) {
    // Mint aTokens to the treasury for the fee amount
    ...
}

// Update interest rates for both the collateral and debt reserves
```

The liquidated user ends up with less collateral but also less debt. The liquidator ends up with the seized collateral (worth more than the debt they repaid, thanks to the bonus). The protocol may take a small fee.

---

## 5. The Close Factor

The close factor determines what fraction of a borrower's debt can be liquidated in a single call.

In Aave V3, the default close factor is **50%**. This means a liquidator can repay at most half of the borrower's total debt in a single `liquidationCall()`.

The 50% limit exists for a reason: it gives the borrower a chance to recover. After a partial liquidation, the borrower's health factor typically improves (because the collateral seized is proportional, but the debt reduction improves the ratio). The borrower can then add collateral or repay debt to avoid further liquidation.

However, when the health factor drops very low, partial liquidation might not be enough to protect the protocol. In Aave V3, when the health factor falls below the **`CLOSE_FACTOR_HF_THRESHOLD`** (approximately 0.95), the close factor jumps to **100%**.

```solidity
uint256 constant CLOSE_FACTOR_HF_THRESHOLD = 0.95e18;
uint256 constant DEFAULT_LIQUIDATION_CLOSE_FACTOR = 0.5e4;  // 50%
uint256 constant MAX_LIQUIDATION_CLOSE_FACTOR = 1e4;         // 100%
```

This means:
- **HF between 0.95 and 1.0**: liquidator can cover up to 50% of the debt
- **HF below 0.95**: liquidator can cover up to 100% of the debt

The 100% close factor is a safeguard against bad debt. If a position is deeply underwater, a 50% liquidation might not bring the health factor back above 1, and the remaining position could become insolvent. Allowing full liquidation ensures the protocol can close out dangerous positions entirely.

---

## 6. Liquidation Bonus and Protocol Fee

### The Liquidation Bonus

The liquidation bonus is the economic engine of the liquidation market. It creates a direct financial incentive for liquidators to monitor positions and act quickly.

The bonus is expressed in basis points relative to the base. A liquidation bonus of `10500` means the liquidator receives 105% of the debt value in collateral --- a 5% profit margin.

Example with a 5% bonus:
- Liquidator repays $10,000 of USDC debt
- Liquidator receives $10,500 worth of ETH collateral
- Profit: $500

This $500 is not free money from the protocol. It comes directly from the liquidated user's collateral. The user loses more collateral than the debt that was repaid.

### The Liquidation Protocol Fee

Aave V3 introduced a liquidation protocol fee --- a portion of the liquidation bonus that goes to the Aave treasury instead of the liquidator.

```solidity
function getLiquidationProtocolFee(
    DataTypes.ReserveConfigurationMap memory self
) internal pure returns (uint256) {
    return (self.data & ~LIQUIDATION_PROTOCOL_FEE_MASK) >>
        LIQUIDATION_PROTOCOL_FEE_START_BIT_POSITION;
}
```

The fee is computed as a percentage of the total bonus. If the liquidation bonus is 5% and the protocol fee is 10% of the bonus:

```
Total collateral seized:       $10,500  (debt + 5% bonus)
Protocol fee (10% of bonus):   $50      (10% of $500)
Collateral to liquidator:      $10,450
Collateral from user:          $10,500
```

This fee is implemented by minting additional aTokens to the treasury address during liquidation:

```solidity
if (vars.liquidationProtocolFeeAmount != 0) {
    uint256 liquidationProtocolFeeAmount = vars.liquidationProtocolFeeAmount;
    // The fee is minted as aTokens to the treasury
    vars.collateralAToken.mint(
        treasuryAddress,
        treasuryAddress,
        liquidationProtocolFeeAmount,
        collateralReserveCache.nextLiquidityIndex
    );
}
```

The treasury accumulates aTokens over time from liquidation fees (along with other revenue sources covered in Chapter 11).

---

## 7. Oracle Integration

The entire liquidation system depends on accurate price data. If prices are wrong, healthy positions could be liquidated or insolvent positions could go unchecked. Aave V3 uses **Chainlink price feeds** as its primary oracle source.

### AaveOracle.sol

The `AaveOracle` contract acts as a wrapper around individual Chainlink aggregators:

```solidity
contract AaveOracle is IAaveOracle {
    mapping(address => AggregatorInterface) private assetsSources;
    IPriceOracleGetter private _fallbackOracle;
    address public immutable BASE_CURRENCY;
    uint256 public immutable BASE_CURRENCY_UNIT;

    function getAssetPrice(address asset) public view override returns (uint256) {
        AggregatorInterface source = assetsSources[asset];

        if (asset == BASE_CURRENCY) {
            return BASE_CURRENCY_UNIT;
        }

        if (address(source) == address(0)) {
            return _fallbackOracle.getAssetPrice(asset);
        }

        int256 price = source.latestAnswer();

        if (price > 0) {
            return uint256(price);
        } else {
            return _fallbackOracle.getAssetPrice(asset);
        }
    }
}
```

A few important details:

1. **Base currency optimization**: If the requested asset is the base currency itself (e.g., USD on USD-denominated deployments), the price is just `BASE_CURRENCY_UNIT` (e.g., `1e8`). No oracle call needed.

2. **Fallback mechanism**: If the Chainlink feed returns zero, a negative value, or if no source is configured, the oracle falls back to `_fallbackOracle`. This provides a safety net against feed failures.

3. **Price format**: Chainlink feeds typically return prices with 8 decimal places. The `BASE_CURRENCY_UNIT` matches this precision. All price calculations in `GenericLogic.calculateUserAccountData()` account for the decimal differences between asset prices and asset units.

### How Prices Feed into Liquidation

The flow is:

1. `Pool.liquidationCall()` is called
2. `LiquidationLogic.executeLiquidationCall()` delegates to `GenericLogic.calculateUserAccountData()`
3. `calculateUserAccountData()` calls `AaveOracle.getAssetPrice()` for each active reserve
4. Chainlink returns the latest price
5. Collateral and debt values are computed in base currency
6. Health factor is derived from these values
7. If HF < 1, the liquidation proceeds

The entire chain is synchronous and on-chain. There are no off-chain components in the price validation path --- everything happens within a single transaction.

---

## 8. Complete Liquidation Example

Let's walk through a full liquidation scenario with concrete numbers.

### Initial Position

Bob supplies **5 ETH** as collateral and borrows **6,000 USDC**.

At the time of borrowing:
- ETH price: **$2,000**
- ETH LTV: **80%**
- ETH liquidation threshold: **82.5%**
- ETH liquidation bonus: **5%** (stored as `10500`)
- Liquidation protocol fee: **10%** of the bonus

Bob's position:
- Collateral value: 5 ETH * $2,000 = **$10,000**
- Debt: **$6,000**
- Health factor: ($10,000 * 0.825) / $6,000 = **$8,250 / $6,000 = 1.375**
- Max borrowing power: $10,000 * 0.80 = $8,000 (he only used $6,000)

Bob is well within safe territory.

### Price Drop

ETH drops to **$1,450**.

Bob's updated position:
- Collateral value: 5 ETH * $1,450 = **$7,250**
- Debt: **$6,000** (plus some accrued interest, let's say **$6,050** total)
- Health factor: ($7,250 * 0.825) / $6,050 = **$5,981.25 / $6,050 = 0.9886**

Bob's health factor is below 1. His position is liquidatable.

Since 0.9886 > 0.95, the close factor is **50%**. A liquidator can repay up to half of Bob's debt.

### Liquidation

Carol is a liquidator bot monitoring the mempool. She sees Bob's position is underwater and calls `liquidationCall()`.

Carol decides to repay **$3,025 of USDC** (50% of Bob's debt).

**Collateral to seize:**

```
baseCollateral = ($3,025 * 1) / $1,450 = 2.0862 ETH
collateralWithBonus = 2.0862 * 1.05 = 2.1905 ETH
```

**Protocol fee:**

```
bonusCollateral = 2.1905 - 2.0862 = 0.1043 ETH
protocolFee = 0.1043 * 0.10 = 0.01043 ETH
```

**What Carol actually receives:**

```
collateralToLiquidator = 2.1905 - 0.01043 = 2.1801 ETH
```

### Final State

**Bob (liquidated user):**
- Collateral: 5 - 2.1905 = **2.8095 ETH** (worth $4,073.78)
- Debt: $6,050 - $3,025 = **$3,025**
- New health factor: ($4,073.78 * 0.825) / $3,025 = **$3,360.87 / $3,025 = 1.111**

Bob's position is healthy again. He lost 2.19 ETH of collateral but had half his debt cleared.

**Carol (liquidator):**
- Paid: $3,025 in USDC
- Received: 2.1801 ETH (worth $3,161.15)
- Profit: **$136.15**

**Aave treasury:**
- Received: 0.01043 ETH (worth $15.12) as aTokens

**The system worked:** Bob's risky position was brought back to solvency. Carol earned a profit for performing a useful service. The protocol collected a small fee. No bad debt was created.

---

## Key Takeaways

1. **Risk parameters (LTV, liquidation threshold, liquidation bonus) are per-asset** and stored in a packed bitmap for gas efficiency.

2. **The health factor is a single number** that determines account solvency. It is a weighted ratio of liquidation-threshold-adjusted collateral to total debt.

3. **Liquidation is permissionless** --- anyone can call `liquidationCall()` when HF < 1. This creates a competitive market of liquidators.

4. **The close factor** limits how much can be liquidated at once (50%), but allows full liquidation when HF < 0.95 to prevent bad debt.

5. **Liquidation bonuses** incentivize liquidators. A portion goes to the protocol treasury.

6. **Chainlink oracles** provide the price data that drives the entire system. The AaveOracle wraps these feeds with fallback logic.

7. **The safety buffer** between LTV and liquidation threshold gives borrowers room to react, but it is not unlimited. Users should monitor their health factor and maintain a comfortable margin.
