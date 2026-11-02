import pytest
from src.core.models import (
    Account,
    AccountType,
    Entry,
    EntryDirection,
    Transaction,
    TransactionStatus,
)
from src.core.invariants import (
    validate_transaction_invariants,
    calculate_balance_delta,
    UnbalancedTransactionError,
    InvalidEntryAmountError,
    InvalidTransactionStructureError,
)

def test_balanced_transaction_validation_success():
    """A valid transaction with matching debits and credits must pass validation."""
    tx = Transaction(
        reference_id="tx_test_001",
        description="Customer subscription payment",
        entries=[
            Entry(
                account_id="acc_cash",
                direction=EntryDirection.DEBIT,
                amount=5000, # $50.00 in cents
                description="Cash received",
            ),
            Entry(
                account_id="acc_revenue",
                direction=EntryDirection.CREDIT,
                amount=5000,
                description="Subscription revenue",
            ),
        ]
    )
    # Should not raise any error
    validate_transaction_invariants(tx)

def test_unbalanced_transaction_rejected():
    """If sum(debits) != sum(credits), UnbalancedTransactionError must be raised."""
    tx = Transaction(
        reference_id="tx_test_002",
        description="Corrupt transaction",
        entries=[
            Entry(
                account_id="acc_cash",
                direction=EntryDirection.DEBIT,
                amount=5000,
            ),
            Entry(
                account_id="acc_revenue",
                direction=EntryDirection.CREDIT,
                amount=4500, # Missing $5.00
            ),
        ]
    )
    with pytest.raises(UnbalancedTransactionError) as exc_info:
        validate_transaction_invariants(tx)
    assert "Debits (5000) != Credits (4500)" in str(exc_info.value)

def test_zero_or_negative_amount_rejected():
    """Entry amounts must strictly be positive integers (>0)."""
    with pytest.raises(InvalidEntryAmountError):
        Entry(
            account_id="acc_cash",
            direction=EntryDirection.DEBIT,
            amount=0,
        )

    with pytest.raises(InvalidEntryAmountError):
        Entry(
            account_id="acc_cash",
            direction=EntryDirection.DEBIT,
            amount=-1000,
        )

def test_transaction_must_have_at_least_two_entries():
    """A transaction must have at least one debit and one credit."""
    tx = Transaction(
        reference_id="tx_single",
        description="Single entry",
        entries=[
            Entry(
                account_id="acc_cash",
                direction=EntryDirection.DEBIT,
                amount=5000,
            )
        ]
    )
    with pytest.raises(InvalidTransactionStructureError):
        validate_transaction_invariants(tx)

def test_normal_balance_calculations():
    """
    Test standard accounting 5-element normal balance equation:
    - ASSET & EXPENSE: Debit increases balance, Credit decreases balance.
    - LIABILITY, EQUITY & REVENUE: Credit increases balance, Debit decreases balance.
    """
    # Asset
    assert calculate_balance_delta(AccountType.ASSET, EntryDirection.DEBIT, 1000) == 1000
    assert calculate_balance_delta(AccountType.ASSET, EntryDirection.CREDIT, 1000) == -1000

    # Expense
    assert calculate_balance_delta(AccountType.EXPENSE, EntryDirection.DEBIT, 500) == 500
    assert calculate_balance_delta(AccountType.EXPENSE, EntryDirection.CREDIT, 500) == -500

    # Liability
    assert calculate_balance_delta(AccountType.LIABILITY, EntryDirection.DEBIT, 1000) == -1000
    assert calculate_balance_delta(AccountType.LIABILITY, EntryDirection.CREDIT, 1000) == 1000

    # Equity
    assert calculate_balance_delta(AccountType.EQUITY, EntryDirection.DEBIT, 2000) == -2000
    assert calculate_balance_delta(AccountType.EQUITY, EntryDirection.CREDIT, 2000) == 2000

    # Revenue
    assert calculate_balance_delta(AccountType.REVENUE, EntryDirection.DEBIT, 3000) == -3000
    assert calculate_balance_delta(AccountType.REVENUE, EntryDirection.CREDIT, 3000) == 3000
