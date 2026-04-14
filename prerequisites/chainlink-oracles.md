# Chainlink Oracles and Price Feeds

Smart contracts cannot fetch data from the outside world. They can only read what is already on-chain. This creates a fundamental problem for lending protocols: Aave V3 needs to know the current USD price of ETH, WBTC, USDC, and every other listed asset in order to calculate collateral values, borrowing power, and liquidation eligibility.

**Oracles** solve this problem by bringing off-chain data on-chain.

-

## The Oracle Problem

Consider what happens when a user deposits 10 ETH as collateral and wants to borrow USDC:

1. The protocol needs to know: what is 10 ETH worth in USD?
2. Based on that value and the asset's Loan-to-Value ratio, how much can they borrow?
3. Later, if ETH's price drops, is the position now undercollateralized?

None of these questions can be answered without a reliable price feed. A naive approach - like letting users submit their own prices - would be trivially exploitable. The protocol needs a **trustworthy, decentralized source of price data**.

-

## How Chainlink Price Feeds Work

Chainlink operates a network of independent **oracle nodes**. Each node fetches price data from multiple off-chain sources (exchanges, data aggregators), and the results are aggregated on-chain into a single answer through a decentralized consensus mechanism.

The key properties:

- **Decentralization**: Multiple independent nodes report prices, so no single node can manipulate the feed.
- **Aggregation**: The final on-chain price is typically the median of all node responses, making it resistant to outliers.
- **Regular updates**: Prices are updated either on a heartbeat (e.g., every hour) or when the price deviates beyond a threshold (e.g., 1%).

Each price feed is deployed as its own contract on-chain. For example, the ETH/USD price feed on Ethereum mainnet lives at a specific address and can be queried by any contract.

-

## The AggregatorV3Interface

Chainlink price feeds implement the `AggregatorV3Interface`. This is the interface your contract interacts with:

```solidity
interface AggregatorV3Interface {
    function decimals() external view returns (uint8);

    function description() external view returns (string memory);

    function version() external view returns (uint256);

    function getRoundData(uint80 _roundId)
        external
        view
        returns (
            uint80 roundId,
            int256 answer,
            uint256 startedAt,
            uint256 updatedAt,
            uint80 answeredInRound
        );

    function latestRoundData()
        external
        view
        returns (
            uint80 roundId,
            int256 answer,
            uint256 startedAt,
            uint256 updatedAt,
            uint80 answeredInRound
        );
}
```

The function you will see most often is `latestRoundData()`, which returns the most recent price update.

-

## Reading a Price Feed

Here is a minimal example of reading the ETH/USD price:

```solidity
import "@chainlink/contracts/src/v0.8/interfaces/AggregatorV3Interface.sol";

contract PriceConsumer {
    AggregatorV3Interface internal priceFeed;

    constructor(address _priceFeed) {
        priceFeed = AggregatorV3Interface(_priceFeed);
    }

    function getLatestPrice() public view returns (int256) {
        (
            uint80 roundId,
            int256 answer,
            uint256 startedAt,
            uint256 updatedAt,
            uint80 answeredInRound
        ) = priceFeed.latestRoundData();

        return answer;
    }
}
```

The `answer` field contains the price. But there are two critical details you must handle correctly: **decimals** and **staleness**.

-

## Price Decimals

Different Chainlink feeds use different numbers of decimals:

| Feed | Decimals | Example answer | Actual price |
|------|----------|---------------|--------------|
| ETH/USD | 8 | 350000000000 | \$3,500.00 |
| BTC/USD | 8 | 6500000000000 | \$65,000.00 |
| USDC/USD | 8 | 100000000 | \$1.00 |
| ETH/BTC | 18 | 53800000000000000 | 0.0538 BTC |

USD-denominated feeds typically use **8 decimals**. ETH-denominated feeds typically use **18 decimals**.

You must call `decimals()` on the feed (or know the expected value) to correctly interpret the `answer`. This is especially important in Aave V3, where collateral values from different assets with different decimal precisions must be compared on a common basis.

```solidity
uint8 feedDecimals = priceFeed.decimals();
// To normalize to 18 decimals:
uint256 normalizedPrice = uint256(answer) * 10 ** (18 - feedDecimals);
```

-

## Staleness Checks

A price feed can go stale if Chainlink nodes stop updating it (due to network congestion, a black swan event, or feed deprecation). Using a stale price is dangerous - it could lead to incorrect liquidations or allow borrowing against inflated collateral.

A proper integration checks how recently the price was updated:

```solidity
function getLatestPrice() public view returns (int256) {
    (
        uint80 roundId,
        int256 answer,
        uint256 startedAt,
        uint256 updatedAt,
        uint80 answeredInRound
    ) = priceFeed.latestRoundData();

    // Ensure the answer is positive
    require(answer > 0, "Invalid price");

    // Ensure the price is not stale
    require(
        block.timestamp - updatedAt <= MAX_STALENESS,
        "Price is stale"
    );

    // Ensure the round is complete
    require(answeredInRound >= roundId, "Round not complete");

    return answer;
}
```

The `updatedAt` timestamp tells you when the price was last refreshed. The `MAX_STALENESS` threshold depends on the feed's expected update frequency - for a feed with a 1-hour heartbeat, you might set staleness to 3600 seconds plus some buffer.

-

## Why Aave Needs Oracles

In Aave V3, oracle prices are used in several critical operations:

### Collateral Valuation
When you supply assets, the protocol needs to calculate the USD value of your collateral to determine your borrowing capacity. This happens every time you try to borrow or withdraw.

### Health Factor Calculation
Your **health factor** is the ratio of your risk-adjusted collateral value to your total debt value. Both sides of this ratio depend on oracle prices. A health factor below 1.0 means your position can be liquidated.

### Liquidation Triggers
Liquidators monitor health factors. When a position becomes undercollateralized (health factor < 1.0), a liquidator can repay part of the debt and receive the collateral at a discount. Accurate, timely prices are essential to make this work correctly.

### E-Mode Price Correlation
Aave V3's Efficiency Mode (E-Mode) allows higher LTV ratios for correlated assets (e.g., stablecoins or ETH derivatives). The oracle must confirm that these assets remain correlated - if one depegs, the protocol needs to detect it.

-

## Aave's Oracle Implementation

Aave V3 wraps Chainlink feeds in its own `AaveOracle` contract. This provides:

- A single entry point for all asset prices (`getAssetPrice(address asset)`)
- The ability to set fallback oracles
- Governance control over which feeds are used for which assets
- Consistent decimal handling across all assets

When you see `oracle.getAssetPrice(asset)` in the Aave codebase, it is ultimately reading from a Chainlink `AggregatorV3Interface` under the hood.

-

## Summary

| Concept | Why It Matters |
|---------|---------------|
| Oracles bring off-chain data on-chain | Smart contracts cannot fetch external prices |
| `latestRoundData()` returns the current price | This is the primary function Aave calls |
| Decimals vary by feed | Must normalize when comparing different assets |
| Staleness checks prevent using outdated prices | Critical for protocol safety |
| Aave wraps feeds in `AaveOracle` | Provides a unified price interface for the protocol |

Understanding Chainlink price feeds is essential background for Chapters 1 (Architecture), 7 (Liquidations), and 9 (E-Mode) of this book.
