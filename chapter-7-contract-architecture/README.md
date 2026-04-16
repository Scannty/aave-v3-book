# Chapter 7: Contract Architecture

By now you understand how Aave works economically: interest rates balance supply and demand, indexes track interest accrual, aTokens and debt tokens represent positions, and the core operations tie it all together. This chapter looks under the hood at how the smart contracts are organized to make all of that work on-chain.

This is the most Solidity-heavy chapter in the book. If you are here for the economics, you can skip it. If you want to understand how to read the codebase, integrate with it, or audit it - this is where that knowledge lives.

<video src="animations/final/architecture.webm" controls autoplay loop muted playsinline style="width:100%;max-width:800px;border-radius:8px;margin:20px 0"></video>

---

## The Pool: A Thin Router

`Pool.sol` is the contract users interact with. It exposes `supply()`, `withdraw()`, `borrow()`, `repay()`, `liquidationCall()`, `flashLoan()`, and more. But the Pool itself contains almost no logic. It delegates virtually everything to library contracts.

Think of the Pool as a receptionist. It receives your request, identifies what needs to happen, and routes you to the appropriate specialist. Here is what `supply()` actually looks like:

```solidity
function supply(
    address asset,
    uint256 amount,
    address onBehalfOf,
    uint16 referralCode
) public virtual override {
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

The entire function body is a single call to `SupplyLogic`. The Pool passes its own storage references (`_reserves`, `_reservesList`, `_usersConfig`) to the library, which operates directly on the Pool's state. From the EVM's perspective, the library code runs in the Pool's context - there is no external call or context switch.

Why this design? Solidity imposes a **24KB size limit** on deployed contracts (EIP-170). A single contract containing all of Aave's logic would far exceed this. By extracting logic into libraries, the Pool stays small while the total system can be arbitrarily complex.

The Pool is deployed behind an **upgradeable proxy**, so governance can update the implementation without changing the address or migrating state.

---

## The Libraries: Where the Logic Lives

Each core operation has its own library:

| Library | What It Handles |
|---------|----------------|
| `SupplyLogic` | Deposits and withdrawals |
| `BorrowLogic` | Borrowing and repaying |
| `LiquidationLogic` | Liquidating undercollateralized positions |
| `FlashLoanLogic` | Flash loans (both simple and multi-asset) |
| `ReserveLogic` | Interest accrual and index updates |
| `ValidationLogic` | Checking that operations are safe (enough collateral, reserve is active, etc.) |
| `GenericLogic` | Computing user account data (health factor, total collateral, total debt) |
| `EModeLogic` | Efficiency Mode configuration |
| `BridgeLogic` | Cross-chain Portal functionality |
| `IsolationModeLogic` | Isolation mode debt ceiling tracking |
| `PoolLogic` | Reserve initialization |

Every user-facing function follows the same pattern: `Pool.borrow()` → `BorrowLogic.executeBorrow()`, `Pool.liquidationCall()` → `LiquidationLogic.executeLiquidationCall()`, and so on.

Within each library, the flow is also consistent:

1. **Cache** reserve data into memory (cheaper than repeated storage reads)
2. **Update state** (accrue interest by updating indexes)
3. **Validate** (check the operation is safe)
4. **Execute** (move tokens, mint/burn, update accounting)
5. **Update interest rates** (recalculate based on new utilization)

---

## The ReserveData Struct: Per-Asset State

Every listed asset has a `ReserveData` entry stored in the Pool. This struct holds everything the protocol needs to know about an asset:

```solidity
struct ReserveData {
    ReserveConfigurationMap configuration;  // Packed risk parameters (bitmap)
    uint128 liquidityIndex;                 // Cumulative supply-side multiplier
    uint128 currentLiquidityRate;           // Current annualized supply rate
    uint128 variableBorrowIndex;            // Cumulative borrow-side multiplier
    uint128 currentVariableBorrowRate;      // Current annualized borrow rate
    uint128 currentStableBorrowRate;        // (deprecated)
    uint40  lastUpdateTimestamp;            // When indexes were last refreshed
    uint16  id;                             // Sequential reserve ID (0, 1, 2...)
    address aTokenAddress;                  // The aToken for this reserve
    address stableDebtTokenAddress;         // (deprecated)
    address variableDebtTokenAddress;       // The variable debt token
    address interestRateStrategyAddress;    // The rate model contract
    uint128 accruedToTreasury;              // Revenue earned but not yet claimed
    uint128 unbacked;                       // Outstanding Portal-minted aTokens
    uint128 isolationModeTotalDebt;         // Total debt against this in isolation
}
```

The types are deliberately sized - `uint128` instead of `uint256`, `uint40` for timestamps, `uint16` for IDs - so that multiple fields pack into a single 256-bit storage slot. This reduces the number of `SLOAD` operations when reading reserve data, which directly reduces gas costs.

The `liquidityIndex` and `variableBorrowIndex` are the cumulative multipliers from Chapter 3. The `currentLiquidityRate` and `currentVariableBorrowRate` are the outputs of the interest rate model from Chapter 2. Everything connects.

---

## The Configuration Bitmap: Packing Parameters Into One Slot

Each reserve has many risk parameters: LTV, liquidation threshold, liquidation bonus, decimals, whether borrowing is enabled, whether the reserve is paused, the reserve factor, caps, and more. Reading each from its own storage slot would be expensive.

Aave packs all of these into a **single `uint256`**:

| Bit Range | Parameter | Example |
|-----------|-----------|---------|
| 0-15 | LTV (basis points) | 8000 = 80% |
| 16-31 | Liquidation threshold | 8250 = 82.5% |
| 32-47 | Liquidation bonus | 10500 = 105% (5% bonus) |
| 48-55 | Decimals | 6 for USDC, 18 for ETH |
| 56 | Active flag | 1 = yes |
| 57 | Frozen flag | 0 = no |
| 58 | Borrowing enabled | 1 = yes |
| 59 | Stable rate enabled | 0 (deprecated) |
| 60 | Paused flag | 0 = no |
| 61 | Borrowable in isolation | 1 for stablecoins |
| 62 | Siloed borrowing | 0 = no |
| 63 | Flash loans enabled | 1 = yes |
| 64-79 | Reserve factor | 1000 = 10% |
| 80-115 | Borrow cap (whole tokens) | 50,000,000 |
| 116-151 | Supply cap (whole tokens) | 100,000,000 |
| 152-167 | Liquidation protocol fee | 1000 = 10% |
| 168-175 | E-Mode category | 1 = stablecoins |

The `ReserveConfiguration` library provides getters and setters using bitmasks:

```solidity
function getLtv(
    DataTypes.ReserveConfigurationMap memory self
) internal pure returns (uint256) {
    return self.data & ~LTV_MASK;  // Extract lowest 16 bits
}

function getLiquidationThreshold(
    DataTypes.ReserveConfigurationMap memory self
) internal pure returns (uint256) {
    return (self.data & ~LIQUIDATION_THRESHOLD_MASK) >> 16;
}
```

One storage read gives you every risk parameter for a reserve. This matters because these parameters are checked on every supply, borrow, repay, withdraw, and liquidation.

---

## The User Configuration Bitmap

Each user also has a single `uint256` where two bits per reserve encode their position:

- Bit `2n`: is the user **borrowing** reserve `n`?
- Bit `2n+1`: is the user **using reserve `n` as collateral**?

This means the protocol can scan a user's entire position by reading one 256-bit integer. Since Aave V3 supports up to 128 reserves per Pool (256 bits / 2 bits per reserve), everything fits in one slot.

When computing the health factor, the protocol loops through these bits to find which reserves the user is involved with, then fetches only those reserves' data. This is much cheaper than iterating over all reserves.

---

## The PoolConfigurator

`PoolConfigurator.sol` is the governance-facing contract. It allows authorized roles to:

- List new assets (`initReserves()`)
- Set risk parameters: LTV, liquidation threshold, bonus (`configureReserveAsCollateral()`)
- Set the reserve factor (`setReserveFactor()`)
- Set supply and borrow caps (`setSupplyCap()`, `setBorrowCap()`)
- Pause or freeze reserves
- Configure E-Mode categories
- Update interest rate strategies

Every function checks the caller's role through `ACLManager` before executing. Ordinary users never interact with this contract.

---

## The PoolAddressesProvider

`PoolAddressesProvider.sol` is the protocol's registry. It stores the addresses of all core components:

| Key | Contract |
|-----|----------|
| `POOL` | Pool (proxy) |
| `POOL_CONFIGURATOR` | PoolConfigurator (proxy) |
| `PRICE_ORACLE` | AaveOracle |
| `ACL_MANAGER` | ACLManager |
| `ACL_ADMIN` | The admin address |

Other contracts look up addresses from this registry rather than hardcoding them. This enables upgradeability: to upgrade the Pool, governance deploys a new implementation and calls `setPoolImpl()` on the AddressesProvider, which updates the proxy to point to the new code. Same address, same storage, new logic.

---

## The Oracle

`AaveOracle.sol` wraps Chainlink price feeds into a uniform interface. For each asset, it maps the asset's address to a Chainlink aggregator. The key function:

```solidity
function getAssetPrice(address asset) public view returns (uint256) {
    // Returns price in base currency (USD, 8 decimals)
}
```

The oracle is called every time the protocol needs to value a position: on borrow (is there enough collateral?), on withdraw (would this break the health factor?), and on liquidation (is this position actually underwater?).

---

## The ACL Manager

`ACLManager.sol` implements role-based access control using OpenZeppelin's AccessControl pattern. Key roles:

| Role | What It Can Do |
|------|---------------|
| `POOL_ADMIN` | Full configuration and upgrades |
| `EMERGENCY_ADMIN` | Pause/unpause the protocol |
| `RISK_ADMIN` | Update risk parameters |
| `FLASH_BORROWER` | Zero-fee flash loans |
| `BRIDGE` | Portal mint/burn operations |
| `ASSET_LISTING_ADMIN` | List new assets |

Every privileged function checks the caller's role:

```solidity
modifier onlyPoolAdmin() {
    _onlyPoolAdmin();
    _;
}

function _onlyPoolAdmin() internal view {
    IACLManager aclManager = IACLManager(
        _addressesProvider.getACLManager()
    );
    require(
        aclManager.isPoolAdmin(msg.sender),
        Errors.CALLER_NOT_POOL_ADMIN
    );
}
```

This is covered in detail in the Governance chapter (Chapter 14).

---

## Token Contracts Per Asset

For every listed asset, three token contracts are deployed:

**aTokens** (e.g., aUSDC) represent supply positions. `balanceOf()` returns the current balance including accrued interest by multiplying the stored scaled balance by the liquidity index. This is the rebasing mechanism from Chapter 4.

**Variable Debt Tokens** (e.g., variableDebtUSDC) represent borrow obligations. Same index-based mechanism, but using the variable borrow index. Covered in Chapter 5.

**Stable Debt Tokens** exist in the codebase but are deprecated in newer deployments.

One critical difference: aTokens are **transferable** (you can send your supply position to someone else), but debt tokens are **non-transferable**. The `transfer()` function on debt tokens reverts. You cannot send your debt to another address.

---

## Summary

The mental model for Aave V3's architecture:

- **Pool** - the thin router that users call, delegating to libraries
- **Libraries** - where all the logic lives (SupplyLogic, BorrowLogic, etc.)
- **ReserveData** - per-asset state: indexes, rates, timestamps, token addresses
- **Configuration bitmap** - all risk parameters packed into one `uint256` for gas efficiency
- **User bitmap** - each user's borrow/collateral flags in one `uint256`
- **PoolConfigurator** - the admin panel, gated by ACLManager roles
- **PoolAddressesProvider** - the registry that makes everything discoverable and upgradeable
- **AaveOracle** - Chainlink price feeds wrapped in a uniform interface

Everything you learned in Chapters 2-6 about interest rates, indexes, tokens, and flows is implemented through this structure.
