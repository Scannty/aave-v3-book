# Chapter 1: What is Aave V3

## The Big Idea

Aave V3 is a decentralized money market. It connects two sides of a financial equation: people with idle capital who want to earn yield, and people who need capital and are willing to pay for it.

Suppliers deposit assets into shared liquidity pools and earn interest. Borrowers post collateral and take out loans. The interest borrowers pay flows to suppliers, minus a small cut the protocol keeps for its treasury.

There is no credit check, no KYC, no approval process. Anyone with a wallet can participate. The rules are enforced entirely by smart contracts - code replaces the counterparty.

-

## How It Works: The Five Core Operations

### 1. Supplying

You deposit an asset - say 10,000 USDC - into the protocol. In return, you receive **aUSDC**, an interest-bearing token whose balance increases over time as borrowers pay interest. Your USDC is now pooled with other suppliers' funds and available for borrowers.

You can hold aUSDC, transfer it, use it in other DeFi protocols, or redeem it for the underlying USDC at any time (as long as there is available liquidity in the pool).

### 2. Enabling as Collateral

Most supplied assets are automatically enabled as collateral. You can toggle this on or off per asset. If you disable an asset as collateral, you still earn interest on it, but it cannot back any borrows.

Why would you disable collateral? If you are only supplying for yield and do not want exposure to liquidation risk. As long as you have no borrows, collateral status does not matter. But once you borrow, the protocol uses your enabled collateral to determine how much you can take.

### 3. Borrowing

You select an asset to borrow (say ETH) and the protocol checks whether your collateral is sufficient. Each asset has a **Loan-to-Value (LTV)** ratio - for example, ETH collateral with 80% LTV means \$10,000 of ETH lets you borrow up to \$8,000.

If the math checks out, the protocol transfers the borrowed asset to your wallet and issues **debt tokens** to your address. These debt tokens represent what you owe, and their balance grows as interest accrues - just like aTokens grow for suppliers, debt tokens grow for borrowers.

### 4. Repaying

You return the borrowed asset to the protocol. Your debt tokens are burned. If you repay everything, your position is clean and your collateral is fully unlocked.

You can also repay with aTokens directly - if you have aUSDC and owe USDC, you can cancel one against the other in a single transaction instead of withdrawing first.

### 5. Withdrawing

You redeem your aTokens for the underlying asset. If you have outstanding borrows, the protocol checks that your remaining collateral still covers your debt (your **health factor** stays above 1). If withdrawing would make your position unsafe, the transaction is rejected.

-

## The Unified Pool

<video src="animations/final/unified_pool.webm" controls autoplay loop muted playsinline style="width:100%;max-width:800px;border-radius:8px;margin:20px 0"></video>

Aave V3 manages every listed asset through a single pool. USDC, ETH, WBTC, DAI, and dozens of other assets all share one system. When you supply USDC and borrow ETH, both operations happen in the same pool.

This means **cross-collateralization is built in**. You can deposit a mix of ETH, WBTC, and USDC as collateral for a single loan. The protocol values your entire portfolio using oracle prices and computes a single health factor across all your positions.

The trade-off: since all assets share one pool, risk from one asset can theoretically affect others. This is why Aave V3 has several risk containment mechanisms:

- **Supply and borrow caps** limit how much of any single asset can enter the system
- **Isolation mode** lets the protocol list riskier assets with strict borrowing limits
- **Siloed borrowing** prevents certain risky assets from being borrowed alongside others
- **E-Mode** gives correlated asset pairs better terms while maintaining safety

These features are covered in detail in later chapters.

-

## The Economic Loop

<video src="animations/final/economic_loop.webm" controls autoplay loop muted playsinline style="width:100%;max-width:800px;border-radius:8px;margin:20px 0"></video>

The core economic loop of the protocol is simple:

1. **Suppliers deposit assets** and earn interest
2. **Borrowers post collateral** and pay interest on their loans
3. **Interest rates adjust automatically** based on utilization (what fraction of the pool is borrowed)
4. **The protocol takes a cut** (the reserve factor, typically 10-20%) for its treasury
5. **Liquidators enforce solvency** by closing risky positions before they create bad debt

Every piece of the protocol exists to make this loop work safely and efficiently:

| Component | Role in the Loop |
|-----------|-----------------|
| Interest rate model | Balances supply and demand through dynamic pricing |
| Indexes and scaled balances | Track interest accrual for all users with minimal gas |
| aTokens | Represent supplier deposits, with balances that grow automatically |
| Debt tokens | Represent borrower obligations, with balances that grow automatically |
| Health factor | Measures position safety, triggers liquidation when needed |
| Oracle | Provides real-time asset prices for collateral valuation |
| Governance | Sets risk parameters, lists assets, manages the protocol |

The rest of this book unpacks each of these components in detail, starting with the interest rate model - the mechanism that keeps the two-sided market in balance.

-

## What Makes V3 Different

Aave V3 was not just a code update from V2. It introduced several features that fundamentally changed the protocol's capabilities:

**E-Mode (Efficiency Mode)** - Borrowing a stablecoin against another stablecoin at 80% LTV is unnecessarily conservative. E-Mode lets governance define categories of correlated assets (e.g., USD stablecoins, ETH derivatives) and give them much higher LTV ratios - up to 93%. This dramatically improves capital efficiency for positions involving similar assets.

**Isolation Mode** - Newer or riskier assets can be listed with guardrails: a debt ceiling that caps total borrowing against them, and restrictions on what can be borrowed. This lets the protocol grow its asset catalog without unbounded risk.

**Flash Loans** - Borrow any amount with no collateral, as long as you repay within the same transaction. This enables arbitrage, self-liquidation, collateral swaps, and leveraged position building.

**Cross-Chain Deployment** - Aave V3 runs on Ethereum, Arbitrum, Optimism, Polygon, Avalanche, Base, and more. Each chain has its own pool with independent parameters, but governance flows from Ethereum.

**GHO** - Aave's native stablecoin. Unlike regular borrowing (where you take existing assets from the pool), GHO is minted fresh when you borrow and burned when you repay. All GHO interest goes directly to the Aave treasury.

-

## How to Read This Book

The chapters are designed to be read in order. Each builds on the previous:

- **Chapters 2-3**: The economic engine - interest rates, indexes, and how balances grow
- **Chapters 4-5**: The tokens - aTokens (deposits) and debt tokens (loans)
- **Chapter 6**: The full lifecycle - supply, borrow, repay, withdraw tied together
- **Chapter 7**: Contract architecture - how the code is organized (with Solidity)
- **Chapters 8-9**: Liquidations and flash loans
- **Chapters 10-11**: E-Mode and Isolation Mode
- **Chapters 12-14**: Reserves/treasury, governance, risk features, L2s, and GHO
