import pytest
from datetime import datetime, timezone, timedelta
from src.core.models import AccountType, Entry, EntryDirection, Transaction
from src.concurrency.repository import LedgerRepository
from src.concurrency.executor import LedgerExecutor
from src.reconciliation.parser import parse_csv_statement, parse_json_statement
from src.reconciliation.engine import ReconciliationEngine, MatchStatus

@pytest.mark.anyio
async def test_csv_and_json_statement_parsing():
    csv_data = """Date,Amount,Description,Reference
2026-11-01,150.00,Stripe Payout Ref#1001,REF-1001
2026-11-02,-25.50,Monthly Wire Fee,FEE-99
"""
    parsed = parse_csv_statement(csv_data)
    assert len(parsed) == 2
    assert parsed[0].amount == 15000  # $150.00 in cents
    assert parsed[0].reference == "REF-1001"
    assert parsed[1].amount == -2550  # -$25.50 in cents

    json_data = [
        {"external_id": "b1", "date": "2026-11-01", "amount": 5000, "description": "Deposit", "reference": "REF-50"}
    ]
    parsed_json = parse_json_statement(json_data)
    assert len(parsed_json) == 1
    assert parsed_json[0].amount == 5000

@pytest.mark.anyio
async def test_reconciliation_exact_and_discrepancy_detection():
    repo = LedgerRepository()
    executor = LedgerExecutor(repo)

    bank_acc = await repo.create_account("Operating Checking", "1010", AccountType.ASSET, initial_balance=0)
    rev_acc = await repo.create_account("Client Sales", "4010", AccountType.REVENUE, initial_balance=0)

    # Post 2 internal transactions
    tx1 = Transaction(
        reference_id="INV-001",
        description="Invoice 001 Payment",
        entries=[
            Entry(account_id=bank_acc.id, direction=EntryDirection.DEBIT, amount=10000), # +$100.00
            Entry(account_id=rev_acc.id, direction=EntryDirection.CREDIT, amount=10000),
        ]
    )
    tx2 = Transaction(
        reference_id="INV-002",
        description="Invoice 002 Payment",
        entries=[
            Entry(account_id=bank_acc.id, direction=EntryDirection.DEBIT, amount=5000), # +$50.00
            Entry(account_id=rev_acc.id, direction=EntryDirection.CREDIT, amount=5000),
        ]
    )
    await executor.execute_transaction(tx1)
    await executor.execute_transaction(tx2)

    # Bank statement has:
    # 1. Matching INV-001 ($100.00)
    # 2. Matching INV-002 ($50.00)
    # 3. Unmatched bank monthly maintenance fee of -$15.00
    csv_bank_feed = """Date,Amount,Description,Reference
2026-11-01,100.00,Deposit INV-001,INV-001
2026-11-02,50.00,Deposit INV-002,INV-002
2026-11-02,-15.00,Service Charge,SVC-FEE
"""
    bank_txs = parse_csv_statement(csv_bank_feed)

    engine = ReconciliationEngine(repo)
    report = await engine.reconcile_account(
        account_id=bank_acc.id,
        statement_id="stmt_nov_2026",
        external_transactions=bank_txs,
    )

    assert report.total_bank_transactions == 3
    assert report.total_internal_transactions == 2
    assert report.matched_count == 2
    assert report.unmatched_bank_count == 1
    assert report.unmatched_internal_count == 0

    # Net discrepancy should be -$15.00 (-1500 cents) representing the unexpected bank fee
    assert report.net_discrepancy == -1500

    # Verify matched items have confidence 1.0
    matched_refs = [m.notes for m in report.matches if m.match_status == MatchStatus.EXACT_MATCH]
    assert len(matched_refs) == 2
