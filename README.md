# The Aave V3 Book

A comprehensive, developer-focused guide to understanding the Aave V3 protocol from the inside out.

## What This Book Covers

Aave V3 is one of the most widely used decentralized lending protocols in DeFi. This book provides a deep technical walkthrough of how it works — from the high-level architecture down to the smart contract implementations.

Unlike documentation that tells you *how to use* Aave, this book explains *how Aave works*. We examine the contract architecture, the math behind interest rates and liquidations, and the design patterns that make the protocol tick.

## Who This Book Is For

This book is written for **intermediate-to-advanced Solidity developers** who want to deeply understand Aave V3's internals. You should be comfortable reading Solidity and have a basic understanding of DeFi lending concepts.

If you're new to DeFi lending, start with the [Prerequisites](prerequisites/README.md) section first.

## How to Read This Book

The chapters are designed to be read in order. Each chapter builds on concepts introduced in previous ones:

1. **Chapters 1-3** establish the architecture and core math (interest rates, indexes)
2. **Chapters 4-5** cover the token layer (aTokens, debt tokens)
3. **Chapter 6** ties it all together with the full supply/borrow/repay/withdraw flows
4. **Chapters 7-8** cover liquidations and flash loans
5. **Chapters 9-10** cover Aave V3's unique features: E-Mode and Isolation Mode
6. **Chapters 11-12** cover protocol economics and governance

Take your time. Mastering the entire protocol in a single sitting isn't realistic — pace yourself and revisit sections as needed.

## Source Code References

Throughout this book, we reference the [aave-v3-core](https://github.com/aave/aave-v3-core) repository. Code snippets and contract references point to the official Aave V3 smart contracts.

## Table of Contents

See [SUMMARY.md](SUMMARY.md) for the full table of contents.
