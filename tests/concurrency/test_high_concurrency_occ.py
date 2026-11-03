import pytest
import asyncio
from src.core.models import AccountType, Entry, EntryDirection, Transaction
from src.concurrency.repository import LedgerRepository
from src.concurrency.executor import LedgerExecutor
from src.audit.hasher import verify_audit_chain

@pytest.mark.anyio
async def test_high_concurrency_race_condition_simulation():
    """
    Stress-tests Optimistic Concurrency Control (OCC) under intense concurrent load.
    50 concurrent coroutines simultaneously attempt to credit and debit the SAME hot account.
    Asserts:
    1. Zero lost updates (balance matches exact mathematical expected sum).
    2. Version matches total number of mutations.
    3. Entire cryptographic SHA-256 audit chain remains unbroken and 100% verified.
    """
    repo = LedgerRepository()
    executor = LedgerExecutor(repo, allow_overdraft=True)

    # Initial setup
    initial_cash = 100000  # $1,000.00
    cash_account = await repo.create_account("Hot Cash Pool", "1000", AccountType.ASSET, initial_balance=initial_cash)
    rev_account = await repo.create_account("Settlement Revenue", "4000", AccountType.REVENUE, initial_balance=0)

    concurrency_count = 50
    amount_per_tx = 1000  # $10.00 each

    async def worker(tx_num: int):
        tx = Transaction(
            reference_id=f"tx_concurrent_{tx_num:03d}",
            description=f"Concurrent clearing batch {tx_num}",
            entries=[
                Entry(account_id=cash_account.id, direction=EntryDirection.DEBIT, amount=amount_per_tx),
                Entry(account_id=rev_account.id, direction=EntryDirection.CREDIT, amount=amount_per_tx),
            ],
        )
        return await executor.execute_transaction(tx, max_retries=15, base_delay=0.005)

    # Launch all 50 concurrent transactions simultaneously using asyncio.gather
    tasks = [worker(i) for i in range(concurrency_count)]
    results = await asyncio.gather(*tasks)

    assert len(results) == concurrency_count

    # 1. Verify balances have zero lost updates
    final_cash = await repo.get_account(cash_account.id)
    final_rev = await repo.get_account(rev_account.id)

    expected_cash_balance = initial_cash + (concurrency_count * amount_per_tx)
    expected_rev_balance = concurrency_count * amount_per_tx

    assert final_cash.balance == expected_cash_balance
    assert final_rev.balance == expected_rev_balance

    # 2. Verify account OCC version was incremented exactly 50 times
    assert final_cash.version == 1 + concurrency_count
    assert final_rev.version == 1 + concurrency_count

    # 3. Verify cryptographic audit chain integrity
    all_txs = await repo.list_transactions(limit=100)
    assert len(all_txs) == concurrency_count

    audit_result = verify_audit_chain(all_txs)
    assert audit_result.is_valid is True
    assert audit_result.total_verified == concurrency_count
    assert audit_result.tampered_transaction_id is None

