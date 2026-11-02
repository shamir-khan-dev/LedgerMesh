import pytest
from src.core.models import Account, AccountType, Entry, EntryDirection, Transaction
from src.concurrency.repository import LedgerRepository
from src.concurrency.executor import (
    LedgerExecutor,
    OptimisticLockConflictError,
    InsufficientFundsError,
)

@pytest.mark.anyio
async def test_successful_transaction_updates_balance_and_increments_version():
    repo = LedgerRepository()
    cash = await repo.create_account("Cash Account", "1001", AccountType.ASSET, initial_balance=10000)
    rev = await repo.create_account("Revenue Account", "4001", AccountType.REVENUE, initial_balance=0)

    executor = LedgerExecutor(repo)

    tx = Transaction(
        reference_id="tx_occ_001",
        description="Sale #1",
        entries=[
            Entry(account_id=cash.id, direction=EntryDirection.DEBIT, amount=2500), # +$25.00
            Entry(account_id=rev.id, direction=EntryDirection.CREDIT, amount=2500), # +$25.00
        ]
    )

    posted_tx = await executor.execute_transaction(tx)
    assert posted_tx.status.value == "POSTED"
    assert posted_tx.hash is not None
    assert posted_tx.prev_hash is not None

    updated_cash = await repo.get_account(cash.id)
    updated_rev = await repo.get_account(rev.id)

    assert updated_cash.balance == 12500
    assert updated_cash.version == 2

    assert updated_rev.balance == 2500
    assert updated_rev.version == 2

@pytest.mark.anyio
async def test_occ_conflict_detection_when_version_is_stale():
    repo = LedgerRepository()
    acc_a = await repo.create_account("Account A", "1001", AccountType.ASSET, initial_balance=5000)

    # Simulate atomic update with expected_version = 1
    updated = await repo.update_account_balance_cas(acc_a.id, delta=1000, expected_version=1)
    assert updated is True

    # Attempting another update with expected_version = 1 must fail (version is now 2)
    with pytest.raises(OptimisticLockConflictError):
        await repo.update_account_balance_cas(acc_a.id, delta=1000, expected_version=1)

@pytest.mark.anyio
async def test_overdraft_protection_for_assets():
    repo = LedgerRepository()
    cash = await repo.create_account("Cash Account", "1001", AccountType.ASSET, initial_balance=1000)
    pay = await repo.create_account("Accounts Payable", "2001", AccountType.LIABILITY, initial_balance=5000)

    executor = LedgerExecutor(repo, allow_overdraft=False)

    tx = Transaction(
        reference_id="tx_overdraft",
        description="Attempt to spend $20 with only $10 balance",
        entries=[
            Entry(account_id=cash.id, direction=EntryDirection.CREDIT, amount=2000), # -$20.00
            Entry(account_id=pay.id, direction=EntryDirection.DEBIT, amount=2000),   # -$20.00
        ]
    )

    with pytest.raises(InsufficientFundsError):
        await executor.execute_transaction(tx)

    # Verify balance was NOT mutated
    account = await repo.get_account(cash.id)
    assert account.balance == 1000
    assert account.version == 1
