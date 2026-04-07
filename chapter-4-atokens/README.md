# Chapter 4: aTokens --- Interest-Bearing Tokens

In the previous chapter, we saw how Aave V3 uses indexes and scaled balances to track interest accrual efficiently. Now we look at the layer that makes this system usable: **aTokens**.

aTokens are the ERC-20 tokens you receive when you supply assets to Aave. They are the user-facing representation of your deposit, and they are one of the most important contracts in the entire protocol.

---

## What Are aTokens?

When you supply 1000 USDC to Aave V3, you receive 1000 aUSDC in return. This aUSDC is an ERC-20 token that lives in your wallet. But unlike a normal ERC-20, your aUSDC balance **increases over time** as interest accrues. You don't need to claim anything, stake anything, or interact with the protocol at all. Your balance simply goes up.

Every reserve in Aave V3 has a corresponding aToken:

| Underlying Asset | aToken   |
|-----------------|----------|
| USDC            | aUSDC    |
| WETH            | aWETH    |
| DAI             | aDAI     |
| WBTC            | aWBTC    |

aTokens maintain a 1:1 value relationship with their underlying asset. If you have 1050 aUSDC, you can redeem it for 1050 USDC (assuming sufficient liquidity). The number of aTokens you hold represents the exact amount of underlying you are entitled to.

This is a deliberate design choice. It makes aTokens intuitive: 1 aUSDC always equals 1 USDC in value. The quantity changes to reflect interest, not the price.

---

## The Rebasing Mechanism

aTokens are **rebasing tokens**. This means the `balanceOf()` function does not return a simple stored value. Instead, it performs a computation every time it is called.

Here is the core insight: the aToken contract inherits from a standard ERC-20 but **overrides `balanceOf()`** to multiply the stored (scaled) balance by the current liquidity index.

```solidity
function balanceOf(address user) public view override returns (uint256) {
    return super.balanceOf(user).rayMul(
        POOL.getReserveNormalizedIncome(_underlyingAsset)
    );
}
```

Let's break this down:

- `super.balanceOf(user)` returns the **scaled balance** --- the raw value stored in the ERC-20's internal `_balances` mapping. This is the user's deposit divided by the liquidity index at the time they deposited.
- `POOL.getReserveNormalizedIncome(_underlyingAsset)` returns the **current liquidity index**, freshly computed to include interest accrued since the last on-chain update.
- `rayMul` multiplies these two values using ray math (27-decimal precision).

The result is the user's **actual balance** --- their original deposit plus all accrued interest, computed on the fly.

### `getReserveNormalizedIncome`

This function is critical because it provides the "live" liquidity index without requiring a state-changing transaction:

```solidity
function getReserveNormalizedIncome(
    address asset
) external view override returns (uint256) {
    DataTypes.ReserveData storage reserve = _reserves[asset];

    uint40 timestamp = reserve.lastUpdateTimestamp;
    if (timestamp == block.timestamp) {
        return reserve.liquidityIndex;
    }

    // Compute index growth since last update
    uint256 cumulated = MathUtils.calculateLinearInterest(
        reserve.currentLiquidityRate,
        timestamp
    );
    return cumulated.rayMul(reserve.liquidityIndex);
}
```

This is a `view` function --- it reads the stored index and rate, then projects forward to the current timestamp. It does not write to storage. This means calling `balanceOf()` on an aToken is free (no gas cost for off-chain calls) and always returns the up-to-date balance.

### What "Rebasing" Means in Practice

If Alice holds 1000 scaled aUSDC and the liquidity index grows from `1.05` to `1.06` over an hour:

- At the start of the hour: `balanceOf(Alice) = 1000 * 1.05 = 1050`
- At the end of the hour: `balanceOf(Alice) = 1000 * 1.06 = 1060`

No transfer event was emitted. No transaction occurred. Alice's balance simply reads differently because the underlying index changed. This is the rebase: the token's reported supply and user balances shift continuously without any on-chain state change per user.

---

## Key Functions in AToken.sol

### `balanceOf(user)`

As shown above, returns `scaledBalance * liquidityIndex`. This is the actual amount of underlying the user is entitled to.

```solidity
function balanceOf(address user) public view override returns (uint256) {
    return super.balanceOf(user).rayMul(
        POOL.getReserveNormalizedIncome(_underlyingAsset)
    );
}
```

### `totalSupply()`

Returns the total actual supply of the aToken --- the sum of all users' actual balances:

```solidity
function totalSupply() public view override returns (uint256) {
    uint256 currentSupplyScaled = super.totalSupply();

    if (currentSupplyScaled == 0) {
        return 0;
    }

    return currentSupplyScaled.rayMul(
        POOL.getReserveNormalizedIncome(_underlyingAsset)
    );
}
```

Same pattern: take the stored scaled total supply and multiply by the current liquidity index.

### `scaledBalanceOf(user)`

Returns the raw stored balance without any index multiplication. This is the "principal-equivalent" value --- what the user's deposit would be worth if the index were exactly 1.0.

```solidity
function scaledBalanceOf(address user) external view override returns (uint256) {
    return super.balanceOf(user);
}
```

This function is used internally and by other protocols that need to work with the underlying scaled values rather than the rebased amounts.

### `scaledTotalSupply()`

Returns the raw total supply without index multiplication:

```solidity
function scaledTotalSupply() public view override returns (uint256) {
    return super.totalSupply();
}
```

### Quick Reference

| Function              | Returns                       | Uses Index? |
|-----------------------|-------------------------------|-------------|
| `balanceOf(user)`     | Actual balance with interest  | Yes         |
| `totalSupply()`       | Total actual supply           | Yes         |
| `scaledBalanceOf(user)` | Raw stored (scaled) balance | No          |
| `scaledTotalSupply()` | Raw stored total supply       | No          |

---

## Minting and Burning

aTokens are not freely mintable. Only the Pool contract can mint or burn them, and it does so as part of supply/withdraw operations.

### Minting (on Supply)

When a user supplies assets to Aave, the Pool contract calls `aToken.mint()`:

```solidity
function mint(
    address caller,
    address onBehalfOf,
    uint256 amount,
    uint256 index
) external override onlyPool returns (bool) {
    return _mintScaled(caller, onBehalfOf, amount, index);
}
```

The `_mintScaled()` function (inherited from `ScaledBalanceTokenBase`) computes the scaled amount and mints it:

```solidity
function _mintScaled(
    address caller,
    address onBehalfOf,
    uint256 amount,
    uint256 index
) internal returns (bool) {
    uint256 amountScaled = amount.rayDiv(index);
    require(amountScaled != 0, Errors.INVALID_MINT_AMOUNT);

    uint256 scaledBalance = super.balanceOf(onBehalfOf);
    uint256 balanceIncrease = scaledBalance.rayMul(index)
        - scaledBalance.rayMul(_userState[onBehalfOf].additionalData);

    _userState[onBehalfOf].additionalData = index.toUint128();

    _mint(onBehalfOf, amountScaled.toUint128());

    uint256 amountToMint = amount + balanceIncrease;
    emit Transfer(address(0), onBehalfOf, amountToMint);
    emit Mint(caller, onBehalfOf, amountToMint, balanceIncrease, index);

    return scaledBalance == 0;
}
```

Key details:

1. **The minted amount is in scaled units**: `amount.rayDiv(index)`. If you deposit 1000 USDC when the index is 1.05, the protocol mints approximately 952.38 scaled aTokens.

2. **`balanceIncrease` tracks accrued interest**: The function computes how much interest the user has earned since their last interaction. This is emitted in the `Transfer` event for off-chain tracking. The `additionalData` field stores the index at the user's last mint/burn, enabling this calculation.

3. **The `Transfer` event reports the actual (non-scaled) amount**: Even though scaled units are stored, events report amounts in underlying terms. This keeps block explorers and indexers showing correct values.

4. **Returns `true` if this is the user's first supply**: This flag is used by the Pool to know whether to enable the asset as collateral for the user.

### Burning (on Withdraw)

When a user withdraws, the Pool calls `aToken.burn()`:

```solidity
function burn(
    address from,
    address receiverOfUnderlying,
    uint256 amount,
    uint256 index
) external override onlyPool {
    _burnScaled(from, receiverOfUnderlying, amount, index);

    if (receiverOfUnderlying != address(this)) {
        IERC20(_underlyingAsset).safeTransfer(receiverOfUnderlying, amount);
    }
}
```

The `_burnScaled()` function mirrors `_mintScaled()`:

```solidity
function _burnScaled(
    address user,
    address target,
    uint256 amount,
    uint256 index
) internal {
    uint256 amountScaled = amount.rayDiv(index);
    require(amountScaled != 0, Errors.INVALID_BURN_AMOUNT);

    uint256 scaledBalance = super.balanceOf(user);
    uint256 balanceIncrease = scaledBalance.rayMul(index)
        - scaledBalance.rayMul(_userState[user].additionalData);

    _userState[user].additionalData = index.toUint128();

    _burn(user, amountScaled.toUint128());

    uint256 amountToBurn = amount + balanceIncrease;
    // ... emit events
}
```

After burning the scaled tokens, the `burn()` function transfers the actual underlying tokens to the user via `safeTransfer`. The aToken contract itself holds the underlying tokens --- it is the vault.

### The Lifecycle

```
Supply Flow:
  User sends 1000 USDC to aToken contract
  Pool mints ~952 scaled aTokens to user (if index = 1.05)
  User's balanceOf() returns 1000 aUSDC

Withdraw Flow:
  Pool burns ~909 scaled aTokens from user (if index = 1.10)
  aToken transfers 1000 USDC to user
  User's aToken balance decreases by 1000
```

---

## Transfers

aTokens are transferable ERC-20 tokens. You can send your aUSDC to another address, and the recipient will begin earning interest on that position.

However, aToken transfers are not simple ERC-20 transfers. The `transfer()` function includes additional logic:

```solidity
function _transfer(
    address from,
    address to,
    uint128 amount,
    bool validate
) internal override {
    uint256 index = POOL.getReserveNormalizedIncome(_underlyingAsset);

    uint256 fromBalanceBefore = super.balanceOf(from).rayMul(index);
    uint256 toBalanceBefore = super.balanceOf(to).rayMul(index);

    super._transfer(from, to, amount.rayDiv(index).toUint128());

    if (validate) {
        POOL.finalizeTransfer(
            _underlyingAsset,
            from,
            to,
            amount,
            fromBalanceBefore,
            toBalanceBefore
        );
    }
}
```

Key points:

1. **Transfers move scaled amounts**: The actual transfer operates on scaled units. If you transfer 100 aUSDC when the index is 1.05, approximately 95.24 scaled tokens move.

2. **Health factor validation**: The `POOL.finalizeTransfer()` call checks that the sender still has a healthy position after the transfer. If transferring aTokens would drop the sender's health factor below 1.0 (making them liquidatable), the transfer reverts. You cannot transfer away collateral that is actively supporting a borrow.

3. **Recipient starts earning immediately**: The transferred scaled tokens work the same way for the recipient as they did for the sender. The recipient's `balanceOf()` will reflect the current index, meaning they earn interest from the moment of transfer.

### Implications for DeFi Composability

Because aTokens are standard ERC-20s (with rebasing behavior), they can be:

- Held in multisig wallets
- Used as collateral in other protocols
- Sent to DAOs or treasury contracts
- Listed on DEXs (though rebasing behavior complicates AMM accounting)

The health factor check on transfer is a critical safety mechanism. Without it, a borrower could simply transfer their collateral aTokens to another wallet, leaving unbacked debt in the protocol.

---

## aTokens vs Compound's cTokens

Both Aave and Compound solve the same problem --- representing interest-bearing deposits --- but they use different approaches.

### Compound's cToken Model

In Compound, when you deposit 1000 USDC, you receive cUSDC tokens at an **exchange rate**. If the exchange rate is 0.02, you get 50,000 cUSDC. Over time, the exchange rate increases. Your 50,000 cUSDC might later be redeemable for 1050 USDC because the exchange rate grew to 0.021.

```
Deposit:  cTokens = underlying / exchangeRate
Redeem:   underlying = cTokens * exchangeRate
```

Your cToken **balance stays constant**. The value per token increases.

### Aave's aToken Model

In Aave, when you deposit 1000 USDC, you receive 1000 aUSDC (approximately --- adjusted by the current index). Over time, your aUSDC **balance increases** to 1050 as interest accrues. Each aUSDC is always worth approximately 1 USDC.

```
Deposit:  scaledTokens = underlying / liquidityIndex
Balance:  underlying = scaledTokens * liquidityIndex
```

Your aToken **balance increases over time**. The value per token stays at ~1.

### Comparison

| Property                   | Aave aTokens              | Compound cTokens           |
|---------------------------|---------------------------|----------------------------|
| Balance changes over time? | Yes (rebasing)            | No (fixed quantity)        |
| Value per token changes?   | No (~1:1 with underlying) | Yes (exchange rate grows)  |
| Internal accounting        | Scaled balance / index    | Fixed balance * exchange rate |
| Intuitive for users?       | Yes (balance = value)     | Less so (need exchange rate) |
| ERC-20 compatibility       | Rebasing complicates some integrations | Standard behavior |
| Transfer events for interest | No (silent rebase)      | No (silent rate change)    |

### Which Is Better?

Neither approach is strictly superior. Aave's model is more intuitive for end users --- seeing your balance go up is satisfying and easy to understand. Compound's model is simpler for smart contract integrations because the token balance is stable and the exchange rate is an explicit function call.

The trade-off is that aTokens' rebasing behavior can cause issues with protocols that cache ERC-20 balances or assume balances only change on transfers. Any protocol integrating aTokens must account for the fact that `balanceOf()` can return a different value between two calls even without any transfer.

---

## The Treasury Mint

As covered briefly in Chapter 3, the Aave protocol charges a **reserve factor** on each reserve --- a percentage of all interest paid by borrowers that goes to the Aave treasury. This revenue is implemented through the aToken minting mechanism.

### How It Works

When `updateState()` runs and indexes are updated, the protocol computes how much total interest has been generated by borrowers since the last update. The reserve factor percentage of that interest is then recorded as aTokens owed to the treasury.

From `ReserveLogic._accrueToTreasury()`:

```solidity
uint256 totalDebtAccrued = currTotalVariableDebt - prevTotalVariableDebt;

uint256 amountToMint = totalDebtAccrued.percentMul(reserveCache.reserveFactor);

if (amountToMint != 0) {
    reserve.accruedToTreasury += amountToMint.rayDiv(
        reserve.liquidityIndex
    ).toUint128();
}
```

The treasury accrual is stored in **scaled units** (divided by the liquidity index), just like user balances. This means the treasury's share also earns interest over time --- the treasury is effectively a depositor whose position grows with the index.

### When Treasury Tokens Are Actually Minted

The `accruedToTreasury` value accumulates over time but the actual aToken minting happens when `mintToTreasury()` is called (typically by the PoolConfigurator or during certain admin operations):

```solidity
function mintToTreasury(
    DataTypes.ReserveData storage reserve,
    DataTypes.ReserveCache memory reserveCache
) internal {
    uint256 accruedToTreasury = reserve.accruedToTreasury;

    if (accruedToTreasury != 0) {
        reserve.accruedToTreasury = 0;
        uint256 normalizedIncome = reserveCache.nextLiquidityIndex;
        uint256 amountToMint = accruedToTreasury.rayMul(normalizedIncome);
        IAToken(reserveCache.aTokenAddress).mintToTreasury(
            amountToMint,
            normalizedIncome
        );
    }
}
```

This is a gas optimization. Rather than minting aTokens to the treasury on every single interaction, the protocol accumulates the amount and mints in batches.

### Numerical Example

Suppose:
- Total variable debt: 1,000,000 USDC
- Variable borrow rate: 5% APR
- Reserve factor: 20%
- Time since last update: 1 day

Interest accrued by borrowers in one day:
```
1,000,000 * 0.05 * (1/365) = 136.99 USDC
```

Treasury's share:
```
136.99 * 0.20 = 27.40 USDC (in scaled units, divided by current liquidityIndex)
```

This 27.40 USDC worth of scaled aTokens is added to `accruedToTreasury`. When eventually minted, the treasury receives aTokens that it can hold (earning further interest) or redeem for the underlying USDC.

---

## The AToken Contract Hierarchy

To understand the full picture, here is how the aToken contract is structured in the inheritance chain:

```
IERC20
  |
ERC20 (OpenZeppelin-based, modified)
  |
ScaledBalanceTokenBase
  |     - Stores scaled balances
  |     - Implements _mintScaled() and _burnScaled()
  |     - Provides scaledBalanceOf() and scaledTotalSupply()
  |
IncentivizedERC20
  |     - Hooks into Aave's reward distribution system
  |     - Notifies the incentives controller on mint/burn/transfer
  |
AToken
        - Overrides balanceOf() and totalSupply() with index multiplication
        - Implements mint(), burn(), and transfer logic
        - Holds the underlying asset (acts as the vault)
        - Handles treasury minting
        - Validates transfers via Pool.finalizeTransfer()
```

The `IncentivizedERC20` layer is worth noting: every time aTokens are minted, burned, or transferred, the contract notifies an external incentives controller. This is how Aave distributes liquidity mining rewards. The hooks add minimal gas overhead but enable the entire rewards system.

---

## Practical Implications

### For Users

- Your aToken balance reflects your deposit plus all accrued interest at all times
- You can transfer aTokens freely (subject to health factor constraints)
- You do not need to "claim" interest --- it is already in your balance
- Holding aTokens in a cold wallet still earns interest

### For Developers Integrating aTokens

- **Do not cache `balanceOf()` results** --- they change between blocks (and even within a block if the reserve is updated)
- **Use `scaledBalanceOf()` for consistent snapshots** --- the scaled balance only changes on mint/burn/transfer
- **Account for rebasing in AMM integrations** --- simple x*y=k AMMs will miscount aToken balances over time
- **Transfer events do not reflect interest** --- the ERC-20 `Transfer` event is only emitted on actual mint/burn/transfer, not on interest accrual

### For Protocol Governance

- The reserve factor determines how much revenue the protocol extracts from each reserve
- Higher reserve factors mean more revenue but lower effective supply rates for depositors
- Treasury aTokens can be redeemed or deployed according to governance decisions

---

## Summary

aTokens are the user-facing layer of Aave V3's interest accrual system. They wrap the scaled balance and index mechanics from Chapter 3 into an ERC-20 interface that is intuitive for users and composable with the broader DeFi ecosystem.

**Key takeaways:**

- **aTokens are rebasing ERC-20s**: `balanceOf()` returns `scaledBalance * liquidityIndex`, making your balance grow over time without transactions.
- **1 aToken is always worth approximately 1 underlying token**: Unlike Compound's cTokens where the exchange rate changes, aTokens maintain a 1:1 value peg. The quantity changes instead.
- **Minting and burning operate in scaled units**: The Pool mints `amount / index` scaled tokens on supply and burns `amount / index` on withdraw.
- **Transfers include health factor validation**: You cannot transfer aTokens if doing so would make your position liquidatable.
- **Treasury revenue is implemented as aToken minting**: A portion of borrower interest is periodically minted as aTokens to the treasury address.
- **The aToken contract holds the underlying assets**: It serves as the vault. On withdrawal, it transfers underlying tokens directly to the user.

In the next chapter, we examine the other side of the equation: **debt tokens**, which use the same scaled balance pattern to track what borrowers owe.
