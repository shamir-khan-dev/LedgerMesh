import pytest
from datetime import datetime, timezone
from src.core.models import Transaction, Entry, EntryDirection
from src.audit.hasher import (
    GENESIS_HASH,
    calculate_transaction_hash,
    verify_audit_chain,
    AuditVerificationResult,
    compute_merkle_root,
)

def create_sample_tx(ref: str, amount: int, prev_hash: str = GENESIS_HASH) -> Transaction:
    tx = Transaction(
        reference_id=ref,
        description=f"Transaction {ref}",
        timestamp=datetime(2026, 11, 2, 12, 0, 0, tzinfo=timezone.utc),
        entries=[
            Entry(account_id="acc_cash", direction=EntryDirection.DEBIT, amount=amount),
            Entry(account_id="acc_rev", direction=EntryDirection.CREDIT, amount=amount),
        ],
        prev_hash=prev_hash,
    )
    tx.hash = calculate_transaction_hash(tx, prev_hash)
    return tx

def test_deterministic_transaction_hashing():
    """Hashing the same transaction inputs must produce identical SHA-256 digests."""
    tx1 = create_sample_tx("tx_001", 10000, GENESIS_HASH)
    tx2 = create_sample_tx("tx_001", 10000, GENESIS_HASH)

    assert tx1.hash == tx2.hash
    assert len(tx1.hash) == 64

def test_audit_chain_verification_valid():
    """A sequentially chained list of transactions must verify cleanly."""
    tx1 = create_sample_tx("tx_001", 10000, GENESIS_HASH)
    tx2 = create_sample_tx("tx_002", 25000, tx1.hash)
    tx3 = create_sample_tx("tx_003", 5000, tx2.hash)

    chain = [tx1, tx2, tx3]
    result: AuditVerificationResult = verify_audit_chain(chain)

    assert result.is_valid is True
    assert result.total_verified == 3
    assert result.tampered_transaction_id is None

def test_audit_chain_detects_tampered_entry_amount():
    """If an attacker mutates an amount in the database, the hash verification must fail."""
    tx1 = create_sample_tx("tx_001", 10000, GENESIS_HASH)
    tx2 = create_sample_tx("tx_002", 25000, tx1.hash)
    tx3 = create_sample_tx("tx_003", 5000, tx2.hash)

    # Malicious tampering: change tx2 amount from 25000 ($250.00) to 99999 ($999.99)
    tx2.entries[0].amount = 99999

    chain = [tx1, tx2, tx3]
    result: AuditVerificationResult = verify_audit_chain(chain)

    assert result.is_valid is False
    assert result.tampered_transaction_id == tx2.id
    assert "Hash mismatch at transaction" in result.error_message

def test_audit_chain_detects_broken_prev_hash_link():
    """If a transaction is deleted or reordered, the chain pointer must break."""
    tx1 = create_sample_tx("tx_001", 10000, GENESIS_HASH)
    tx2 = create_sample_tx("tx_002", 25000, tx1.hash)
    tx3 = create_sample_tx("tx_003", 5000, tx2.hash)

    # Maliciously re-point tx3 to tx1 directly, dropping tx2
    tx3.prev_hash = tx1.hash
    # recalculate tx3 hash to match its new prev_hash
    tx3.hash = calculate_transaction_hash(tx3, tx1.hash)

    # But we present [tx1, tx2, tx3]
    result = verify_audit_chain([tx1, tx2, tx3])
    assert result.is_valid is False
    assert result.tampered_transaction_id == tx3.id
    assert "Previous hash link broken" in result.error_message

def test_merkle_root_computation():
    """Merkle root aggregates transactions into a cryptographic root digest."""
    tx1 = create_sample_tx("tx_001", 10000, GENESIS_HASH)
    tx2 = create_sample_tx("tx_002", 25000, tx1.hash)

    merkle_root = compute_merkle_root([tx1.hash, tx2.hash])
    assert len(merkle_root) == 64
    assert isinstance(merkle_root, str)
