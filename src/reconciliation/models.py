import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field

class MatchStatus(str, Enum):
    EXACT_MATCH = "EXACT_MATCH"
    WINDOW_MATCH = "WINDOW_MATCH"
    UNMATCHED_INTERNAL = "UNMATCHED_INTERNAL"
    UNMATCHED_EXTERNAL = "UNMATCHED_EXTERNAL"

class BankStatementTransaction(BaseModel):
    external_id: str = Field(default_factory=lambda: f"stmt_tx_{uuid.uuid4().hex[:8]}")
    date: datetime
    amount: int  # in cents; positive for deposit/credit, negative for withdrawal/debit
    description: str
    reference: Optional[str] = None

class MatchedPair(BaseModel):
    match_status: MatchStatus
    internal_tx_id: Optional[str] = None
    external_id: Optional[str] = None
    amount: int
    confidence_score: float = 1.0
    notes: Optional[str] = None

class ReconciliationReport(BaseModel):
    statement_id: str
    account_id: str
    reconciled_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    total_bank_transactions: int
    total_internal_transactions: int
    matched_count: int
    unmatched_bank_count: int
    unmatched_internal_count: int
    total_bank_volume: int
    total_internal_volume: int
    net_discrepancy: int  # in cents; $0.00 is balanced
    matches: List[MatchedPair]
