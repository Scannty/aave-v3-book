# Chapter 12: Governance and Admin Controls

Aave V3 is a decentralized protocol, but "decentralized" does not mean "unmanaged." Someone needs to list new assets, adjust risk parameters, pause the protocol during emergencies, and upgrade contracts when bugs are found. In Aave V3, these powers are distributed across a set of well-defined roles, managed through an access control system, and ultimately controlled by AAVE token holders through on-chain governance.

This chapter covers the full governance and admin architecture: how addresses are registered, how roles are assigned, how parameters are updated, how emergencies are handled, and how contracts are upgraded.

---

## 1. PoolAddressesProvider: The Central Registry

Every Aave V3 deployment begins with a single contract: the `PoolAddressesProvider`. This is the protocol's phone book. Every other contract in the system looks up addresses through this registry rather than hardcoding them.

### What It Stores

```solidity
contract PoolAddressesProvider is Ownable, IPoolAddressesProvider {
    // Market identifier
    string private _marketId;

    // Main protocol contracts (stored as proxy addresses)
    mapping(bytes32 => address) private _addresses;

    bytes32 private constant POOL = 'POOL';
    bytes32 private constant POOL_CONFIGURATOR = 'POOL_CONFIGURATOR';
    bytes32 private constant PRICE_ORACLE = 'PRICE_ORACLE';
    bytes32 private constant ACL_MANAGER = 'ACL_MANAGER';
    bytes32 private constant ACL_ADMIN = 'ACL_ADMIN';
    bytes32 private constant POOL_DATA_PROVIDER = 'POOL_DATA_PROVIDER';
    // ... and more
}
```

The key addresses stored are:

| Key | Contract | Purpose |
|---|---|---|
| `POOL` | Pool (proxy) | The main lending pool --- supply, borrow, repay, withdraw, liquidate |
| `POOL_CONFIGURATOR` | PoolConfigurator (proxy) | Admin functions for configuring reserves |
| `PRICE_ORACLE` | AaveOracle | Price feed aggregator for all assets |
| `ACL_MANAGER` | ACLManager | Role-based access control |
| `ACL_ADMIN` | (address) | The admin who can grant/revoke roles on ACLManager |
| `POOL_DATA_PROVIDER` | AaveProtocolDataProvider | Read-only helper for querying protocol state |

### Why a Registry?

The registry pattern provides two critical capabilities:

**1. Upgradeability.** Since Pool and PoolConfigurator are behind proxies, the PoolAddressesProvider can point the proxy to a new implementation without changing any addresses that other contracts reference.

**2. Discoverability.** External integrations (frontends, bots, other protocols) only need to know the PoolAddressesProvider address. From there, they can look up every other contract:

```solidity
IPoolAddressesProvider provider = IPoolAddressesProvider(KNOWN_ADDRESS);
IPool pool = IPool(provider.getPool());
IAaveOracle oracle = IAaveOracle(provider.getPriceOracle());
IACLManager aclManager = IACLManager(provider.getACLManager());
```

### Setting Addresses

The PoolAddressesProvider is owned by a single address (the governance executor). Only the owner can update addresses:

```solidity
function setPoolImpl(address newPoolImpl) external override onlyOwner {
    address oldPoolImpl = _getProxyImplementation(POOL);
    _updateImpl(POOL, newPoolImpl);
    emit PoolUpdated(oldPoolImpl, newPoolImpl);
}

function setPoolConfiguratorImpl(address newPoolConfiguratorImpl) external override onlyOwner {
    address oldPoolConfiguratorImpl = _getProxyImplementation(POOL_CONFIGURATOR);
    _updateImpl(POOL_CONFIGURATOR, newPoolConfiguratorImpl);
    emit PoolConfiguratorUpdated(oldPoolConfiguratorImpl, newPoolConfiguratorImpl);
}

function setPriceOracle(address newPriceOracle) external override onlyOwner {
    address oldPriceOracle = _addresses[PRICE_ORACLE];
    _addresses[PRICE_ORACLE] = newPriceOracle;
    emit PriceOracleUpdated(oldPriceOracle, newPriceOracle);
}

function setACLManager(address newAclManager) external override onlyOwner {
    address oldAclManager = _addresses[ACL_MANAGER];
    _addresses[ACL_MANAGER] = newAclManager;
    emit ACLManagerUpdated(oldAclManager, newAclManager);
}

function setACLAdmin(address newAclAdmin) external override onlyOwner {
    address oldAclAdmin = _addresses[ACL_ADMIN];
    _addresses[ACL_ADMIN] = newAclAdmin;
    emit ACLAdminUpdated(oldAclAdmin, newAclAdmin);
}
```

Notice that `setPoolImpl()` and `setPoolConfiguratorImpl()` call `_updateImpl()`, which updates the proxy's implementation. `setPriceOracle()` and `setACLManager()` simply update the address mapping --- these are not behind proxies.

### PoolAddressesProviderRegistry

There is also a `PoolAddressesProviderRegistry` that tracks all `PoolAddressesProvider` instances across different markets. This allows a single entry point for discovering all Aave V3 markets on a chain.

---

## 2. ACLManager: Role-Based Access Control

The `ACLManager` is the gatekeeper for all administrative actions in Aave V3. It implements role-based access control using OpenZeppelin's `AccessControl` contract. Every privileged function in Pool and PoolConfigurator checks the caller's role through ACLManager before executing.

### The Roles

```solidity
contract ACLManager is AccessControl, IACLManager {
    bytes32 public constant override POOL_ADMIN_ROLE = keccak256('POOL_ADMIN');
    bytes32 public constant override EMERGENCY_ADMIN_ROLE = keccak256('EMERGENCY_ADMIN');
    bytes32 public constant override RISK_ADMIN_ROLE = keccak256('RISK_ADMIN');
    bytes32 public constant override FLASH_BORROWER_ROLE = keccak256('FLASH_BORROWER');
    bytes32 public constant override BRIDGE_ROLE = keccak256('BRIDGE');
    bytes32 public constant override ASSET_LISTING_ADMIN_ROLE = keccak256('ASSET_LISTING_ADMIN');

    // ...
}
```

| Role | Purpose | Typical Holder |
|---|---|---|
| `POOL_ADMIN` | Full admin powers. Can configure reserves, update all parameters, list new assets, upgrade token implementations. | Governance executor (with timelock) |
| `EMERGENCY_ADMIN` | Can pause/unpause the entire pool or individual reserves. Cannot change parameters. | Guardian multisig (for fast response) |
| `RISK_ADMIN` | Can update risk parameters: LTV, liquidation thresholds, reserve factors, caps, interest rate strategies. Cannot list new assets or upgrade implementations. | Risk service provider (e.g., Gauntlet, Chaos Labs) or governance |
| `FLASH_BORROWER` | Whitelisted for zero-premium flash loans. No admin powers. | Approved protocol integrations |
| `BRIDGE` | Can mint unbacked aTokens and back them later. Used for Portal cross-chain operations. | Approved bridge protocols |
| `ASSET_LISTING_ADMIN` | Can list new assets (call `initReserves()`). A subset of POOL_ADMIN powers. | Governance or authorized listing entities |

### How Roles Are Checked

The PoolConfigurator uses modifier-style checks that query the ACLManager:

```solidity
// In PoolConfigurator
modifier onlyPoolAdmin() {
    _onlyPoolAdmin();
    _;
}

function _onlyPoolAdmin() internal view {
    IACLManager aclManager = IACLManager(
        _addressesProvider.getACLManager()
    );
    require(aclManager.isPoolAdmin(msg.sender), Errors.CALLER_NOT_POOL_ADMIN);
}

modifier onlyRiskOrPoolAdmins() {
    _onlyRiskOrPoolAdmins();
    _;
}

function _onlyRiskOrPoolAdmins() internal view {
    IACLManager aclManager = IACLManager(
        _addressesProvider.getACLManager()
    );
    require(
        aclManager.isRiskAdmin(msg.sender) || aclManager.isPoolAdmin(msg.sender),
        Errors.CALLER_NOT_RISK_OR_POOL_ADMIN
    );
}

modifier onlyEmergencyAdmin() {
    _onlyEmergencyAdmin();
    _;
}

function _onlyEmergencyAdmin() internal view {
    IACLManager aclManager = IACLManager(
        _addressesProvider.getACLManager()
    );
    require(
        aclManager.isEmergencyAdmin(msg.sender),
        Errors.CALLER_NOT_EMERGENCY_ADMIN
    );
}

modifier onlyPoolOrEmergencyAdmin() {
    _onlyPoolOrEmergencyAdmin();
    _;
}

function _onlyPoolOrEmergencyAdmin() internal view {
    IACLManager aclManager = IACLManager(
        _addressesProvider.getACLManager()
    );
    require(
        aclManager.isPoolAdmin(msg.sender) || aclManager.isEmergencyAdmin(msg.sender),
        Errors.CALLER_NOT_POOL_OR_EMERGENCY_ADMIN
    );
}

modifier onlyAssetListingOrPoolAdmins() {
    _onlyAssetListingOrPoolAdmins();
    _;
}

function _onlyAssetListingOrPoolAdmins() internal view {
    IACLManager aclManager = IACLManager(
        _addressesProvider.getACLManager()
    );
    require(
        aclManager.isAssetListingAdmin(msg.sender) || aclManager.isPoolAdmin(msg.sender),
        Errors.CALLER_NOT_ASSET_LISTING_OR_POOL_ADMIN
    );
}
```

The pattern is consistent: every privileged function resolves the ACLManager from the PoolAddressesProvider, then checks if `msg.sender` has the required role. There is no shortcut --- even internal functions go through this check.

### Granting and Revoking Roles

The ACL_ADMIN (set on the PoolAddressesProvider) is the `DEFAULT_ADMIN_ROLE` in OpenZeppelin's AccessControl. This address can grant and revoke any role:

```solidity
constructor(IPoolAddressesProvider provider) {
    _addressesProvider = provider;
    address aclAdmin = provider.getACLAdmin();
    require(aclAdmin != address(0), Errors.ACL_ADMIN_CANNOT_BE_ZERO);
    _setupRole(DEFAULT_ADMIN_ROLE, aclAdmin);
}
```

Granting a role:
```solidity
// Only the ACL_ADMIN can do this
aclManager.addPoolAdmin(someAddress);
aclManager.addEmergencyAdmin(someAddress);
aclManager.addRiskAdmin(someAddress);
aclManager.addFlashBorrower(someAddress);
aclManager.addBridge(someAddress);
aclManager.addAssetListingAdmin(someAddress);
```

These are convenience wrappers around OpenZeppelin's `grantRole()`:
```solidity
function addPoolAdmin(address admin) external override {
    grantRole(POOL_ADMIN_ROLE, admin);
}

function removePoolAdmin(address admin) external override {
    revokeRole(POOL_ADMIN_ROLE, admin);
}

function isPoolAdmin(address admin) external view override returns (bool) {
    return hasRole(POOL_ADMIN_ROLE, admin);
}
```

### Summary of Role-to-Function Mapping

| PoolConfigurator Function | Required Role |
|---|---|
| `initReserves()` | ASSET_LISTING_ADMIN or POOL_ADMIN |
| `configureReserveAsCollateral()` | RISK_ADMIN or POOL_ADMIN |
| `setReserveFactor()` | RISK_ADMIN or POOL_ADMIN |
| `setReserveBorrowing()` | RISK_ADMIN or POOL_ADMIN |
| `setBorrowCap()`, `setSupplyCap()` | RISK_ADMIN or POOL_ADMIN |
| `setReserveFreeze()` | RISK_ADMIN or POOL_ADMIN |
| `setReservePause()` | POOL_ADMIN or EMERGENCY_ADMIN |
| `setPoolPause()` | EMERGENCY_ADMIN |
| `updateAToken()`, `updateDebtTokens()` | POOL_ADMIN |
| `setReserveInterestRateStrategyAddress()` | RISK_ADMIN or POOL_ADMIN |
| `setAssetEModeCategory()` | RISK_ADMIN or POOL_ADMIN |
| `setDebtCeiling()` | RISK_ADMIN or POOL_ADMIN |

---

## 3. How Governance Updates Parameters

<video src="../animations/final/governance_flow.webm" controls autoplay loop muted playsinline style="width:100%;max-width:800px;border-radius:8px;margin:20px 0"></video>

In practice, most parameter changes on Aave V3 follow a governance flow. Let's walk through a concrete example: changing the USDC reserve factor from 10% to 15%.

### The Payload Contract

Governance proposals don't call PoolConfigurator directly. They execute through a payload contract --- a simple contract that encodes the desired changes:

```solidity
// Example governance payload
contract UpdateUSDCReserveFactorPayload {
    IPoolConfigurator public immutable POOL_CONFIGURATOR;
    address public constant USDC = 0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48;
    uint256 public constant NEW_RESERVE_FACTOR = 1500; // 15%

    constructor(IPoolConfigurator poolConfigurator) {
        POOL_CONFIGURATOR = poolConfigurator;
    }

    function execute() external {
        POOL_CONFIGURATOR.setReserveFactor(USDC, NEW_RESERVE_FACTOR);
    }
}
```

The payload is deployed in advance so that voters can inspect exactly what the proposal will do. The governance executor calls `execute()` on this contract after the vote passes and the timelock expires.

### Multiple Changes in One Proposal

Governance proposals often bundle multiple parameter changes:

```solidity
contract MultiAssetUpdatePayload {
    IPoolConfigurator public immutable POOL_CONFIGURATOR;

    function execute() external {
        // Update USDC reserve factor
        POOL_CONFIGURATOR.setReserveFactor(USDC, 1500);

        // Update ETH supply cap
        POOL_CONFIGURATOR.setSupplyCap(WETH, 500_000);

        // Update DAI borrow cap
        POOL_CONFIGURATOR.setBorrowCap(DAI, 100_000_000);

        // Enable stable rate borrowing for USDT
        POOL_CONFIGURATOR.setReserveStableRateBorrowing(USDT, true);
    }
}
```

---

## 4. Emergency Controls

Not all situations can wait for a governance vote. Exploits, oracle failures, and market crashes require immediate response. Aave V3 provides two emergency mechanisms: **pause** and **freeze**.

### Freeze vs. Pause

| | Freeze | Pause |
|---|---|---|
| New supply | Blocked | Blocked |
| New borrow | Blocked | Blocked |
| Repay | Allowed | Blocked |
| Withdraw | Allowed | Blocked |
| Liquidation | Allowed | Blocked |
| Flash loan | Allowed | Blocked |
| Who can trigger | RISK_ADMIN or POOL_ADMIN | POOL_ADMIN or EMERGENCY_ADMIN |
| Granularity | Per reserve | Per reserve or entire pool |

The distinction is critical:

**Freeze** is the milder action. It prevents new exposure (no one can supply or borrow more) but allows existing positions to be managed. Users can still repay debts, withdraw their funds, and unhealthy positions can still be liquidated. This is appropriate when there's concern about an asset (e.g., a stablecoin depegging) but no active exploit.

**Pause** is the nuclear option. It stops everything. No one can interact with the reserve at all. This is appropriate during an active exploit where any interaction might drain funds.

### How Validation Checks These Flags

Every operation in Aave V3 runs through `ValidationLogic`. The very first checks are always the reserve status:

```solidity
// From ValidationLogic.sol
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

    // ... supply cap check, etc.
}

function validateBorrow(
    // ... params
) internal view {
    // Same checks: isActive, !isPaused, !isFrozen
    // ... plus health factor, borrow cap, etc.
}

function validateRepay(
    // ... params
) internal view {
    (bool isActive, , , , bool isPaused) = reserveCache
        .reserveConfiguration
        .getFlags();

    require(isActive, Errors.RESERVE_INACTIVE);
    require(!isPaused, Errors.RESERVE_PAUSED);
    // Note: NO frozen check. Repay is allowed when frozen.
}

function validateWithdraw(
    // ... params
) internal view {
    (bool isActive, , , , bool isPaused) = reserveCache
        .reserveConfiguration
        .getFlags();

    require(isActive, Errors.RESERVE_INACTIVE);
    require(!isPaused, Errors.RESERVE_PAUSED);
    // Note: NO frozen check. Withdraw is allowed when frozen.
}
```

The pattern is clear: `supply` and `borrow` check all three flags (active, paused, frozen). `repay` and `withdraw` only check active and paused. This is how freeze allows graceful unwinding while pause stops everything.

### Pausing the Entire Pool

The EMERGENCY_ADMIN can pause all reserves in a single transaction:

```solidity
function setPoolPause(bool paused) external override onlyEmergencyAdmin {
    address[] memory reserves = _pool.getReservesList();
    for (uint256 i = 0; i < reserves.length; i++) {
        if (reserves[i] != address(0)) {
            setReservePause(reserves[i], paused);
        }
    }
}
```

This iterates through every reserve and sets the paused flag. It's a blunt instrument, but when an exploit is in progress, speed matters more than precision.

---

## 5. Upgrading Contracts

<video src="../animations/final/proxy_upgrade.webm" controls autoplay loop muted playsinline style="width:100%;max-width:800px;border-radius:8px;margin:20px 0"></video>

Aave V3's core contracts --- Pool and PoolConfigurator --- are deployed behind transparent proxies. This means their logic can be upgraded without changing the contract address or losing state.

The proxy stores all state (reserve data, user positions, configurations). The implementation contract contains only the logic. When an upgrade occurs, the proxy is pointed to a new implementation, but all state remains intact.

### How an Upgrade Works

1. Governance deploys a new Pool implementation contract (e.g., Pool V3.1).
2. A governance proposal is created to call `PoolAddressesProvider.setPoolImpl(newImpl)`.
3. After the vote passes and the timelock expires, the proposal executes.
4. `setPoolImpl()` updates the proxy to point to the new implementation:

```solidity
function _updateImpl(bytes32 id, address newAddress) internal {
    address proxyAddress = _addresses[id];
    InitializableImmutableAdminUpgradeabilityProxy proxy =
        InitializableImmutableAdminUpgradeabilityProxy(payable(proxyAddress));
    proxy.upgradeTo(newAddress);
}
```

5. From this point forward, all calls to the Pool proxy execute the new implementation's code.

### Storage Compatibility

This is the most critical constraint of proxy upgrades. The new implementation must have a storage layout that is compatible with the old one. Specifically:

- Existing storage variables must remain in the same slots.
- New variables can only be added at the end of the storage layout.
- Existing variables cannot be removed or have their types changed.
- The order of variable declarations must be preserved.

Violating these rules would corrupt existing state. This is why Aave V3 uses reserved storage gaps in its contracts:

```solidity
contract Pool {
    // ... existing state variables ...

    // Reserved storage gap for future upgrades
    uint256[50] private __gap;
}
```

The `__gap` array reserves storage slots that can be consumed by new variables in future implementations without shifting the layout of subsequent variables.

### Upgrading Token Implementations

aTokens and debt tokens are also behind proxies and can be upgraded through PoolConfigurator:

```solidity
function updateAToken(
    ConfiguratorInputTypes.UpdateATokenInput calldata input
) external override onlyPoolAdmin {
    // Get the current aToken proxy
    DataTypes.ReserveData memory reserveData = _pool.getReserveData(input.asset);
    address aTokenProxy = reserveData.aTokenAddress;

    // Update the proxy's implementation
    _upgradeTokenImplementation(
        aTokenProxy,
        input.implementation,
        input.encodedCallData
    );

    emit ATokenUpgraded(input.asset, aTokenProxy, input.implementation);
}
```

Note that only `POOL_ADMIN` can upgrade token implementations --- not `RISK_ADMIN`. This is because a malicious token implementation could drain all funds, so this power is reserved for the highest level of governance.

---

## 6. The Guardian Multisig

In theory, all admin power could flow through governance. In practice, governance votes take days. When an exploit is draining funds, you need to pause the protocol in minutes, not days.

This is why Aave deployments use a **Guardian multisig** --- a multi-signature wallet (typically 5/10 or similar) held by trusted community members. The Guardian holds the `EMERGENCY_ADMIN` role.

### The Two-Track System

**Fast Track (minutes):** Guardian Multisig with EMERGENCY_ADMIN role. Can pause/unpause reserves but cannot change parameters or upgrade contracts. Used for active exploits, oracle failures, and critical bugs.

**Slow Track (days):** Governance (AAVE token holders) controls the Executor contract with POOL_ADMIN role. Can do everything: configure reserves, upgrade contracts, list assets. Enforced by timelock for safety.

This separation ensures that emergency response is fast (multisig signers can respond in minutes) while permanent changes go through the full governance process (days of voting and timelock).

### Why Not Give the Guardian More Power?

The Guardian intentionally cannot:
- Change risk parameters (LTV, liquidation thresholds)
- List new assets
- Upgrade contract implementations
- Modify the interest rate model
- Withdraw from the treasury

If the Guardian multisig were compromised, the attacker could only pause the protocol --- an inconvenience, but not a loss of funds. If the Guardian had POOL_ADMIN powers, a compromise could drain the protocol.

---

## 7. Portal: Cross-Chain Liquidity

<video src="../animations/final/portal.webm" controls autoplay loop muted playsinline style="width:100%;max-width:800px;border-radius:8px;margin:20px 0"></video>

Portal is an Aave V3 feature designed for cross-chain operations. It allows authorized bridge protocols to mint "unbacked" aTokens on one chain, burn them on another, and eventually back them with real assets. The goal is to facilitate seamless cross-chain liquidity movement.

### The BRIDGE Role

Only addresses with the `BRIDGE` role can call `mintUnbacked()`:

```solidity
function mintUnbacked(
    address asset,
    uint256 amount,
    address onBehalfOf,
    uint16 referralCode
) external override onlyBridge {
    BridgeLogic.executeMintUnbacked(
        _reserves,
        _reservesList,
        _usersConfig[onBehalfOf],
        asset,
        amount,
        onBehalfOf,
        referralCode
    );
}
```

### Safety Limits

Portal has built-in safety limits to contain risk:

- **Unbacked Mint Cap**: Each reserve has a maximum amount of unbacked aTokens that can exist at any time. This is the `unbackedMintCap` in the reserve configuration.
- **Bridge Premium**: When backing unbacked aTokens, the bridge must pay a small premium (similar to a flash loan premium). This compensates suppliers for the temporary risk of unbacked tokens.

```solidity
function backUnbacked(
    address asset,
    uint256 amount,
    uint256 fee
) external override onlyBridge {
    BridgeLogic.executeBackUnbacked(
        _reserves,
        asset,
        amount,
        fee,
        _bridgeProtocolFee
    );
}
```

### Current Status

It's worth noting that Portal has seen limited adoption in practice. Cross-chain bridging remains a challenging problem, and most Aave V3 deployments operate as independent markets on each chain. The architecture is there, but the ecosystem of bridge integrations has not materialized as originally envisioned. The feature remains available for future use as cross-chain infrastructure matures.

---

## 8. Putting It All Together

The governance architecture of Aave V3 can be summarized as a layered system of increasing privilege:

| Layer | Role | Permissions |
|-------|------|-------------|
| 0 | Anyone | Supply, borrow, repay, withdraw, liquidate, flash loan |
| 1 | FLASH_BORROWER | Zero-fee flash loans |
| 2 | RISK_ADMIN | Update risk parameters, freeze reserves |
| 3 | EMERGENCY_ADMIN (Guardian) | Pause/unpause reserves and pool |
| 4 | ASSET_LISTING_ADMIN | List new assets |
| 5 | POOL_ADMIN (Governance) | Everything: configure, upgrade, list, pause |
| 6 | AddressesProvider Owner | Upgrade implementations, change ACL admin |

Each layer has strictly more power than the one below it. Each is held by an entity appropriate to its level of trust: anonymous users at Layer 0, a fast-response multisig at Layer 3, and slow-but-secure governance at Layers 5 and 6.

This is the design philosophy of Aave V3's governance: **minimize trust at every layer, and ensure that the most dangerous operations require the most rigorous process.**

---

## Summary

Aave V3's governance architecture is built on three pillars:

- **PoolAddressesProvider** --- the central registry that enables upgradeability and discoverability
- **ACLManager** --- role-based access control that distributes power across well-defined roles
- **Proxy pattern** --- allows contract upgrades while preserving state

In practice, this translates to a two-track system: a Guardian multisig for emergency response (pause/unpause in minutes) and full governance for parameter changes and upgrades (votes and timelocks over days). Every privileged function checks the caller's role through ACLManager, and every role is designed with the principle of least privilege --- each role has exactly the power it needs and no more.
