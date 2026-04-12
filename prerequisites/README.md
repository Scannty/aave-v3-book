# Prerequisites

Before diving into the internals of Aave V3, you should be comfortable with several foundational concepts. This section covers the background knowledge that the rest of the book assumes you have.

You do not need to be an expert in any of these topics. The goal here is to give you enough understanding so that when these concepts appear in later chapters, you can follow the reasoning without getting stuck.

---

## What You Should Know Before Reading This Book

### 1. [ERC-20 Token Standards and Rebasing Tokens](erc20-token-standards.md)

Aave V3 is built entirely around ERC-20 tokens. When you supply assets, you receive **aTokens** (which are rebasing ERC-20s whose balances grow over time). When you borrow, the protocol mints **debt tokens** that track what you owe. Understanding how standard ERC-20 transfers, approvals, and balances work --- and how rebasing tokens bend those rules --- is essential for understanding Aave's token mechanics.

### 2. [Chainlink Oracles and Price Feeds](chainlink-oracles.md)

Aave needs to know the real-time price of every asset in the protocol. It relies on **Chainlink price feeds** to value collateral, determine borrowing power, and trigger liquidations. If you don't understand how on-chain oracles work, the risk management logic in Aave V3 will be hard to follow.

### 3. [Proxy Patterns and Upgradeability](proxy-patterns.md)

Aave V3's core contracts (Pool, PoolConfigurator, and others) are deployed behind **upgradeable proxies**. This means the protocol can fix bugs and add features without migrating all user positions to new contracts. Understanding `delegatecall`, storage layout, and the difference between Transparent Proxy and UUPS patterns will help you read Aave's deployment and upgrade code.

### 4. [DeFi Liquidations and Collateral](defi-liquidations.md)

Lending protocols must handle the case where a borrower's collateral drops in value. Aave V3 uses **health factors**, **LTV ratios**, and **liquidation thresholds** to decide when a position is unsafe, and it incentivizes external **liquidators** to close those positions. This prerequisite covers the general mechanics so you can focus on Aave's specific implementation in Chapter 7.

---

## How to Use This Section

If you are already familiar with these topics, feel free to skip ahead to [Chapter 1: Architecture](../chapter-1-architecture/). You can always come back here as a reference.

If you are newer to DeFi development, read through each prerequisite in order. They build on each other loosely --- ERC-20 knowledge helps with understanding aTokens, oracle knowledge helps with liquidations, and so on.

---

## What This Section Does NOT Cover

This section assumes you already have:

- **Solidity fundamentals** --- variables, functions, modifiers, mappings, structs, events
- **Ethereum basics** --- transactions, gas, block structure, EOAs vs contracts
- **Basic DeFi concepts** --- what lending/borrowing means, what a DEX is, what yield farming refers to

If you need to brush up on Solidity itself, the [official Solidity docs](https://docs.soliditylang.org/) and [Solidity by Example](https://solidity-by-example.org/) are good starting points.
