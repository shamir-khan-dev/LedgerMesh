import asyncio
from datetime import datetime, timezone
from typing import Dict, List, Optional
from src.core.models import Account, AccountType, Transaction, Entry
from src.audit.hasher import GENESIS_HASH

class OptimisticLockConflictError(Exception):
    """Raised when an atomic CAS operation fails due to stale row version."""
    pass

class AccountNotFoundError(Exception):
    """Raised when an account does not exist in the ledger."""
    pass


class LedgerRepository:
    """
    High-performance, ACID-compliant ledger storage repository supporting
    atomic Compare-And-Swap (CAS) optimistic concurrency control and cryptographic head tracking.
    """

    def __init__(self):
        self._accounts: Dict[str, Account] = {}
        self._transactions: Dict[str, Transaction] = {}
        self._entries: Dict[str, Entry] = {}
        self._tx_order: List[str] = []
        self._head_tx_hash: str = GENESIS_HASH
        self._lock = asyncio.Lock()

    async def create_account(
        self,
        name: str,
        code: str,
        account_type: AccountType,
        currency: str = "USD",
        initial_balance: int = 0,
    ) -> Account:
        """Creates a new ledger account."""
        async with self._lock:
            account = Account(
                name=name,
                code=code,
                account_type=account_type,
                currency=currency,
                balance=initial_balance,
                version=1,
            )
            self._accounts[account.id] = account
            return account.model_copy()

    async def get_account(self, account_id: str) -> Optional[Account]:
        """Retrieves an account by its ID."""
        async with self._lock:
            acc = self._accounts.get(account_id)
            return acc.model_copy() if acc else None

    async def list_accounts(self) -> List[Account]:
        """Returns all registered ledger accounts."""
        async with self._lock:
            return [acc.model_copy() for acc in self._accounts.values()]

    async def update_account_balance_cas(
        self, account_id: str, delta: int, expected_version: int
    ) -> bool:
        """
        Atomically updates account balance using Optimistic Concurrency Control (Compare-And-Swap).
        Only updates if version in memory matches expected_version.
        """
        async with self._lock:
            account = self._accounts.get(account_id)
            if not account:
                raise AccountNotFoundError(f"Account '{account_id}' not found")

            if account.version != expected_version:
                raise OptimisticLockConflictError(
                    f"OCC Conflict on account '{account_id}': expected version {expected_version}, current {account.version}"
                )

            # Atomic mutation
            account.balance += delta
            account.version += 1
            account.updated_at = datetime.now(timezone.utc)
            return True

    async def apply_batch_cas(
        self, updates: List[tuple[str, int, int]]
    ) -> None:
        """
        Atomically applies multiple CAS updates in a single critical section.
        updates = [(account_id, delta, expected_version), ...]
        If ANY version check fails, none of the updates are committed.
        """
        async with self._lock:
            # 1. Validation phase (check all versions and existence)
            for acc_id, _, exp_version in updates:
                acc = self._accounts.get(acc_id)
                if not acc:
                    raise AccountNotFoundError(f"Account '{acc_id}' not found")
                if acc.version != exp_version:
                    raise OptimisticLockConflictError(
                        f"OCC Conflict on account '{acc_id}': expected version {exp_version}, current {acc.version}"
                    )

            # 2. Execution phase (apply all delta mutations atomically)
            now = datetime.now(timezone.utc)
            for acc_id, delta, _ in updates:
                acc = self._accounts[acc_id]
                acc.balance += delta
                acc.version += 1
                acc.updated_at = now

    async def get_head_transaction_hash(self) -> str:
        """Returns the cryptographic SHA-256 hash of the most recently posted transaction."""
        async with self._lock:
            return self._head_tx_hash

    async def save_transaction(self, tx: Transaction) -> Transaction:
        """Appends a posted transaction and entries, advancing the audit hash head."""
        async with self._lock:
            tx_copy = tx.model_copy()
            self._transactions[tx_copy.id] = tx_copy
            self._tx_order.append(tx_copy.id)
            for entry in tx_copy.entries:
                self._entries[entry.id] = entry.model_copy()
            if tx_copy.hash:
                self._head_tx_hash = tx_copy.hash
            return tx_copy

    async def get_transaction(self, tx_id: str) -> Optional[Transaction]:
        """Fetches a transaction by ID."""
        async with self._lock:
            tx = self._transactions.get(tx_id)
            return tx.model_copy() if tx else None

    async def list_transactions(self, limit: int = 100, offset: int = 0) -> List[Transaction]:
        """Returns ordered ledger transactions for journal audit."""
        async with self._lock:
            ordered_ids = self._tx_order[offset : offset + limit]
            return [self._transactions[tx_id].model_copy() for tx_id in ordered_ids]
