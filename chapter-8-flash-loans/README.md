# Chapter 8: Flash Loans

Imagine walking into a bank and saying: "Lend me \$100 million. No collateral. No credit check. I will return it in 12 seconds." In traditional finance, you would be escorted out. In DeFi, this happens thousands of times a day. It is called a **flash loan**, and Aave pioneered it.

The concept is simple: borrow any amount of any asset, with zero collateral, as long as you repay the full amount plus a small fee within the same transaction. If you fail to repay, the entire transaction reverts --- as if it never happened. The protocol's funds were never at risk.

This is not a loophole or a hack. It is a fundamental consequence of how blockchains work, and it unlocks financial operations that are impossible in any other system.

---

## 1. Why Flash Loans Are Possible

Flash loans exploit a property unique to blockchains: **transaction atomicity**. An Ethereum transaction is all-or-nothing. Every state change within a transaction either completes successfully, or the entire transaction reverts to the starting state. There is no middle ground.

This creates a remarkable guarantee: the protocol can lend you \$100 million because it knows that if you do not return it, the loan never happened. From the blockchain's perspective, the funds never left the pool. The ledger at the end of the block looks exactly as it did before.

Compare this to traditional lending, where risk exists because time passes between disbursement and repayment. The borrower could disappear, go bankrupt, or refuse to pay. Flash loans eliminate the time dimension entirely. The loan is issued and repaid within a single atomic operation that takes about 12 seconds (one block).

This means flash loans carry **zero risk to the protocol**:

- **No credit risk**: Repayment is guaranteed by the blockchain itself.
- **No liquidity risk**: Funds leave and return in the same block.
- **No duration risk**: There is no time window for default.
- **Positive economics**: The protocol earns a fee on every successful flash loan.

---

## 2. The Fee Structure

Flash loans are not free. The borrower pays a **premium** of **0.05%** (5 basis points) on most Aave V3 deployments.

| Loan Amount | Premium (0.05%) | You Repay |
|-------------|-----------------|-----------|
| \$1,000 | \$0.50 | \$1,000.50 |
| \$100,000 | \$50 | \$100,050 |
| \$1,000,000 | \$500 | \$1,000,500 |
| \$50,000,000 | \$25,000 | \$50,025,000 |

The premium is split between two recipients:

1. **Liquidity providers** receive the majority. The fee increases the liquidity index, meaning all depositors earn a proportional share of flash loan revenue --- the same mechanism as interest income.

2. **The Aave treasury** receives a governance-configured portion via `accruedToTreasury`.

The exact split is configurable. If the total premium is 5 bps and the protocol's share is 4 bps, then on a \$1M loan: suppliers earn \$100 and the treasury earns \$400.

The amount you can borrow is limited only by the available liquidity in a reserve. If there is \$500M of USDC deposited and not currently lent out, you can flash loan up to \$500M.

---

## 3. Use Cases: What You Can Do with Unlimited Capital

Flash loans are powerful because they give anyone --- even someone with \$0 --- temporary access to millions of dollars. The catch is that you must generate enough value within a single transaction to repay the loan plus the fee. Here are the most common strategies.

### Arbitrage

The classic use case. If USDC/ETH is priced differently across two exchanges:

1. Flash loan 1,000,000 USDC from Aave
2. Buy ETH on the cheaper exchange
3. Sell ETH on the more expensive exchange
4. Repay 1,000,500 USDC to Aave
5. Keep the profit

If the price difference is too small to cover the 0.05% premium plus gas, the transaction simply reverts. The arbitrageur risks nothing beyond the gas cost of a failed transaction.

Before flash loans, this kind of arbitrage required substantial capital. Flash loans democratized it --- anyone with the technical skill to write a smart contract can compete.

### Collateral Swap

You have \$100,000 of ETH as collateral on Aave, backing a \$50,000 USDC loan. You want to switch your collateral to WBTC --- perhaps because you are bearish on ETH. Without flash loans, you would need to:

1. Find \$50,000 to repay the loan (you might not have it)
2. Repay the USDC debt
3. Withdraw ETH
4. Swap ETH for WBTC
5. Supply WBTC
6. Re-borrow USDC

With flash loans, this becomes a single atomic transaction:

1. Flash loan \$50,000 USDC
2. Repay your Aave debt
3. Withdraw your ETH collateral
4. Swap ETH for WBTC on a DEX
5. Supply WBTC as new collateral on Aave
6. Borrow \$50,000 USDC against the new collateral
7. Repay the flash loan (\$50,025 USDC)

One transaction. No capital needed. No moment where your position is exposed.

### Self-Liquidation

Your health factor is approaching 1.0 and you want to unwind your position gracefully. If you wait and get liquidated by a bot, you lose the 5-10% liquidation bonus. With a flash loan, you can liquidate yourself at a cost of just 0.05%:

1. Flash loan enough of the debt asset to repay yourself
2. Repay your Aave debt
3. Withdraw your freed collateral
4. Swap enough collateral to cover the flash loan + premium
5. Repay the flash loan
6. Keep the remaining collateral

**The savings are dramatic.** On a \$100,000 debt position with ETH collateral and a 5% liquidation bonus, a normal liquidation costs you ~\$5,000. Self-liquidation via flash loan costs ~\$50. That is a 99% reduction.

### Leveraged Positions (Looping)

Build a leveraged long ETH position in a single transaction:

1. Start with 10 ETH (~\$20,000)
2. Flash loan 90 ETH
3. Supply all 100 ETH to Aave
4. Borrow 80 ETH worth of USDC (80% LTV)
5. Swap USDC for ~80 ETH
6. Use 80 ETH + premium to repay the flash loan
7. You now have 100 ETH collateral and ~80 ETH of USDC debt: ~5x leverage

Without flash loans, you would need to loop supply-borrow-swap-supply many times, each iteration adding a little more leverage. Flash loans collapse this into one transaction.

---

## 4. Two Flash Loan Functions

Aave V3 provides two entry points, optimized for different needs.

### `flashLoanSimple()` --- The Lightweight Option

Borrow a single asset. Lower gas cost, simpler interface. Best for straightforward arbitrage or self-liquidation.

### `flashLoan()` --- The Full-Featured Option

Borrow multiple assets in a single call. Supports debt modes (see below). Higher gas cost, but necessary for complex multi-asset operations.

| Feature | `flashLoanSimple` | `flashLoan` |
|---------|-------------------|-------------|
| Assets | 1 | Multiple |
| Debt modes | No | Yes (0, 1, 2) |
| `onBehalfOf` | No | Yes |
| Gas cost | Lower | Higher |
| Premium on debt mode | N/A | None (interest instead) |

**Rule of thumb:** Use `flashLoanSimple` when borrowing a single asset with intent to repay. Use `flashLoan` when borrowing multiple assets or when you want to keep the borrowed funds as debt.

---

## 5. The Receiver Contract

To use a flash loan, you deploy a smart contract that implements a callback interface. Aave sends the funds to your contract, calls your callback, and then verifies repayment. Your contract must:

1. Receive the borrowed funds
2. Execute your custom logic (arbitrage, swap, liquidation, etc.)
3. Ensure it holds enough to repay (amount + premium)
4. Approve the Pool to pull the repayment
5. Return `true`

The interface for the simple version:

```solidity
interface IFlashLoanSimpleReceiver {
    function executeOperation(
        address asset,
        uint256 amount,
        uint256 premium,
        address initiator,
        bytes calldata params
    ) external returns (bool);

    function ADDRESSES_PROVIDER() external view returns (IPoolAddressesProvider);
    function POOL() external view returns (IPool);
}
```

The `params` field is an opaque byte array --- you can encode anything into it (swap routes, target addresses, strategy parameters) and decode it in your callback.

The multi-asset version (`IFlashLoanReceiver`) is identical except the parameters are arrays: `address[] assets`, `uint256[] amounts`, `uint256[] premiums`.

### The Execution Flow

Here is what happens inside the protocol when you call `flashLoanSimple`:

1. The Pool validates the reserve is active and flash loans are enabled
2. The premium is calculated: `amount x 0.05%`
3. The Pool transfers the requested amount from the aToken contract to your receiver
4. The Pool calls your `executeOperation` callback
5. Your contract runs its logic and approves the Pool for repayment
6. The Pool pulls `amount + premium` from your contract via `safeTransferFrom`
7. If step 6 fails (insufficient balance or no approval), the entire transaction reverts

The critical invariant: the `safeTransferFrom` at the end. If your contract cannot repay, the transfer fails, the transaction reverts, and the funds never left. This is the mechanism that makes flash loans risk-free for the protocol.

---

## 6. Flash Loan Modes: Borrow Without Repaying

The full `flashLoan()` function (not the simple version) supports a feature that transforms flash loans from a temporary tool into a position-building mechanism: **debt modes**.

Each borrowed asset has an associated mode that determines what happens after the callback:

### Mode 0: Classic Flash Loan (Repay)

The borrower must repay the full amount plus premium within the transaction. This is the standard behavior, identical to `flashLoanSimple`.

### Mode 1: Keep as Stable-Rate Debt

The borrower does not repay the flash loan. Instead, a stable-rate debt position is opened on their behalf. The borrowed amount becomes a regular Aave loan that accrues interest over time.

Requirements:
- The `onBehalfOf` address must have sufficient collateral
- If `onBehalfOf` is not the caller, credit delegation must be approved
- The reserve must support stable borrowing

### Mode 2: Keep as Variable-Rate Debt

Same as Mode 1, but with a variable interest rate. This is the most commonly used debt mode.

### The Economic Implications

Modes 1 and 2 fundamentally change what a flash loan is. Instead of "borrow and repay instantly," it becomes "get funds immediately, open a leveraged position atomically."

The classic looping strategy with Mode 2:

1. Flash loan 100 ETH (Mode 2 --- will become variable-rate debt)
2. Supply all 100 ETH as collateral to Aave
3. The callback ends. Mode 2 kicks in: a 100 ETH variable-rate debt is created
4. You now have 100 ETH collateral and 100 ETH debt (plus your original 10 ETH)
5. Net: 110 ETH collateral, 100 ETH debt = ~11x leverage on your 10 ETH

**No premium is charged on Mode 1 or Mode 2 flash loans.** The borrower pays interest on the resulting debt position instead. This makes economic sense: charging a one-time premium on top of ongoing interest would double-charge the borrower.

You can even mix modes in a single call. Flash loan ETH (Mode 0, must repay) and USDC (Mode 2, keep as debt) in the same transaction. Each asset follows its own rules.

---

## 7. Security: Why This Is Safe

Flash loans sound dangerous, but they are among the safest features in the protocol.

**The atomic guarantee** is absolute. If the receiver contract cannot repay, the transfer reverts, which reverts the entire transaction. There is no partial state. The protocol cannot lose funds through a flash loan --- the blockchain enforces this.

**Reentrancy protection** prevents the callback from exploiting intermediate states. During the callback, funds have been transferred out but not yet returned. Aave V3 uses reentrancy guards to block the receiver from calling back into sensitive Pool functions during this window.

**Validation checks** ensure the reserve is active, not paused, and has flash loans enabled. Governance can disable flash loans per-asset if needed.

The one caveat: flash loans can be used as **tools** in attacks on other protocols. A flash loan from Aave can provide capital for price manipulation on a vulnerable DEX or governance attack on a poorly designed DAO. But this is not a risk to Aave --- the funds always return. The risk lies with protocols that do not account for the existence of flash loans in their security models.

---

## Key Takeaways

1. **Flash loans let you borrow any amount with zero collateral**, repaying in the same transaction. If repayment fails, the loan never happened. This is possible because of blockchain atomicity.

2. **The cost is minimal**: 0.05% premium, split between liquidity providers and the treasury. Governance can adjust this.

3. **Four major use cases** dominate: arbitrage (exploit price differences), collateral swaps (restructure positions atomically), self-liquidation (save 99% vs. the liquidation penalty), and leveraged looping (build leveraged positions in one transaction).

4. **`flashLoanSimple` vs. `flashLoan`**: Use the simple version for single-asset, repay-immediately scenarios. Use the full version for multi-asset operations or when you want to keep borrowed funds as debt.

5. **Debt modes (1 and 2)** turn flash loans into a position-building tool. No premium is charged --- the borrower pays interest on the resulting debt instead.

6. **Flash loans are risk-free for the protocol.** The `safeTransferFrom` repayment check and blockchain atomicity guarantee that funds either return or the transaction never happened.

7. **Flash loans democratize access to capital.** Operations that once required millions in starting capital can now be executed by anyone with the technical ability to write a smart contract.
