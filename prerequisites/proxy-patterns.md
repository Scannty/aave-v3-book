# Proxy Patterns and Upgradeability

Smart contracts on Ethereum are immutable by default. Once deployed, their bytecode cannot change. This is a feature - users can verify exactly what code will execute. But it is also a constraint. Bugs cannot be patched. New features cannot be added. For a protocol like Aave V3, which manages billions of dollars and must evolve over time, immutability alone is not practical.

**Upgradeable proxy patterns** solve this by separating the contract's storage and address from its logic.

---

## Why Upgradeability Matters for DeFi

Consider what happens if a critical bug is found in an immutable lending protocol:

1. Deploy a new, fixed contract
2. Convince every user to migrate their positions (withdraw, re-approve, re-deposit)
3. Update every integration that references the old contract address

This is slow, expensive, and error-prone. Users might not migrate. Integrations might break. The protocol's TVL could collapse during the transition.

With an upgradeable proxy:

1. Deploy the new logic contract
2. Point the proxy to the new logic
3. All user positions, balances, and approvals remain intact at the same address

Aave V3 uses this approach for its core contracts, including the `Pool`, `PoolConfigurator`, and several others. Governance controls when and how upgrades happen.

---

## The Core Mechanism: delegatecall

The proxy pattern relies on a single EVM opcode: `delegatecall`.

A normal `call` executes code in the **target** contract's context:
- Uses the target's storage
- `msg.sender` is the caller
- `address(this)` is the target

A `delegatecall` executes code in the **caller's** context:
- Uses the **caller's** storage
- `msg.sender` is preserved from the original transaction
- `address(this)` is the **caller** (the proxy)

<video src="animations/final/delegatecall.webm" controls autoplay loop muted playsinline style="width:100%;max-width:800px;border-radius:8px;margin:20px 0"></video>

This means the proxy holds all the state (balances, mappings, etc.) while the implementation contract provides the logic. The implementation is stateless - it only defines what to do, not where the data lives.

---

## How a Basic Proxy Works

A minimal proxy contract looks like this:

```solidity
contract Proxy {
    // Slot for the implementation address (using EIP-1967 slot)
    bytes32 private constant IMPLEMENTATION_SLOT =
        0x360894a13ba1a3210667c828492db98dca3e2076cc3735a920a3ca505d382bbc;

    fallback() external payable {
        address impl = _getImplementation();

        assembly {
            // Copy calldata
            calldatacopy(0, 0, calldatasize())

            // delegatecall to implementation
            let result := delegatecall(gas(), impl, 0, calldatasize(), 0, 0)

            // Copy return data
            returndatacopy(0, 0, returndatasize())

            // Return or revert based on result
            switch result
            case 0 { revert(0, returndatasize()) }
            default { return(0, returndatasize()) }
        }
    }

    function _getImplementation() internal view returns (address impl) {
        bytes32 slot = IMPLEMENTATION_SLOT;
        assembly {
            impl := sload(slot)
        }
    }
}
```

The `fallback()` function intercepts every call to the proxy and forwards it via `delegatecall` to the implementation. Since Solidity routes function calls by matching the first 4 bytes of calldata (the function selector), the proxy does not need to know anything about the implementation's interface.

---

## Storage Layout: The Critical Constraint

Because `delegatecall` uses the **proxy's** storage, the implementation's storage layout must be carefully managed across upgrades.

Storage in Solidity is a key-value store where keys are 256-bit **slots**. State variables are assigned to slots sequentially:

```solidity
contract V1 {
    uint256 public value;    // slot 0
    address public owner;    // slot 1
}
```

If you upgrade to a new implementation, the new contract must preserve this layout:

```solidity
// CORRECT: new variable added at the end
contract V2 {
    uint256 public value;    // slot 0 (same)
    address public owner;    // slot 1 (same)
    bool public paused;      // slot 2 (new)
}
```

```solidity
// WRONG: inserting a variable shifts all subsequent slots
contract V2Bad {
    bool public paused;      // slot 0 (COLLISION with value!)
    uint256 public value;    // slot 1 (COLLISION with owner!)
    address public owner;    // slot 2
}
```

A storage collision means the new code interprets old data with the wrong type. A `uint256` balance could be read as an `address`, or vice versa. This silently corrupts the protocol's state.

### Storage Gaps

A common pattern to reserve space for future variables:

```solidity
contract V1 {
    uint256 public value;
    address public owner;

    // Reserve 50 slots for future use
    uint256[50] private __gap;
}
```

When V2 needs a new variable, it shrinks the gap:

```solidity
contract V2 {
    uint256 public value;
    address public owner;
    bool public paused;          // uses one slot from the gap

    uint256[49] private __gap;   // 50 - 1 = 49
}
```

Aave V3 uses storage gaps in its upgradeable contracts to allow safe future extensions.

---

## Transparent Proxy Pattern

The **Transparent Proxy** pattern (introduced by OpenZeppelin) solves a subtle problem: what if the proxy and the implementation both have a function with the same selector?

For example, if both the proxy and the implementation define `upgrade(address)`, which one runs when you call it?

The Transparent Proxy solves this with a simple rule:

- If the caller is the **admin**, the call goes to the proxy itself (for admin functions like `upgrade`)
- If the caller is **anyone else**, the call is forwarded to the implementation via `delegatecall`

```solidity
fallback() external payable {
    if (msg.sender == admin) {
        // Handle admin functions (upgrade, changeAdmin, etc.)
    } else {
        // delegatecall to implementation
        _delegate(_getImplementation());
    }
}
```

This means the admin **cannot** interact with the implementation's functions through the proxy, and regular users **cannot** call the proxy's admin functions. The separation is clean but costs extra gas (an `SLOAD` to check the admin address on every call).

In practice, the admin is typically a `ProxyAdmin` contract controlled by governance, not an EOA.

---

## UUPS Pattern

The **Universal Upgradeable Proxy Standard** (UUPS, EIP-1822) takes a different approach: the upgrade logic lives in the **implementation**, not the proxy.

```solidity
// The proxy is minimal - just delegatecall
contract UUPSProxy {
    fallback() external payable {
        _delegate(_getImplementation());
    }
}

// The implementation contains the upgrade function
contract ImplementationV1 is UUPSUpgradeable {
    function upgradeTo(address newImplementation) external onlyAdmin {
        _setImplementation(newImplementation);
    }

    // ... business logic
}
```

Advantages of UUPS over Transparent Proxy:

| Aspect | Transparent Proxy | UUPS |
|--------|------------------|------|
| Upgrade logic location | In the proxy | In the implementation |
| Gas cost per call | Higher (admin check) | Lower (no admin check) |
| Proxy contract size | Larger | Smaller (cheaper deploy) |
| Risk of bricking | Lower | Higher (if upgrade logic is omitted from new implementation) |

The main risk with UUPS: if you deploy a new implementation that does not include the `upgradeTo` function, the proxy becomes permanently non-upgradeable. There is no fallback mechanism.

---

## Initializers Instead of Constructors

Constructors run only once at deploy time and set state in the **implementation's** storage, not the proxy's. Since the proxy's storage is what matters, constructors are useless in upgradeable contracts.

Instead, upgradeable contracts use **initializer functions**:

```solidity
contract PoolV1 is Initializable {
    address public admin;
    bool private _initialized;

    function initialize(address _admin) external initializer {
        admin = _admin;
    }
}
```

The `initializer` modifier (from OpenZeppelin) ensures the function can only be called once, mimicking the one-time execution guarantee of a constructor. You will see `initialize()` functions throughout the Aave V3 codebase.

---

## How Aave V3 Uses Proxies

Aave V3 deploys its core contracts behind upgradeable proxies:

- **Pool**: The main entry point for supply, borrow, repay, withdraw, and liquidation. Deployed behind a proxy so the protocol can fix bugs or add features without moving user positions.
- **PoolConfigurator**: Manages reserve parameters (LTV, liquidation threshold, interest rate strategy). Also upgradeable.
- **aTokens and Debt Tokens**: Each reserve's token contracts are deployed behind proxies.

The upgrade process is governed - the Aave DAO votes on proposals that include the new implementation address. The `PoolAddressesProvider` contract acts as a registry, storing the current proxy addresses and controlling upgrades.

```
PoolAddressesProvider
  |
  |- getPool() -> Proxy -> PoolV3Implementation
  |- getPoolConfigurator() -> Proxy -> PoolConfiguratorV3Implementation
```

When governance approves an upgrade, the `PoolAddressesProvider` calls `setPoolImpl(newAddress)`, which updates the proxy's implementation slot. All calls to the Pool address now execute the new logic, while all storage (user balances, reserve configurations) remains untouched.

---

## Summary

| Concept | Key Point |
|---------|-----------|
| `delegatecall` | Executes logic in the caller's storage context |
| Proxy pattern | Separates storage (proxy) from logic (implementation) |
| Storage layout | Must be preserved across upgrades or data corrupts |
| Transparent Proxy | Admin calls go to proxy, user calls go to implementation |
| UUPS | Upgrade logic in implementation, cheaper per-call gas |
| Initializers | Replace constructors in upgradeable contracts |
| Aave V3 | Core contracts (Pool, tokens) are all behind proxies |

Understanding proxy patterns is essential for reading Aave V3's deployment code, upgrade proposals, and the `PoolAddressesProvider` registry covered in Chapter 1.
