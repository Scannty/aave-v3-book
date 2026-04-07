# Chapter 1: The Architecture of Aave V3

## What is Aave V3

Aave V3 is a decentralized, non-custodial lending protocol deployed across multiple EVM-compatible chains. Users supply assets into liquidity pools to earn interest, and borrowers post collateral to take out loans. The protocol is entirely permissionless — anyone can supply or borrow without needing approval from a centralized entity.

If you have used Compound V3 (Comet), the mental model is similar but the architecture is fundamentally different. Compound V3 deploys a **separate market contract for each borrowable asset**. Each Comet instance (e.g., USDC Comet, ETH Comet) is an independent market with its own collateral set. If you want to borrow USDC against your ETH, you interact with the USDC Comet. If you want to borrow ETH against your USDC, you need a different Comet deployment.

Aave V3 takes the opposite approach: a **single `Pool` contract manages all assets**. One Pool handles USDC, ETH, WBTC, DAI, and every other listed asset simultaneously. When you supply USDC and borrow ETH, both operations go through the same Pool contract. This means all listed assets share a unified collateral and borrowing environment.

This design choice has deep implications for how the protocol is structured. A single Pool must track the state of dozens of assets, each with its own interest rate model, oracle price, risk parameters, and token contracts. Aave manages this complexity through an extensive use of libraries, bitpacked configuration, and a carefully layered contract architecture.

## Using Aave from the UI

Before diving into the contracts, it helps to understand what actually happens when a user interacts with Aave through the [Aave App](https://app.aave.com/).

**Supplying an asset.** A user navigates to the Supply section, selects an asset (say USDC), and enters an amount. Behind the scenes, the UI calls `Pool.supply()`. The user's USDC is transferred into the Pool, and they receive **aUSDC** in return — an interest-bearing token whose balance increases over time.

**Enabling as collateral.** By default, most supplied assets are automatically enabled as collateral. The user can toggle this on or off through the dashboard. Under the hood, this calls `Pool.setUserUseReserveAsCollateral()`, which flips a bit in the user's configuration bitmap.

**Borrowing.** The user selects an asset to borrow (say ETH) and an amount. The UI calls `Pool.borrow()`. The protocol checks that the user has enough collateral (based on oracle prices and risk parameters), mints **variableDebtETH** tokens to the borrower, and transfers the borrowed ETH to them.

**Repaying.** To close a loan, the user calls `Pool.repay()` with the borrowed asset. The debt tokens are burned and the asset is returned to the Pool.

**Withdrawing.** The user calls `Pool.withdraw()` to redeem their aTokens for the underlying asset. The protocol checks that the withdrawal would not make the user's position undercollateralized.

Every one of these actions flows through a single contract: `Pool.sol`.

## Contract Architecture from 10,000 Feet

Aave V3's contract architecture is layered. At the highest level, there are five categories of contracts:

### Pool.sol — The Entry Point

`Pool.sol` is the main contract that users interact with. It exposes the public functions: `supply()`, `withdraw()`, `borrow()`, `repay()`, `liquidationCall()`, `flashLoan()`, `flashLoanSimple()`, and more.

Despite being the entry point for nearly all user interactions, `Pool.sol` itself contains very little logic. It delegates almost everything to library contracts (more on this below). Think of Pool as a **thin router** — it receives the call, passes the arguments to the appropriate library, and returns the result.

Pool is deployed behind a proxy (using OpenZeppelin's upgradeability pattern), with its address stored in the `PoolAddressesProvider`.

### PoolConfigurator.sol — The Admin Control Panel

`PoolConfigurator.sol` is the admin-facing contract. It allows governance or authorized roles to:

- List new reserves (assets) on the protocol
- Set risk parameters (LTV, liquidation threshold, liquidation bonus)
- Set reserve factors (protocol's cut of interest)
- Pause/unpause reserves
- Configure E-Mode categories
- Update interest rate strategies

Ordinary users never interact with this contract. It is restricted by the `ACLManager`.

### PoolAddressesProvider.sol — The Registry

`PoolAddressesProvider.sol` is a simple registry contract that stores the addresses of all core protocol components: the Pool, the PoolConfigurator, the Oracle, the ACLManager, and others.

This pattern allows the protocol to be upgraded by updating the address in the registry rather than migrating state. Other contracts look up the Pool address from the provider rather than hardcoding it.

```solidity
// Simplified view of PoolAddressesProvider
contract PoolAddressesProvider {
    mapping(bytes32 => address) private _addresses;

    function getPool() external view returns (address) {
        return _addresses[POOL];
    }

    function getPriceOracle() external view returns (address) {
        return _addresses[PRICE_ORACLE];
    }

    // ... other getters
}
```

### AaveOracle.sol — Price Feeds

`AaveOracle.sol` wraps Chainlink price feeds (and potentially other oracle sources) into a uniform interface. For each asset, it stores a mapping from asset address to Chainlink aggregator address.

The key function is `getAssetPrice(address asset)`, which returns the price in the base currency (typically USD, denominated in 8 decimal places matching Chainlink's convention).

The oracle is critical for two operations: determining how much a user can borrow (based on their collateral value) and determining when a position is eligible for liquidation.

### ACLManager.sol — Access Control

`ACLManager.sol` implements role-based access control using OpenZeppelin's `AccessControl`. It defines roles such as:

- **POOL_ADMIN** — Can configure reserves via PoolConfigurator
- **EMERGENCY_ADMIN** — Can pause the protocol
- **RISK_ADMIN** — Can update risk parameters
- **FLASH_BORROWER** — Exempt from flash loan fees
- **BRIDGE** — Can mint/burn aTokens for cross-chain bridging (Portal)
- **ASSET_LISTING_ADMIN** — Can list new assets

### Token Contracts — aTokens and Debt Tokens

For every asset listed on Aave, three token contracts are deployed:

1. **aToken** (e.g., aUSDC) — Represents the user's supply position. Its `balanceOf()` returns an ever-increasing amount reflecting accrued interest. Under the hood, it stores a **scaled balance** and multiplies by the liquidity index on read.

2. **VariableDebtToken** (e.g., variableDebtUSDC) — Represents variable-rate debt. Its `balanceOf()` returns the current debt including accrued interest. Like aTokens, it uses scaled balances internally.

3. **StableDebtToken** (e.g., stableDebtUSDC) — Represents stable-rate debt. This is largely deprecated in newer deployments but still exists in the codebase.

These tokens are not standard ERC-20s. aTokens are transferable (transferring your aTokens transfers your supply position), but debt tokens are **non-transferable** — you cannot send your debt to someone else.

### The Library Contracts

The actual logic for each operation lives in library contracts:

| Library | Responsibility |
|---------|---------------|
| `SupplyLogic` | Handles `supply()` and `withdraw()` |
| `BorrowLogic` | Handles `borrow()` and `repay()` |
| `LiquidationLogic` | Handles `liquidationCall()` |
| `FlashLoanLogic` | Handles `flashLoan()` and `flashLoanSimple()` |
| `EModeLogic` | Handles E-Mode configuration and validation |
| `BridgeLogic` | Handles Portal (cross-chain bridging) |
| `PoolLogic` | Handles reserve initialization and dropping |
| `ReserveLogic` | Manages reserve state updates (index accrual) |
| `ValidationLogic` | Validates all operations (sufficient collateral, active reserve, etc.) |
| `GenericLogic` | Calculates user account data (health factor, total collateral/debt) |
| `IsolationModeLogic` | Handles isolation mode debt ceiling tracking |

Here is a simplified view of the contract dependency graph:

```
User
  │
  ▼
Pool.sol (proxy)
  │
  ├──▶ SupplyLogic
  ├──▶ BorrowLogic
  ├──▶ LiquidationLogic
  ├──▶ FlashLoanLogic
  ├──▶ EModeLogic
  ├──▶ BridgeLogic
  │       │
  │       ▼
  │    ValidationLogic ◀── GenericLogic
  │       │
  │       ▼
  │    ReserveLogic
  │
  ├──▶ aToken (per asset)
  ├──▶ VariableDebtToken (per asset)
  ├──▶ StableDebtToken (per asset)
  │
  ├──▶ AaveOracle
  └──▶ ACLManager

PoolConfigurator.sol (proxy)
  │
  ├──▶ ConfiguratorLogic
  ├──▶ Pool
  └──▶ ACLManager

PoolAddressesProvider.sol
  │
  ├──▶ Pool address
  ├──▶ PoolConfigurator address
  ├──▶ AaveOracle address
  └──▶ ACLManager address
```

## The Reserve Data Structure

The heart of Aave's state management is the `ReserveData` struct, defined in `DataTypes.sol`. Each listed asset has one `ReserveData` entry stored in the Pool. This struct holds everything the protocol needs to know about an asset.

```solidity
struct ReserveData {
    // Configuration — a bitmap packing LTV, liquidation threshold, etc.
    ReserveConfigurationMap configuration;

    // The liquidity index — tracks cumulative interest earned by suppliers
    uint128 liquidityIndex;

    // The current supply rate (annual, in ray)
    uint128 currentLiquidityRate;

    // The variable borrow index — tracks cumulative interest owed by borrowers
    uint128 variableBorrowIndex;

    // The current variable borrow rate (annual, in ray)
    uint128 currentVariableBorrowRate;

    // The current stable borrow rate (annual, in ray)
    uint128 currentStableBorrowRate;

    // Timestamp of the last update to the indexes
    uint40 lastUpdateTimestamp;

    // The id of this reserve (sequential, starting from 0)
    uint16 id;

    // Address of the aToken for this reserve
    address aTokenAddress;

    // Address of the stable debt token
    address stableDebtTokenAddress;

    // Address of the variable debt token
    address variableDebtTokenAddress;

    // Address of the interest rate strategy contract
    address interestRateStrategyAddress;

    // Current treasury accrued (in scaled aToken units)
    uint128 accruedToTreasury;

    // Outstanding unbacked aTokens (Portal feature)
    uint128 unbacked;

    // Isolation mode total debt ceiling consumed
    uint128 isolationModeTotalDebt;
}
```

Let us walk through the most important fields:

**`liquidityIndex`** — This is a cumulative multiplier (in ray, i.e., 27 decimal places) that tracks how much interest has accrued for suppliers since the reserve was initialized. It starts at 1e27 (1.0 in ray) and only increases. If the liquidity index is 1.05e27, then every unit of "scaled balance" stored for a supplier is worth 1.05 units of the underlying asset. Chapter 3 covers this in detail.

**`variableBorrowIndex`** — The same concept but for variable-rate borrowers. Tracks cumulative interest accrued on variable debt.

**`currentLiquidityRate`** and **`currentVariableBorrowRate`** — The current annualized rates, stored in ray. These are recalculated every time the reserve's state changes (on any supply, borrow, repay, or withdraw).

**`lastUpdateTimestamp`** — The block timestamp of the last state update. Used to calculate how much time has passed for interest accrual.

**`configuration`** — A packed `uint256` bitmap storing risk parameters. We cover this next.

The Pool stores a mapping from asset address to `ReserveData`:

```solidity
// Inside Pool storage
mapping(address => DataTypes.ReserveData) internal _reserves;
```

It also maintains a list of all reserve addresses and a counter:

```solidity
mapping(uint256 => address) internal _reservesList;
uint16 internal _reservesCount;
```

The sequential `id` field in each `ReserveData` is used to index into user-level bitmaps (more on that in the configuration section).

## How Aave V3 Uses Libraries

Solidity has a 24KB contract size limit (EIP-170). A naive implementation of Pool with all the supply, borrow, repay, withdraw, liquidation, and flash loan logic would far exceed this limit. Aave V3 solves this by extracting logic into **library contracts**.

In Solidity, when a library function takes a `storage` reference as its first parameter, the compiler generates a `DELEGATECALL`-like internal call that operates directly on the calling contract's storage. This is not an external call — it is inlined or uses `JUMP` instructions, so there is no separate deployment or context switch.

Here is how `Pool.supply()` delegates to `SupplyLogic`:

```solidity
// In Pool.sol
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

Notice that `_reserves`, `_reservesList`, and `_usersConfig` are passed as storage references. The `SupplyLogic` library operates on Pool's storage directly. From the EVM's perspective, all the code executes in the context of the Pool contract.

This pattern is used consistently across the protocol:

- `Pool.supply()` and `Pool.withdraw()` delegate to `SupplyLogic`
- `Pool.borrow()` and `Pool.repay()` delegate to `BorrowLogic`
- `Pool.liquidationCall()` delegates to `LiquidationLogic`
- `Pool.flashLoan()` delegates to `FlashLoanLogic`

The benefit is clear: the Pool contract stays small while the total logic can be arbitrarily large, spread across multiple libraries.

## The Configuration Bitmap

Aave stores each reserve's risk parameters in a single `uint256` value. This is a classic gas optimization technique — reading one storage slot is far cheaper than reading many.

The `ReserveConfiguration` library provides getter and setter functions that mask and shift bits to read and write individual fields. Here is the layout:

```
Bit 0-15:    LTV (Loan-to-Value ratio, in basis points, e.g., 8000 = 80%)
Bit 16-31:   Liquidation threshold (basis points)
Bit 32-47:   Liquidation bonus (basis points, e.g., 10500 = 5% bonus)
Bit 48-55:   Decimals (the asset's ERC-20 decimals)
Bit 56:      Reserve is active
Bit 57:      Reserve is frozen
Bit 58:      Borrowing is enabled
Bit 59:      Stable rate borrowing enabled
Bit 60:      Asset is paused
Bit 61:      Borrowable in isolation mode
Bit 62:      Siloed borrowing
Bit 63:      Flashloaning enabled
Bit 64-79:   Reserve factor (basis points)
Bit 80-115:  Borrow cap (in whole token units)
Bit 116-151: Supply cap (in whole token units)
Bit 152-167: Liquidation protocol fee (basis points)
Bit 168-175: E-Mode category
Bit 176-211: Unbacked mint cap
Bit 212-251: Debt ceiling (in whole units of the debt ceiling decimals)
Bit 252-255: Unused
```

Here is how the LTV is read from the bitmap:

```solidity
uint256 constant LTV_MASK =                   0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF0000;

function getLtv(
    DataTypes.ReserveConfigurationMap memory self
) internal pure returns (uint256) {
    return self.data & ~LTV_MASK;
}
```

The `~LTV_MASK` inverts the mask to isolate the lowest 16 bits. Similar getter functions exist for every field, each using the appropriate mask and bit shift.

There is also a **user configuration bitmap**. Each user has a `uint256` where two bits per reserve indicate: (1) whether the user is borrowing that asset, and (2) whether the user is using it as collateral.

```solidity
// In DataTypes.sol
struct UserConfigurationMap {
    uint256 data;
}
```

For reserve with `id = n`:
- Bit `2 * n` — is the user borrowing this asset?
- Bit `2 * n + 1` — is the user using this asset as collateral?

This allows the protocol to quickly iterate over a user's positions by scanning bits in a single `uint256`. Since Aave V3 supports up to 128 reserves per Pool (256 bits / 2 bits per reserve), this fits in one storage slot.

## Key Differences from Aave V2

Aave V3 introduced several major features and optimizations over V2:

### E-Mode (Efficiency Mode)

E-Mode allows assets that are price-correlated (e.g., USDC, USDT, DAI — all USD stablecoins) to have higher capital efficiency when borrowed against each other. When a user enters an E-Mode category, they get higher LTV and liquidation thresholds for assets within that category.

For example, borrowing USDT against USDC in stablecoin E-Mode might allow 97% LTV instead of the normal 80%. This is safe because the assets are expected to maintain a tight price peg to each other. Chapter 9 covers E-Mode in detail.

### Isolation Mode

Isolation Mode allows newly listed or riskier assets to be used as collateral, but with restrictions: the user can **only borrow stablecoins** (or specific approved assets) against isolated collateral, and there is a **debt ceiling** limiting total borrowing against that asset across all users.

This lets governance list long-tail assets without exposing the protocol to unlimited risk. Chapter 10 covers this in detail.

### Portal

Portal is a cross-chain bridging feature that allows aTokens to be burned on one chain and minted on another. A whitelisted bridge protocol burns aTokens on the source chain, and a corresponding amount of "unbacked" aTokens are minted on the destination chain. The bridge then transfers the underlying assets to back them.

This enables cross-chain liquidity without requiring users to manually bridge assets.

### Storage and Gas Optimizations

Aave V3 significantly improved gas efficiency compared to V2:

- **Tighter struct packing** — `ReserveData` fields are carefully sized (`uint128`, `uint40`, `uint16`) to pack into fewer storage slots
- **Bitmap user configuration** — Instead of iterating over all reserves to check a user's positions, the protocol scans bits in a single `uint256`
- **Supply and borrow caps** — Encoded directly in the reserve configuration bitmap, eliminating extra storage reads
- **Library architecture** — More aggressive use of libraries to keep contract sizes manageable while adding features

### Other Changes

- **Multiple rewards** — V3's incentives system supports multiple reward tokens per aToken/debtToken (not covered in this book)
- **Better risk management** — Supply caps, borrow caps, isolation mode, and siloed borrowing give governance fine-grained risk controls
- **Simplified flash loans** — `flashLoanSimple()` was added as a gas-optimized path for single-asset flash loans
- **Virtual accounting** — Later updates introduced virtual underlying balance tracking to protect against donation attacks

## Summary

Aave V3's architecture is built around a single Pool contract that delegates logic to specialized libraries. Each asset (reserve) has its own configuration bitmap, interest rate indexes, and token contracts (aToken, variable debt token, stable debt token). The PoolAddressesProvider serves as a registry, and access control is managed through role-based ACL.

The key mental model: the **Pool is a thin router**, the **libraries contain the logic**, the **ReserveData struct holds the state**, and the **configuration bitmap packs parameters into a single slot**.

In the next chapter, we examine how Aave V3 determines interest rates — the math behind the variable rate model and how supply and borrow rates are calculated.
