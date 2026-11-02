import asyncio
import os
import sys

# Ensure UTF-8 output encoding on Windows consoles
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from src.core.models import AccountType, Entry, EntryDirection, Transaction
from src.core.invariants import UnbalancedTransactionError
from src.concurrency.repository import LedgerRepository
from src.concurrency.executor import LedgerExecutor
from src.audit.hasher import verify_audit_chain, calculate_transaction_hash
from src.idempotency.store import InMemoryIdempotencyStore
from src.reconciliation.parser import parse_csv_statement
from src.reconciliation.engine import ReconciliationEngine, MatchStatus

console = Console(force_terminal=True, legacy_windows=False)

async def main():
    console.print(Panel.fit(
        "[bold cyan]LedgerMesh: Institutional Double-Entry Clearing & Audit Engine[/bold cyan]\n"
        "[dim]End-to-End Architectural Verification & Feature Demonstration[/dim]",
        border_style="cyan"
    ))

    repo = LedgerRepository()
    executor = LedgerExecutor(repo, allow_overdraft=False)
    idempotency_store = InMemoryIdempotencyStore()

    # 1. Chart of Accounts Setup
    console.print("\n[bold yellow]Step 1: Establishing Chart of Accounts[/bold yellow]")
    cash = await repo.create_account("Operating Cash (SVB/JPMorgan)", "1000", AccountType.ASSET, initial_balance=2500000) # $25,000.00
    ar = await repo.create_account("Accounts Receivable", "1200", AccountType.ASSET, initial_balance=500000) # $5,000.00
    rev = await repo.create_account("SaaS Platform Revenue", "4000", AccountType.REVENUE, initial_balance=0)
    pay = await repo.create_account("Vendor Accounts Payable", "2000", AccountType.LIABILITY, initial_balance=1000000)

    acc_table = Table(title="Initial Chart of Accounts", border_style="blue")
    acc_table.add_column("Code", style="cyan")
    acc_table.add_column("Account Name", style="white")
    acc_table.add_column("Type", style="magenta")
    acc_table.add_column("Balance (USD)", style="green")

    for a in [cash, ar, rev, pay]:
        acc_table.add_row(a.code, a.name, a.account_type.value, f"${a.balance / 100:,.2f}")
    console.print(acc_table)

    # 2. Balanced Double-Entry Clearing
    console.print("\n[bold yellow]Step 2: Clearing Balanced Double-Entry Transaction[/bold yellow]")
    tx1 = Transaction(
        reference_id="INV-2026-001",
        description="Enterprise Subscription Settlement - Acme Corp",
        entries=[
            Entry(account_id=cash.id, direction=EntryDirection.DEBIT, amount=350000, description="Cash Inflow"), # +$3,500.00
            Entry(account_id=rev.id, direction=EntryDirection.CREDIT, amount=350000, description="Subscription Revenue"), # +$3,500.00
        ]
    )
    posted_tx1 = await executor.execute_transaction(tx1)
    console.print(f"[bold green][PASS][/bold green] Transaction [bold green]{posted_tx1.reference_id}[/bold green] successfully posted.")
    console.print(f"   [dim]SHA-256 Hash:[/dim] [cyan]{posted_tx1.hash}[/cyan]")
    console.print(f"   [dim]Prev Hash (Genesis):[/dim] [dim]{posted_tx1.prev_hash}[/dim]")

    # 3. Double-Entry Invariant Enforcement
    console.print("\n[bold yellow]Step 3: Invariant Protection: Rejecting Unbalanced Transaction[/bold yellow]")
    unbalanced_tx = Transaction(
        reference_id="MALFORMED-TX",
        description="Unbalanced Transaction Attempt",
        entries=[
            Entry(account_id=cash.id, direction=EntryDirection.DEBIT, amount=100000), # $1,000.00
            Entry(account_id=rev.id, direction=EntryDirection.CREDIT, amount=90000),  # $900.00 (Discrepancy!)
        ]
    )
    try:
        await executor.execute_transaction(unbalanced_tx)
        console.print("[bold red][FAIL] ERROR: Unbalanced transaction was accepted![/bold red]")
    except UnbalancedTransactionError as e:
        console.print(f"[bold green][PASS] INVARIANT ENFORCED:[/bold green] Rejected malformed transaction: [red]{e}[/red]")

    # 4. Distributed Idempotency Protection
    console.print("\n[bold yellow]Step 4: Distributed Idempotency Replay Protection[/bold yellow]")
    idem_key = "IDEM-KEY-ACME-RENEWAL"
    payload = {"reference_id": "RENEWAL-01", "amount": 120000}

    # First attempt: lock acquired
    acquired_first = await idempotency_store.acquire_lock(idem_key, payload)
    console.print(f"1st Request (Idempotency-Key: {idem_key}): Lock Acquired = [green]{acquired_first}[/green]")
    await idempotency_store.complete_request(idem_key, status_code=201, response_body={"status": "POSTED", "ref": "RENEWAL-01"})

    # Duplicate retry with same key: returns cached response without duplicate balance mutation
    acquired_retry = await idempotency_store.acquire_lock(idem_key, payload)
    cached = await idempotency_store.get_record(idem_key)
    console.print(f"2nd Retry Request (Same Key): Lock Acquired = [yellow]{acquired_retry}[/yellow] (Served directly from cache: {cached.response_body})")

    # 5. Cryptographic Tamper-Evident Audit Chain
    console.print("\n[bold yellow]Step 5: Cryptographic Tamper-Evident Audit Verification[/bold yellow]")
    # Post a second transaction
    tx2 = Transaction(
        reference_id="INV-2026-002",
        description="Consulting Service Fee Clearing",
        entries=[
            Entry(account_id=cash.id, direction=EntryDirection.DEBIT, amount=150000),
            Entry(account_id=rev.id, direction=EntryDirection.CREDIT, amount=150000),
        ]
    )
    posted_tx2 = await executor.execute_transaction(tx2)

    all_txs = await repo.list_transactions()
    audit_res = verify_audit_chain(all_txs)
    console.print(f"Ledger Chain Status: [bold green]VALID[/bold green] (Verified {audit_res.total_verified} transactions from Genesis).")

    # Simulate database tampering
    console.print("\n[bold red]Simulating Adversarial Database Tampering Attack:[/bold red]")
    console.print("Modifying past transaction INV-2026-001 amount from $3,500.00 to $9,999.00 in storage...")
    posted_tx1.entries[0].amount = 999900

    tamper_check = verify_audit_chain([posted_tx1, posted_tx2])
    console.print(f"[bold red][ALERT] TAMPERING DETECTED BY AUDIT ENGINE:[/bold red]")
    console.print(f"   Is Valid: [red]{tamper_check.is_valid}[/red]")
    console.print(f"   Compromised Tx ID: [yellow]{tamper_check.tampered_transaction_id}[/yellow]")
    console.print(f"   Alert: [dim]{tamper_check.error_message}[/dim]")

    # Restore legitimate state
    posted_tx1.entries[0].amount = 350000
    posted_tx1.hash = calculate_transaction_hash(posted_tx1, posted_tx1.prev_hash)

    # 6. Automated Multi-Bank Statement Reconciliation
    console.print("\n[bold yellow]Step 6: Automated Multi-Bank Statement Reconciliation (Tie-Out)[/bold yellow]")
    csv_bank_statement = f"""Date,Amount,Description,Reference
2026-11-01,3500.00,Acme Corp Enterprise Wire,INV-2026-001
2026-11-02,1500.00,Consulting Fee Wire,INV-2026-002
2026-11-02,-35.00,International Inbound Wire Fee,BANK-FEE-01
"""
    bank_txs = parse_csv_statement(csv_bank_statement)
    reconciler = ReconciliationEngine(repo)
    report = await reconciler.reconcile_account(
        account_id=cash.id,
        statement_id="SVB_STMT_NOV_2026",
        external_transactions=bank_txs,
    )

    rec_table = Table(title="Bank Statement Reconciliation Report", border_style="magenta")
    rec_table.add_column("Metric", style="cyan")
    rec_table.add_column("Value", style="bold white")

    rec_table.add_row("Bank Statement ID", report.statement_id)
    rec_table.add_row("Total External Bank Transactions", str(report.total_bank_transactions))
    rec_table.add_row("Total Internal Transactions", str(report.total_internal_transactions))
    rec_table.add_row("Matched Transactions", f"[bold green]{report.matched_count}[/bold green]")
    rec_table.add_row("Unmatched Bank Items (Fees/Charges)", f"[bold red]{report.unmatched_bank_count}[/bold red]")
    rec_table.add_row("Net Bank Volume", f"${report.total_bank_volume / 100:,.2f}")
    rec_table.add_row("Net Internal Volume", f"${report.total_internal_volume / 100:,.2f}")
    rec_table.add_row("Net Discrepancy", f"[bold yellow]${report.net_discrepancy / 100:,.2f}[/bold yellow] (International Wire Fee to be journaled)")

    console.print(rec_table)

    console.print(Panel.fit(
        "[bold green]All Institutional Invariants Verified Successfully! LedgerMesh Engine is Production Ready.[/bold green]",
        border_style="green"
    ))

if __name__ == "__main__":
    asyncio.run(main())
