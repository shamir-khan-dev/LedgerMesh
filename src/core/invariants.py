from src.core.models import AccountType, EntryDirection, Transaction

class LedgerError(Exception):
    """Base exception for all LedgerMesh business logic errors."""
    pass

class UnbalancedTransactionError(LedgerError):
    """Raised when sum(Debits) != sum(Credits)."""
    pass

class InvalidEntryAmountError(LedgerError):
    """Raised when an entry has an amount <= 0 or invalid non-integer format."""
    pass

class InvalidTransactionStructureError(LedgerError):
    """Raised when a transaction does not satisfy structural double-entry requirements."""
    pass

class InsufficientFundsError(LedgerError):
    """Raised when an account balance cannot go below zero / overdraft limit."""
    pass


def validate_transaction_invariants(tx: Transaction) -> None:
    """
    Strictly validates core double-entry accounting invariants for a transaction:
    1. A transaction must have at least two entries.
    2. A transaction must include at least one Debit and at least one Credit.
    3. The sum of Debits must exactly equal the sum of Credits ($0.00 discrepancy tolerance).
    """
    if not tx.entries or len(tx.entries) < 2:
        raise InvalidTransactionStructureError(
            f"Transaction {tx.reference_id} must have at least 2 entries, got {len(tx.entries) if tx.entries else 0}"
        )

    debit_sum = 0
    credit_sum = 0
    has_debit = False
    has_credit = False

    for entry in tx.entries:
        if entry.direction == EntryDirection.DEBIT:
            debit_sum += entry.amount
            has_debit = True
        elif entry.direction == EntryDirection.CREDIT:
            credit_sum += entry.amount
            has_credit = True

    if not has_debit or not has_credit:
        raise InvalidTransactionStructureError(
            f"Transaction {tx.reference_id} must contain at least one DEBIT and one CREDIT entry"
        )

    if debit_sum != credit_sum:
        raise UnbalancedTransactionError(
            f"Double-entry invariant violated for {tx.reference_id}: Debits ({debit_sum}) != Credits ({credit_sum})"
        )


def calculate_balance_delta(
    account_type: AccountType, direction: EntryDirection, amount: int
) -> int:
    """
    Computes signed balance delta according to standard 5-element normal balances:
    - ASSETS & EXPENSES: Debit increases (+), Credit decreases (-)
    - LIABILITIES, EQUITY & REVENUE: Credit increases (+), Debit decreases (-)
    """
    if account_type in (AccountType.ASSET, AccountType.EXPENSE):
        return amount if direction == EntryDirection.DEBIT else -amount
    elif account_type in (AccountType.LIABILITY, AccountType.EQUITY, AccountType.REVENUE):
        return amount if direction == EntryDirection.CREDIT else -amount
    else:
        raise ValueError(f"Unknown account type: {account_type}")

