# Chapter 8: Flash Loans

Flash loans are one of the most novel primitives in DeFi, and Aave pioneered them. The concept is simple but powerful: borrow any amount of any asset, without any collateral, as long as you repay the full amount (plus a small fee) within the same transaction. If the repayment fails, the entire transaction reverts as if it never happened.

This is not magic. It is a consequence of how Ethereum transactions work. A transaction is atomic --- it either completes fully or reverts entirely. Flash loans exploit this property to allow uncollateralized borrowing with zero risk to the protocol.

---

## 1. What Are Flash Loans?

In traditional lending --- even in DeFi --- you must post collateral before you can borrow. Flash loans remove this requirement entirely. The protocol lends you the funds, you do whatever you want with them, and then the protocol checks that you returned the funds plus a premium. If you did not, the transaction reverts. The protocol's funds were never at risk because, from the blockchain's perspective, the loan never happened.

This unlocks operations that would otherwise require large amounts of capital:
- Arbitrage across DEXes
- Collateral swaps without unwinding positions
- Self-liquidation to avoid the liquidation penalty
- Building leveraged positions in a single transaction

Flash loans are available for any asset that has liquidity in Aave's pools. The amount you can borrow is limited only by the available liquidity in that reserve.

---

## 2. Two Flash Loan Functions

Aave V3 provides two entry points for flash loans:

### `flashLoanSimple()`

Borrow a single asset. Lower gas cost, simpler interface.

```solidity
function flashLoanSimple(
    address receiverAddress,
    address asset,
    uint256 amount,
    bytes calldata params,
    uint16 referralCode
) external;
```

### `flashLoan()`

Borrow multiple assets in a single call. More gas, but supports multi-asset operations and debt modes.

```solidity
function flashLoan(
    address receiverAddress,
    address[] calldata assets,
    uint256[] calldata amounts,
    uint256[] calldata interestRateModes,
    address onBehalfOf,
    bytes calldata params,
    uint16 referralCode
) external;
```

The key difference beyond multi-asset support is the `interestRateModes` parameter, which allows the borrower to **keep the borrowed funds** by incurring debt instead of repaying. We cover this in Section 5.

---

## 3. The Flash Loan Flow (Simple)

Here is how `flashLoanSimple` works, step by step.

### Step 1: Deploy a Receiver Contract

The borrower must deploy a contract that implements the `IFlashLoanSimpleReceiver` interface:

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

The `executeOperation` function is where the borrower defines what to do with the borrowed funds. This is the callback that Aave invokes after transferring the funds.

### Step 2: Call `flashLoanSimple`

The borrower (or any EOA/contract) calls `Pool.flashLoanSimple()`, which delegates to `FlashLoanLogic.executeFlashLoanSimple()`:

```solidity
function executeFlashLoanSimple(
    mapping(address => DataTypes.ReserveData) storage reservesData,
    DataTypes.FlashloanSimpleParams memory params
) external {
    DataTypes.ReserveData storage reserve = reservesData[params.asset];
    DataTypes.ReserveCache memory reserveCache = reserve.cache();

    reserve.updateState(reserveCache);

    // Validate the flash loan
    ValidationLogic.validateFlashloanSimple(reserveCache);

    // Calculate the premium
    uint256 totalPremium = params.amount.percentMul(params.flashLoanPremiumTotal);

    // Transfer the requested amount from the aToken to the receiver
    IAToken(reserveCache.aTokenAddress).transferUnderlyingTo(
        params.receiverAddress,
        params.amount
    );
```

At this point, the receiver contract has the borrowed funds in its balance.

### Step 3: Execute the Callback

```solidity
    // Call the receiver's executeOperation function
    require(
        IFlashLoanSimpleReceiver(params.receiverAddress).executeOperation(
            params.asset,
            params.amount,
            totalPremium,
            msg.sender,
            params.params
        ),
        Errors.INVALID_FLASHLOAN_EXECUTOR_RETURN
    );
```

The receiver contract now runs its custom logic --- arbitrage, collateral swap, liquidation, whatever. The `params` field (opaque bytes) can carry arbitrary data to guide this logic.

The receiver must:
1. Do whatever it wants with the funds
2. Ensure it holds `amount + totalPremium` of the asset at the end
3. Approve the Pool to pull the funds
4. Return `true`

### Step 4: Verify Repayment

```solidity
    // Pull the repayment (amount + premium) from the receiver
    IERC20(params.asset).safeTransferFrom(
        params.receiverAddress,
        reserveCache.aTokenAddress,
        params.amount + totalPremium
    );

    // Handle the premium
    // Part goes to liquidity providers (via the reserve), part to treasury
    if (vars.premiumToProtocol != 0) {
        // Mint aTokens to the treasury for the protocol's share
        reserve.accruedToTreasury += vars.premiumToProtocol
            .rayDiv(reserveCache.nextLiquidityIndex)
            .toUint128();
    }

    // The remainder of the premium stays in the aToken, benefiting suppliers

    // Update interest rates
    reserve.updateInterestRates(reserveCache, params.asset, totalPremium, 0);

    emit FlashLoan(
        params.receiverAddress,
        msg.sender,
        params.asset,
        params.amount,
        totalPremium,
        params.referralCode
    );
}
```

The critical invariant: after the callback, the Pool pulls `amount + premium` from the receiver via `safeTransferFrom`. If the receiver does not have sufficient balance or has not approved the transfer, the entire transaction reverts. The funds never left the protocol from the blockchain's perspective.

### A Minimal Receiver Example

```solidity
contract MyFlashLoanReceiver is IFlashLoanSimpleReceiver {
    IPoolAddressesProvider public immutable override ADDRESSES_PROVIDER;
    IPool public immutable override POOL;

    constructor(IPoolAddressesProvider provider) {
        ADDRESSES_PROVIDER = provider;
        POOL = IPool(provider.getPool());
    }

    function executeOperation(
        address asset,
        uint256 amount,
        uint256 premium,
        address initiator,
        bytes calldata params
    ) external override returns (bool) {
        // --- Custom logic goes here ---
        // You now have `amount` of `asset` in this contract.
        // Do your arbitrage, swap, liquidation, etc.

        // --- Repayment ---
        // Approve the Pool to pull amount + premium
        uint256 amountOwed = amount + premium;
        IERC20(asset).approve(address(POOL), amountOwed);

        return true;
    }

    // Entry point: initiate the flash loan
    function requestFlashLoan(address asset, uint256 amount) external {
        POOL.flashLoanSimple(
            address(this),   // receiver
            asset,           // asset to borrow
            amount,          // amount
            "",              // params (empty for this example)
            0                // referral code
        );
    }
}
```

---

## 4. Flash Loan Premium

Flash loans are not free. The borrower pays a **premium** --- a small fee calculated as a percentage of the borrowed amount.

On most Aave V3 deployments, the premium is **0.05%** (5 basis points). Borrow 1,000,000 USDC, pay back 1,000,500 USDC.

The premium is configurable by governance and stored in the Pool:

```solidity
// In Pool.sol storage
uint128 internal _flashLoanPremiumTotal;        // e.g., 5 (meaning 0.05%)
uint128 internal _flashLoanPremiumToProtocol;   // e.g., 4 (meaning 0.04%)
```

The premium is split two ways:

1. **To liquidity providers**: The majority of the premium goes to the aToken reserve. It increases the liquidity index, which means all suppliers earn a share of flash loan fees proportional to their deposit.

2. **To the protocol treasury**: A portion is redirected to the Aave treasury via `accruedToTreasury`.

For example, if `_flashLoanPremiumTotal` is 5 bps and `_flashLoanPremiumToProtocol` is 4 bps:
- Total premium on a 1,000,000 USDC loan: **500 USDC**
- Protocol's share: 500 * (4/5) = **400 USDC**
- Liquidity providers' share: 500 - 400 = **100 USDC**

The exact split is governance-configurable and varies by deployment.

Note: the premium calculation uses `percentMul`, which operates in basis points (1 bp = 0.01%):

```solidity
uint256 totalPremium = params.amount.percentMul(params.flashLoanPremiumTotal);
// For amount = 1_000_000e6 and premium = 5:
// totalPremium = 1_000_000e6 * 5 / 10000 = 500e6 (500 USDC)
```

---

## 5. Flash Loan Modes

The full `flashLoan()` function (not the simple version) supports a powerful feature: **debt modes**. Each borrowed asset has an associated `interestRateMode` that determines what happens after the callback.

```solidity
uint256[] calldata interestRateModes
```

The three modes:

### Mode 0: No Debt (Standard Flash Loan)

The borrower must repay the full amount plus premium within the transaction. This is the classic flash loan behavior, identical to `flashLoanSimple`.

### Mode 1: Incur Stable Rate Debt

The borrower does **not** repay the flash loan. Instead, a stable-rate debt position is opened on their behalf (specifically, on behalf of the `onBehalfOf` address). The borrowed amount becomes a regular Aave loan.

For this to work:
- The `onBehalfOf` address must have sufficient collateral
- The `onBehalfOf` address must have approved the borrower via `approveDelegation()` (if `onBehalfOf` is not the caller)
- The reserve must have stable borrowing enabled

### Mode 2: Incur Variable Rate Debt

Same as Mode 1, but with a variable interest rate.

### Why Debt Modes Exist

Modes 1 and 2 turn flash loans into a tool for **opening leveraged positions in a single transaction**. Here is the classic "loop" strategy:

1. Flash loan 100 ETH
2. Supply all 100 ETH as collateral to Aave
3. Borrow 80 ETH worth of USDC against the collateral
4. Use the USDC to repay the flash loan

Without flash loans, you would need to repeat supply-borrow-supply-borrow many times to build up leverage. With Mode 2, you can do it in one transaction.

The code that handles modes in `FlashLoanLogic.executeFlashLoan()`:

```solidity
for (vars.i = 0; vars.i < params.assets.length; vars.i++) {
    // ... transfer assets to receiver ...
}

// Execute the callback
require(
    IFlashLoanReceiver(params.receiverAddress).executeOperation(
        params.assets,
        params.amounts,
        vars.flashloanPremiums,
        msg.sender,
        params.params
    ),
    Errors.INVALID_FLASHLOAN_EXECUTOR_RETURN
);

for (vars.i = 0; vars.i < params.assets.length; vars.i++) {
    if (DataTypes.InterestRateMode(params.interestRateModes[vars.i]) == DataTypes.InterestRateMode.NONE) {
        // Mode 0: pull repayment from the receiver
        IERC20(params.assets[vars.i]).safeTransferFrom(
            params.receiverAddress,
            reserveCache.aTokenAddress,
            params.amounts[vars.i] + vars.flashloanPremiums[vars.i]
        );
    } else {
        // Mode 1 or 2: open a debt position instead of pulling repayment
        BorrowLogic.executeBorrow(
            // ... borrow on behalf of onBehalfOf ...
        );
    }
}
```

For Mode 0, the premium is paid in full. For Modes 1 and 2, no premium is charged --- the borrower is simply opening a regular borrow position, which will accrue interest normally.

---

## 6. Common Use Cases

### Arbitrage

The most iconic flash loan use case. If USDC/ETH is priced differently on Uniswap and SushiSwap:

1. Flash loan 1,000,000 USDC from Aave
2. Buy ETH on the cheaper exchange
3. Sell ETH on the more expensive exchange
4. Repay 1,000,500 USDC (amount + premium)
5. Keep the profit

If the price difference is not large enough to cover the premium and gas, the transaction simply reverts. No risk to the arbitrageur beyond gas costs.

### Collateral Swap

Replace one collateral type with another without unwinding your position:

1. Flash loan enough of the new collateral asset
2. Supply the new collateral to Aave
3. Withdraw your old collateral from Aave
4. Swap old collateral for the flash-loaned asset on a DEX
5. Repay the flash loan

Without flash loans, you would need to repay your debt first (requiring capital), withdraw collateral, swap, re-supply, and re-borrow. Flash loans make it atomic.

### Self-Liquidation

If your health factor is approaching 1 and you want to avoid the liquidation penalty:

1. Flash loan enough of the debt asset
2. Repay your own debt on Aave
3. Withdraw your freed collateral
4. Swap enough collateral to cover the flash loan + premium
5. Repay the flash loan
6. Keep the remaining collateral

You lose only the 0.05% flash loan premium instead of the 5-10% liquidation bonus. Significant savings.

### Leveraged Positions (Looping)

Build a leveraged long position in one transaction using Mode 2:

1. Flash loan 100 ETH
2. Supply 100 ETH to Aave (you already had 10 ETH, now have 110 ETH collateral)
3. The callback ends --- Mode 2 opens a variable-rate debt for 100 ETH
4. You now have 110 ETH collateral and 100 ETH debt: ~11x leverage

Or the more common version without debt modes:

1. Flash loan 100 USDC
2. Swap USDC for ETH on a DEX
3. Supply ETH to Aave
4. Borrow USDC against the ETH
5. Repay the flash loan with the borrowed USDC + premium

---

## 7. The Full `flashLoan()` Function

The multi-asset flash loan function follows the same pattern as `flashLoanSimple`, but with loops and mode handling.

```solidity
function executeFlashLoan(
    mapping(address => DataTypes.ReserveData) storage reservesData,
    mapping(uint256 => address) storage reservesList,
    mapping(uint8 => DataTypes.EModeCategory) storage eModeCategories,
    DataTypes.UserConfigurationMap storage userConfig,
    DataTypes.FlashloanParams memory params
) external {
    // Validate
    ValidationLogic.validateFlashloan(
        reservesData,
        params.assets,
        params.amounts
    );

    // Calculate premiums for each asset
    FlashLoanLocalVars memory vars;
    vars.flashloanPremiums = new uint256[](params.assets.length);
    vars.flashloanPremiumsToProtocol = new uint256[](params.assets.length);

    for (vars.i = 0; vars.i < params.assets.length; vars.i++) {
        vars.flashloanPremiums[vars.i] = DataTypes.InterestRateMode(
            params.interestRateModes[vars.i]
        ) == DataTypes.InterestRateMode.NONE
            ? params.amounts[vars.i].percentMul(params.flashLoanPremiumTotal)
            : 0;

        // Transfer the asset to the receiver
        IAToken(reserveCache.aTokenAddress).transferUnderlyingTo(
            params.receiverAddress,
            params.amounts[vars.i]
        );
    }
```

Key points:

- **Premiums are only charged for Mode 0.** If the borrower is incurring debt (Mode 1 or 2), the premium is zero --- they will pay interest on the debt instead.
- Each asset can have a **different mode**. You could flash loan ETH (Mode 0, must repay) and USDC (Mode 2, incur variable debt) in the same call.
- The callback uses the multi-asset `IFlashLoanReceiver` interface:

```solidity
interface IFlashLoanReceiver {
    function executeOperation(
        address[] calldata assets,
        uint256[] calldata amounts,
        uint256[] calldata premiums,
        address initiator,
        bytes calldata params
    ) external returns (bool);
}
```

After the callback, the function loops through assets again:

```solidity
    for (vars.i = 0; vars.i < params.assets.length; vars.i++) {
        if (DataTypes.InterestRateMode(params.interestRateModes[vars.i])
            == DataTypes.InterestRateMode.NONE)
        {
            // Mode 0: pull amount + premium from receiver
            DataTypes.ReserveData storage reserve = reservesData[params.assets[vars.i]];
            DataTypes.ReserveCache memory reserveCache = reserve.cache();

            IERC20(params.assets[vars.i]).safeTransferFrom(
                params.receiverAddress,
                reserveCache.aTokenAddress,
                params.amounts[vars.i] + vars.flashloanPremiums[vars.i]
            );

            // Credit premium to suppliers and treasury
            reserve.cumulateToLiquidityIndex(
                IERC20(reserveCache.aTokenAddress).totalSupply(),
                vars.flashloanPremiums[vars.i] - vars.flashloanPremiumsToProtocol[vars.i]
            );

            reserve.accruedToTreasury += vars.flashloanPremiumsToProtocol[vars.i]
                .rayDiv(reserveCache.nextLiquidityIndex)
                .toUint128();

            reserve.updateInterestRates(
                reserveCache,
                params.assets[vars.i],
                vars.flashloanPremiums[vars.i],
                0
            );
        } else {
            // Mode 1 or 2: execute a borrow on behalf of the user
            BorrowLogic.executeBorrow(
                reservesData,
                reservesList,
                eModeCategories,
                userConfig,
                DataTypes.ExecuteBorrowParams({
                    asset: params.assets[vars.i],
                    user: msg.sender,
                    onBehalfOf: params.onBehalfOf,
                    amount: params.amounts[vars.i],
                    interestRateMode: DataTypes.InterestRateMode(
                        params.interestRateModes[vars.i]
                    ),
                    referralCode: params.referralCode,
                    releaseUnderlying: false,   // already transferred
                    // ...
                })
            );
        }
    }
}
```

Note the `releaseUnderlying: false` in the borrow call. The funds were already transferred during the flash loan phase, so the borrow logic should not transfer them again. It only needs to mint debt tokens and update the user's configuration.

---

## 8. Security Considerations

Flash loans sound dangerous. How can you lend millions without collateral? The answer lies in the atomicity guarantees of Ethereum transactions.

### The Atomic Guarantee

A flash loan is not really a loan in the traditional sense. It is a temporary state change within a single transaction. If the state change is not reversed (i.e., the funds are not returned), the entire transaction reverts. From the perspective of the blockchain, it is as if the flash loan never happened.

This means flash loans cannot create bad debt. The protocol's solvency invariant --- total assets >= total liabilities --- is preserved at the end of every block, regardless of what happens during flash loan execution.

### The Repayment Check

The repayment is enforced by `safeTransferFrom`. After the callback, the Pool attempts to pull `amount + premium` from the receiver:

```solidity
IERC20(params.asset).safeTransferFrom(
    params.receiverAddress,
    reserveCache.aTokenAddress,
    params.amount + totalPremium
);
```

If the receiver does not have the funds or has not approved the transfer, `safeTransferFrom` reverts, which reverts the entire transaction. There is no way to circumvent this check.

### Reentrancy Protection

Aave V3 uses reentrancy guards to prevent the receiver callback from re-entering the Pool and exploiting intermediate states. The callback happens while the protocol is in a modified state (funds have been transferred out), so reentrancy into sensitive functions could be dangerous.

The Pool inherits from `PoolStorage` which includes a reentrancy guard check. Functions that modify state are protected so that the flash loan callback cannot call back into them in an exploitative way.

### Why Flash Loans Do Not Increase Protocol Risk

From the protocol's perspective, flash loans are risk-free:

1. **No credit risk**: The loan is repaid within the same transaction or it never happened.
2. **No liquidity risk**: The funds leave and return in the same block. No period of illiquidity.
3. **No duration risk**: There is no time period over which the borrower could default.
4. **Positive economics**: The protocol earns a premium on every successful flash loan.

The only "risk" is that flash loans can be used as tools in attacks on **other** protocols (price manipulation, governance attacks, etc.). But this is not a risk to Aave itself --- the funds are always returned to Aave's pools.

### Flash Loan Validation

Before executing the flash loan, the protocol validates that:

```solidity
function validateFlashloanSimple(
    DataTypes.ReserveCache memory reserveCache
) internal pure {
    require(
        !reserveCache.reserveConfiguration.getPaused(),
        Errors.RESERVE_PAUSED
    );
    require(
        reserveCache.reserveConfiguration.getActive(),
        Errors.RESERVE_INACTIVE
    );
    require(
        reserveCache.reserveConfiguration.getFlashLoanEnabled(),
        Errors.FLASHLOAN_DISABLED
    );
}
```

The reserve must be active, not paused, and flash loans must be enabled. Governance can disable flash loans per-asset if needed.

---

## Comparing `flashLoan` vs `flashLoanSimple`

| Feature                     | `flashLoanSimple` | `flashLoan`           |
|-----------------------------|-------------------|-----------------------|
| Number of assets            | 1                 | Multiple              |
| Debt modes                  | No                | Yes (0, 1, 2)         |
| `onBehalfOf` parameter      | No                | Yes                   |
| Gas cost                    | Lower             | Higher                |
| Receiver interface          | `IFlashLoanSimpleReceiver` | `IFlashLoanReceiver` |
| Premium on debt mode        | N/A               | None (interest instead)|

Use `flashLoanSimple` when you need a single asset and plan to repay within the transaction. Use `flashLoan` when you need multiple assets or want to incur debt.

---

## Key Takeaways

1. **Flash loans allow uncollateralized borrowing** within a single transaction. If the funds are not returned, the transaction reverts.

2. **Two interfaces exist**: `flashLoanSimple` for single-asset, no-mode flash loans, and `flashLoan` for multi-asset operations with optional debt modes.

3. **The premium is currently 0.05%**, split between liquidity providers and the treasury. It is governance-configurable.

4. **Debt modes (1 and 2)** allow the borrower to keep the flash-loaned funds by opening a regular Aave debt position. This enables single-transaction leveraged positions.

5. **Flash loans are risk-free for the protocol** due to Ethereum's atomicity guarantee. The funds either return or the transaction never happened.

6. **Common use cases** include arbitrage, collateral swaps, self-liquidation, and leveraged looping.

7. **Security relies on** the `safeTransferFrom` repayment check, reentrancy guards, and the atomic nature of Ethereum transactions.
