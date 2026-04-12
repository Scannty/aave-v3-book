# Chapter 14: L2 Deployments, PriceOracleSentinel, and GHO

Aave V3 is not a single deployment on Ethereum mainnet. It runs on Arbitrum, Optimism, Polygon, Avalanche, Base, and a growing list of other chains. The same contracts --- `Pool.sol`, `AToken.sol`, `VariableDebtToken.sol`, all the logic libraries --- are deployed on each chain with chain-specific parameters. From a user's perspective, borrowing ETH on Arbitrum looks identical to borrowing ETH on mainnet.

But L2 chains introduce a risk that doesn't exist on L1: **sequencer downtime**. And Aave V3 introduces something that doesn't exist in any predecessor: **GHO**, a stablecoin that is minted rather than borrowed from a pool.

This chapter covers both.

---

## 1. The Sequencer Problem

Every optimistic rollup (Arbitrum, Optimism, Base) relies on a centralized sequencer to order transactions. If the sequencer goes down, users cannot submit transactions to the L2. No trades, no oracle updates, no collateral top-ups. The chain effectively freezes.

This creates a specific danger for lending protocols. Consider the timeline:

1. The Arbitrum sequencer goes offline at 2:00 PM. ETH is worth $2,000.
2. During the downtime, ETH drops to $1,700 on mainnet. But the Arbitrum price feed is stale --- it still shows $2,000.
3. The sequencer comes back online at 4:00 PM. Oracle prices update to $1,700.
4. A liquidation bot immediately liquidates every position that became unhealthy during the two-hour window.

The borrowers in step 4 had no chance to react. They couldn't add collateral or repay debt because the sequencer was down. Liquidating them instantly is unfair and could cause a cascade of unnecessary liquidations.

Without protection, sequencer downtime turns into a mass liquidation event.

---

## 2. PriceOracleSentinel

Aave's solution is the `PriceOracleSentinel`. It acts as a gatekeeper that pauses certain operations when the sequencer has recently recovered, giving users time to manage their positions.

### How It Knows the Sequencer Is Down

Chainlink provides a **Sequencer Uptime Feed** on each L2. This is a special oracle that reports whether the L2 sequencer is currently operational. The feed returns two values: a status (0 = up, 1 = down) and the timestamp of the last status change.

`PriceOracleSentinel` wraps this feed through an `ISequencerOracle` interface:

```solidity
// From ISequencerOracle.sol
interface ISequencerOracle {
    function latestRoundData()
        external
        view
        returns (
            uint80 roundId,
            int256 answer,      // 0 = sequencer is up, 1 = down
            uint256 startedAt,  // timestamp of last status change
            uint256 updatedAt,
            uint80 answeredInRound
        );
}
```

### The Grace Period

When the sequencer comes back online, `PriceOracleSentinel` enforces a **grace period** --- a configurable window (typically 1 hour) during which:

- **Liquidations are NOT allowed.** Users need time to add collateral or repay debt.
- **Borrowing is NOT allowed.** Prices may still be stale or volatile; allowing borrows could let attackers take advantage of temporarily incorrect prices.
- **Supply, repay, and withdraw still work.** These operations are safe. Supplying more collateral or repaying debt improves the user's position. Withdrawals are validated against the health factor as usual.

After the grace period expires, all operations resume normally.

### The Code

The sentinel exposes two key functions:

```solidity
// From PriceOracleSentinel.sol

function isBorrowAllowed() external view override returns (bool) {
    return _isUpAndGracePeriodPassed();
}

function isLiquidationAllowed() external view override returns (bool) {
    return _isUpAndGracePeriodPassed();
}

function _isUpAndGracePeriodPassed() internal view returns (bool) {
    (, int256 answer, , uint256 startedAt, ) = _sequencerOracle
        .latestRoundData();

    // If the sequencer is currently down, block operations
    if (answer != 0) return false;

    // If the sequencer is up but the grace period hasn't passed, block operations
    if (block.timestamp - startedAt <= _gracePeriod) return false;

    return true;
}
```

The logic is straightforward. Query the sequencer oracle. If the sequencer is down (`answer != 0`), return false. If the sequencer is up but came back online less than `_gracePeriod` seconds ago, return false. Otherwise, return true.

### Integration with ValidationLogic

The sentinel is wired into the protocol's validation layer. Before executing a borrow or liquidation, the validation functions check the sentinel:

```solidity
// From ValidationLogic.sol --- inside validateBorrow()

if (
    params.userEModeCategory == 0 ||
    EModeConfiguration.isReserveEnabledOnBitmap(
        eModeCategories[params.userEModeCategory].borrowableBitmap,
        reserveIndex
    )
) {
    // ... other validation ...

    if (address(params.priceOracleSentinel) != address(0)) {
        require(
            params.priceOracleSentinel.isBorrowAllowed(),
            Errors.PRICE_ORACLE_SENTINEL_CHECK_FAILED
        );
    }
}
```

And for liquidations:

```solidity
// From ValidationLogic.sol --- inside validateLiquidationCall()

if (address(params.priceOracleSentinel) != address(0)) {
    require(
        params.priceOracleSentinel.isLiquidationAllowed(),
        Errors.PRICE_ORACLE_SENTINEL_CHECK_FAILED
    );
}
```

Notice the `address(0)` check. On L1 deployments (Ethereum mainnet), the `PriceOracleSentinel` is not configured --- the address is zero. The check is skipped entirely. The sentinel only matters on L2s where sequencer risk exists.

### Why Borrowing Is Also Paused

It might seem like only liquidations need to be paused. But consider this attack:

1. The sequencer comes back online. Oracle prices haven't fully updated yet.
2. An attacker borrows at stale prices that are favorable to them --- for example, the oracle still shows their collateral at $2,000 when the real market price is $1,700.
3. By the time prices update, the attacker has extracted value from the protocol.

Pausing borrows during the grace period closes this vector. Users who need to improve their positions can still supply collateral and repay debt.

### Configuration

The grace period is set by governance through the `PoolAddressesProvider`:

```solidity
function setGracePeriod(uint256 newGracePeriod) external onlyPoolAdmin {
    _gracePeriod = newGracePeriod;
    emit GracePeriodUpdated(newGracePeriod);
}
```

A typical grace period is 3600 seconds (1 hour). This gives users enough time to react without keeping the protocol frozen for too long.

---

## 3. GHO: Aave's Native Stablecoin

GHO is a decentralized, USD-pegged stablecoin created by Aave governance. It is fundamentally different from every other asset on Aave because it is **minted, not borrowed from a pool**.

### How GHO Differs from Regular Borrowing

When you borrow USDC on Aave, this is what happens:

1. Suppliers deposit USDC into the pool. They receive aUSDC.
2. You post collateral and borrow from that pool. The USDC is transferred from the pool to your wallet.
3. You pay interest. That interest is shared between suppliers (most of it) and the treasury (the reserve factor portion).
4. You repay. The USDC goes back into the pool.

There is a finite supply of USDC in the pool. If all of it is borrowed, the utilization rate hits 100%, interest rates spike, and no one else can borrow until someone repays.

GHO works differently:

1. There are **no GHO suppliers**. No one deposits GHO into a pool.
2. You post collateral and "borrow" GHO. New GHO tokens are **minted** and sent to your wallet.
3. You pay interest. **100% of that interest goes to the Aave treasury** --- there are no suppliers to share with.
4. You repay. The GHO is **burned**. It ceases to exist.

This means GHO has no utilization curve. There is no pool to be drained. The supply of GHO expands and contracts based on user demand.

### The Facilitator Model

GHO is not exclusively minted by the Aave Pool. The GHO token contract uses a **Facilitator** abstraction. A Facilitator is any approved contract that can mint and burn GHO, subject to a capacity limit.

```solidity
// From GhoToken.sol

struct Facilitator {
    uint128 bucketCapacity;   // max GHO this facilitator can have minted
    uint128 bucketLevel;      // current amount of GHO minted by this facilitator
    string label;             // human-readable name
}

mapping(address => Facilitator) internal _facilitators;

function mint(address account, uint256 amount) external {
    require(_facilitators[msg.sender].bucketCapacity > 0, 'INVALID_FACILITATOR');

    uint256 newBucketLevel = _facilitators[msg.sender].bucketLevel + amount;
    require(
        newBucketLevel <= _facilitators[msg.sender].bucketCapacity,
        'FACILITATOR_BUCKET_CAPACITY_EXCEEDED'
    );

    _facilitators[msg.sender].bucketLevel = uint128(newBucketLevel);
    _mint(account, amount);
}
```

The Aave V3 Pool on Ethereum is the primary Facilitator. But governance can approve additional Facilitators --- for example, a FlashMinter Facilitator that allows flash-minting GHO (similar to flash loans but for newly created tokens).

Each Facilitator has a **bucket capacity**: the maximum amount of GHO it can have outstanding at any time. This is a critical safety mechanism. If a Facilitator is compromised, the damage is bounded by its bucket capacity. Governance sets and adjusts these limits.

### GHO Interest Rates

Regular Aave assets have interest rates determined by the utilization curve (Chapter 2). GHO does not. Since there is no supply pool, there is no utilization metric.

Instead, the GHO borrow rate is set directly by governance through a custom interest rate strategy:

```solidity
// From GhoInterestRateStrategy.sol

contract GhoInterestRateStrategy is IGhoInterestRateStrategy {
    uint256 internal _borrowRate;

    function calculateInterestRates(
        DataTypes.CalculateInterestRatesParams memory
    ) external view override returns (uint256, uint256, uint256) {
        // Supply rate is always 0 (no suppliers)
        // Stable borrow rate is 0 (GHO only uses variable)
        // Variable borrow rate is the governance-set rate
        return (0, 0, _borrowRate);
    }

    function setInterestRate(uint256 newBorrowRate) external onlyRiskAdmin {
        uint256 oldBorrowRate = _borrowRate;
        _borrowRate = newBorrowRate;
        emit BorrowRateUpdated(oldBorrowRate, newBorrowRate);
    }
}
```

The rate is typically set below market rates for comparable stablecoins. This is intentional --- a lower borrow rate encourages users to mint GHO, which increases its circulating supply and liquidity. Governance adjusts the rate based on market conditions and the GHO peg.

### The stkAAVE Discount

GHO includes a mechanism that ties it to the AAVE token economy. Users who hold **stkAAVE** (staked AAVE in the Safety Module) receive a discount on their GHO borrow rate.

The discount is managed by a `GhoDiscountRateStrategy`:

```solidity
// Simplified from GhoDiscountRateStrategy.sol

contract GhoDiscountRateStrategy is IGhoDiscountRateStrategy {
    uint256 public constant GHO_DISCOUNTED_PER_DISCOUNT_TOKEN = 100e18;
    uint256 public constant DISCOUNT_RATE = 2000; // 20% in basis points

    function calculateDiscountRate(
        uint256 debtBalance,
        uint256 discountTokenBalance  // stkAAVE balance
    ) external pure override returns (uint256) {
        uint256 discountedBalance = discountTokenBalance
            * GHO_DISCOUNTED_PER_DISCOUNT_TOKEN;

        if (discountedBalance >= debtBalance) {
            return DISCOUNT_RATE; // full discount
        } else {
            return (DISCOUNT_RATE * discountedBalance) / debtBalance; // proportional
        }
    }
}
```

The idea: each stkAAVE token entitles the holder to a discounted rate on up to 100 GHO of debt. If you hold 10 stkAAVE, you get the discount on up to 1,000 GHO. If your GHO debt exceeds the discounted amount, only a proportional discount applies.

This creates a demand driver for AAVE staking. Users who want cheaper GHO borrowing have an incentive to buy and stake AAVE, which strengthens the Safety Module and the protocol's overall security.

### How GHO Fits into the Pool

Despite its unique minting mechanics, GHO integrates into the Aave Pool in a way that looks familiar to the existing architecture. From the Pool's perspective, a GHO "borrow" still:

- Validates collateral and health factor through `ValidationLogic`
- Updates debt token balances through `VariableDebtToken`
- Is subject to liquidation if the health factor drops below 1
- Accrues interest that compounds through the normal index mechanism

The key difference is in the token flow. When the Pool processes a GHO borrow, instead of transferring existing tokens from a supply pool, it calls `GhoToken.mint()`. When processing a repay, it calls `GhoToken.burn()`. The collateral and liquidation mechanics are identical to any other asset.

### Revenue Implications

GHO is a significant revenue source for the Aave treasury. With regular assets, the protocol only receives the reserve factor portion of interest (typically 10-20%). With GHO, the treasury receives **100% of borrow interest** because there are no suppliers to compensate.

If 500 million GHO is outstanding at a 3% borrow rate, that is $15 million per year flowing directly to the Aave treasury. This makes GHO one of the most important economic primitives in the Aave ecosystem.

### Current Status

GHO launched on Ethereum mainnet and is expanding to additional chains. Cross-chain GHO involves bridge mechanisms and additional Facilitators on destination chains, allowing GHO minted on one chain to be used on another while maintaining consistent accounting.

---

## 4. Multi-chain Governance

Aave governance lives on Ethereum mainnet. All governance proposals --- parameter changes, new asset listings, risk configuration updates --- are voted on and executed on L1. But these decisions need to reach deployments on Arbitrum, Optimism, Base, and every other chain where Aave is deployed.

### Cross-chain Execution

When a governance proposal targets an L2 deployment, the execution flow is:

1. The proposal passes on Ethereum mainnet through the standard governance process (Chapter 12).
2. The execution payload includes a cross-chain message routed through a bridge (typically the native L1-to-L2 messaging bridge for the target chain).
3. A `CrossChainForwarder` on Ethereum sends the encoded payload to the target chain.
4. A `CrossChainExecutor` on the L2 receives and executes the payload, applying the governance decision to the local Pool deployment.

Each chain has its own `PoolAddressesProvider`, its own `Pool`, its own set of reserve configurations. But the authority to change any of these flows from Ethereum governance. No single admin on an L2 can unilaterally modify protocol parameters.

### Per-chain Configuration

While governance is centralized on Ethereum, each chain deployment has independent parameters. The same asset might have different LTVs, liquidation thresholds, or interest rate strategies on different chains. This makes sense --- the liquidity profile, oracle infrastructure, and risk characteristics of an asset can vary significantly across chains.

For example, USDC on Ethereum mainnet might have different risk parameters than bridged USDC on Arbitrum, because bridged assets carry additional bridge risk that native assets do not.

---

## 5. Putting It Together

The additions in this chapter --- `PriceOracleSentinel` and GHO --- represent two different dimensions of Aave V3's evolution beyond a simple lending pool.

The sentinel addresses **deployment risk**. Moving to L2s brings lower fees and faster transactions, but it also introduces sequencer dependency. The grace period mechanism is a targeted solution: minimal code, no changes to the core liquidation logic, just a validation check that gates operations during a vulnerable window.

GHO addresses **economic design**. Instead of being a pure intermediary between suppliers and borrowers, Aave becomes an issuer. The protocol mints its own stablecoin, captures 100% of the interest, and uses the stkAAVE discount to tie the stablecoin's success to the governance token's value. The Facilitator model keeps this extensible without concentrating risk.

Both features share a design philosophy that runs through all of Aave V3: **solve the problem at the right layer of abstraction**. The sentinel doesn't change how liquidations work --- it adds a precondition. GHO doesn't change how collateral or health factors work --- it changes where the borrowed tokens come from. The core protocol remains the same.

With this chapter, you have the complete picture of Aave V3: the interest rate model, the index system, the token mechanics, supply and borrow flows, liquidations, flash loans, E-Mode, isolation mode, reserves, governance, risk features, L2 protections, and GHO. These are the building blocks of the most widely deployed lending protocol in DeFi.
