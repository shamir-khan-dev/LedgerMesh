from datetime import timedelta
from typing import Dict, List, Set, Tuple
from src.core.models import AccountType, EntryDirection, Transaction
from src.core.invariants import calculate_balance_delta
from src.concurrency.repository import LedgerRepository
from src.reconciliation.models import (
    BankStatementTransaction,
    MatchStatus,
    MatchedPair,
    ReconciliationReport,
)

class ReconciliationEngine:
    """
    Institutional multi-pass bank statement reconciliation and tie-out engine.
    Matches internal ledger journal entries with external clearing statements,
    detecting timing variances, unrecorded fees, and calculating net discrepancies down to the cent.
    """

    def __init__(self, repository: LedgerRepository):
        self._repo = repository

    async def reconcile_account(
        self,
        account_id: str,
        statement_id: str,
        external_transactions: List[BankStatementTransaction],
        date_tolerance_days: int = 2,
    ) -> ReconciliationReport:
        target_account = await self._repo.get_account(account_id)
        if not target_account:
            raise ValueError(f"Account '{account_id}' does not exist")

        all_txs = await self._repo.list_transactions(limit=10000)

        # Filter internal transactions that affect this specific account
        # Map: tx_id -> (Transaction, signed_amount)
        internal_candidates: Dict[str, Tuple[Transaction, int]] = {}
        for tx in all_txs:
            for entry in tx.entries:
                if entry.account_id == account_id:
                    delta = calculate_balance_delta(
                        target_account.account_type, entry.direction, entry.amount
                    )
                    internal_candidates[tx.id] = (tx, delta)
                    break

        matched_pairs: List[MatchedPair] = []
        matched_ext_ids: Set[str] = set()
        matched_int_tx_ids: Set[str] = set()

        # Pass 1: Exact Reference Match
        for ext in external_transactions:
            if ext.external_id in matched_ext_ids or not ext.reference:
                continue

            for int_tx_id, (int_tx, int_amount) in internal_candidates.items():
                if int_tx_id in matched_int_tx_ids:
                    continue

                if ext.reference == int_tx.reference_id and ext.amount == int_amount:
                    matched_pairs.append(
                        MatchedPair(
                            match_status=MatchStatus.EXACT_MATCH,
                            internal_tx_id=int_tx.id,
                            external_id=ext.external_id,
                            amount=ext.amount,
                            confidence_score=1.0,
                            notes=f"Exact match on reference '{ext.reference}'",
                        )
                    )
                    matched_ext_ids.add(ext.external_id)
                    matched_int_tx_ids.add(int_tx_id)
                    break

        # Pass 2: Amount & Date Window Matching
        for ext in external_transactions:
            if ext.external_id in matched_ext_ids:
                continue

            for int_tx_id, (int_tx, int_amount) in internal_candidates.items():
                if int_tx_id in matched_int_tx_ids:
                    continue

                if ext.amount == int_amount:
                    days_diff = abs((ext.date - int_tx.timestamp).days)
                    if days_diff <= date_tolerance_days:
                        matched_pairs.append(
                            MatchedPair(
                                match_status=MatchStatus.WINDOW_MATCH,
                                internal_tx_id=int_tx.id,
                                external_id=ext.external_id,
                                amount=ext.amount,
                                confidence_score=0.9,
                                notes=f"Fuzzy window match within {days_diff} days",
                            )
                        )
                        matched_ext_ids.add(ext.external_id)
                        matched_int_tx_ids.add(int_tx_id)
                        break

        # Pass 3: Residual Analysis - Unmatched External
        unmatched_bank_count = 0
        for ext in external_transactions:
            if ext.external_id not in matched_ext_ids:
                unmatched_bank_count += 1
                matched_pairs.append(
                    MatchedPair(
                        match_status=MatchStatus.UNMATCHED_EXTERNAL,
                        external_id=ext.external_id,
                        amount=ext.amount,
                        confidence_score=0.0,
                        notes=f"Unmatched bank transaction: {ext.description}",
                    )
                )

        # Pass 4: Residual Analysis - Unmatched Internal
        unmatched_internal_count = 0
        for int_tx_id, (int_tx, int_amount) in internal_candidates.items():
            if int_tx_id not in matched_int_tx_ids:
                unmatched_internal_count += 1
                matched_pairs.append(
                    MatchedPair(
                        match_status=MatchStatus.UNMATCHED_INTERNAL,
                        internal_tx_id=int_tx.id,
                        amount=int_amount,
                        confidence_score=0.0,
                        notes=f"Unmatched internal transaction: {int_tx.description}",
                    )
                )

        total_bank_volume = sum(ext.amount for ext in external_transactions)
        total_internal_volume = sum(amount for _, amount in internal_candidates.values())
        net_discrepancy = total_bank_volume - total_internal_volume

        return ReconciliationReport(
            statement_id=statement_id,
            account_id=account_id,
            total_bank_transactions=len(external_transactions),
            total_internal_transactions=len(internal_candidates),
            matched_count=len(matched_ext_ids),
            unmatched_bank_count=unmatched_bank_count,
            unmatched_internal_count=unmatched_internal_count,
            total_bank_volume=total_bank_volume,
            total_internal_volume=total_internal_volume,
            net_discrepancy=net_discrepancy,
            matches=matched_pairs,
        )
