import asyncio
import random
from typing import Dict, List, Optional
from src.core.models import Transaction, TransactionStatus, AccountType
from src.core.invariants import (
    validate_transaction_invariants,
    calculate_balance_delta,
    InsufficientFundsError,
)
from src.audit.hasher import calculate_transaction_hash
from src.concurrency.repository import LedgerRepository, OptimisticLockConflictError, AccountNotFoundError

class LedgerExecutor:
    """
    Coordinates atomic double-entry transaction clearing with Optimistic Concurrency Control,
    exponential backoff with jitter, and cryptographic audit hash chaining.
    """

    def __init__(self, repository: LedgerRepository, allow_overdraft: bool = False):
        self._repo = repository
        self._allow_overdraft = allow_overdraft

    async def execute_transaction(
        self,
        tx: Transaction,
        max_retries: int = 5,
        base_delay: float = 0.005,
    ) -> Transaction:
        """
        Executes a financial transaction across multiple accounts with ACID isolation:
        1. Validates sum(debit) == sum(credit) invariant.
        2. Gathers current versions for all affected accounts.
        3. Enforces overdraft and positive balance constraints.
        4. Calculates SHA-256 hash linked to the ledger head hash.
        5. Atomically applies Compare-And-Swap balance updates.
        6. On version collision, retries with exponential backoff & full jitter.
        """
        # Step 1: Invariant validation
        validate_transaction_invariants(tx)

        # Retry loop for Optimistic Concurrency Control
        for attempt in range(max_retries):
            # Step 2: Fetch and verify current state of affected accounts
            account_deltas: Dict[str, int] = {}
            for entry in tx.entries:
                acc = await self._repo.get_account(entry.account_id)
                if not acc:
                    raise AccountNotFoundError(f"Account '{entry.account_id}' does not exist")

                delta = calculate_balance_delta(acc.account_type, entry.direction, entry.amount)
                account_deltas[acc.id] = account_deltas.get(acc.id, 0) + delta

            # Step 3: Overdraft checking
            cas_updates = []
            for acc_id, net_delta in account_deltas.items():
                acc = await self._repo.get_account(acc_id)
                if not acc:
                    raise AccountNotFoundError(f"Account '{acc_id}' does not exist")

                if (
                    not self._allow_overdraft
                    and acc.account_type in (AccountType.ASSET, AccountType.EXPENSE)
                    and (acc.balance + net_delta) < 0
                ):
                    raise InsufficientFundsError(
                        f"Insufficient funds in account '{acc.id}' ({acc.name}): "
                        f"balance={acc.balance}, net_delta={net_delta}"
                    )

                cas_updates.append((acc.id, net_delta, acc.version))

            # Step 4: Cryptographic Hash Linkage
            head_hash = await self._repo.get_head_transaction_hash()
            tx.prev_hash = head_hash
            tx.hash = calculate_transaction_hash(tx, head_hash)

            # Step 5: Atomic CAS Execution
            try:
                await self._repo.apply_batch_cas(cas_updates)
                # Successful commit! Save transaction and update ledger head
                tx.status = TransactionStatus.POSTED
                saved_tx = await self._repo.save_transaction(tx)
                return saved_tx
            except OptimisticLockConflictError:
                if attempt >= max_retries - 1:
                    # Retries exhausted
                    raise OptimisticLockConflictError(
                        f"Transaction {tx.reference_id} failed after {max_retries} OCC retries due to concurrent mutations"
                    )

                # Exponential backoff with jitter
                sleep_time = (base_delay * (2 ** attempt)) + random.uniform(0.001, 0.008)
                await asyncio.sleep(sleep_time)

        raise OptimisticLockConflictError(f"Transaction {tx.reference_id} failed to commit")
