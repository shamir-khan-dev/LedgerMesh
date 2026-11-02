import hashlib
import json
from typing import List, Optional
from pydantic import BaseModel
from src.core.models import Transaction

GENESIS_HASH = "0" * 64

class AuditVerificationResult(BaseModel):
    is_valid: bool
    total_verified: int
    tampered_transaction_id: Optional[str] = None
    error_message: Optional[str] = None


def calculate_transaction_hash(tx: Transaction, prev_hash: str) -> str:
    """
    Computes a deterministic, canonical SHA-256 digest of a transaction linked
    to its preceding transaction hash (prev_hash).
    """
    sorted_entries = sorted(
        [
            {
                "account_id": e.account_id,
                "direction": e.direction.value if hasattr(e.direction, "value") else str(e.direction),
                "amount": e.amount,
            }
            for e in tx.entries
        ],
        key=lambda x: (x["account_id"], x["direction"], x["amount"]),
    )

    canonical_data = {
        "prev_hash": prev_hash,
        "reference_id": tx.reference_id,
        "timestamp": tx.timestamp.isoformat(),
        "description": tx.description,
        "entries": sorted_entries,
    }

    canonical_bytes = json.dumps(canonical_data, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(canonical_bytes).hexdigest()


def verify_audit_chain(
    transactions: List[Transaction], expected_genesis: str = GENESIS_HASH
) -> AuditVerificationResult:
    """
    Traverses the chronological transaction chain from genesis to head, verifying:
    1. The genesis block links to expected_genesis.
    2. Every subsequent transaction correctly references the preceding transaction's hash.
    3. The cryptographic content of every transaction and its entries matches its SHA-256 digest.
    """
    if not transactions:
        return AuditVerificationResult(is_valid=True, total_verified=0)

    for i, tx in enumerate(transactions):
        # 1. Verify prev_hash link
        if i == 0:
            if tx.prev_hash != expected_genesis:
                return AuditVerificationResult(
                    is_valid=False,
                    total_verified=i,
                    tampered_transaction_id=tx.id,
                    error_message=f"Genesis link broken: expected {expected_genesis}, got {tx.prev_hash}",
                )
        else:
            prev_tx = transactions[i - 1]
            if tx.prev_hash != prev_tx.hash:
                return AuditVerificationResult(
                    is_valid=False,
                    total_verified=i,
                    tampered_transaction_id=tx.id,
                    error_message=(
                        f"Previous hash link broken at index {i} (tx {tx.id}): "
                        f"expected {prev_tx.hash}, got {tx.prev_hash}"
                    ),
                )

        # 2. Recalculate and verify cryptographic content hash
        recalculated_hash = calculate_transaction_hash(tx, tx.prev_hash or expected_genesis)
        if recalculated_hash != tx.hash:
            return AuditVerificationResult(
                is_valid=False,
                total_verified=i,
                tampered_transaction_id=tx.id,
                error_message=(
                    f"Hash mismatch at transaction index {i} (tx {tx.id}): "
                    f"recorded {tx.hash}, recalculated {recalculated_hash}"
                ),
            )

    return AuditVerificationResult(
        is_valid=True,
        total_verified=len(transactions),
        tampered_transaction_id=None,
        error_message=None,
    )


def compute_merkle_root(hashes: List[str]) -> str:
    """
    Computes a cryptographic Merkle Root digest over an ordered list of transaction hashes.
    Useful for external state anchoring and batch audit attestations.
    """
    if not hashes:
        return GENESIS_HASH

    current_layer = list(hashes)

    while len(current_layer) > 1:
        if len(current_layer) % 2 == 1:
            current_layer.append(current_layer[-1])  # Duplicate last element if odd

        next_layer = []
        for i in range(0, len(current_layer), 2):
            combined = (current_layer[i] + current_layer[i + 1]).encode("utf-8")
            next_layer.append(hashlib.sha256(combined).hexdigest())

        current_layer = next_layer

    return current_layer[0]
