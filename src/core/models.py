import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator

class AccountType(str, Enum):
    ASSET = "ASSET"
    LIABILITY = "LIABILITY"
    EQUITY = "EQUITY"
    REVENUE = "REVENUE"
    EXPENSE = "EXPENSE"

class EntryDirection(str, Enum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"

class TransactionStatus(str, Enum):
    PENDING = "PENDING"
    POSTED = "POSTED"
    REJECTED = "REJECTED"

class Account(BaseModel):
    id: str = Field(default_factory=lambda: f"acc_{uuid.uuid4().hex[:12]}")
    name: str
    code: str
    account_type: AccountType
    currency: str = "USD"
    balance: int = 0  # Stored in integer minor units (e.g. cents)
    version: int = 1  # Optimistic Concurrency Control (OCC) version
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class Entry(BaseModel):
    id: str = Field(default_factory=lambda: f"ent_{uuid.uuid4().hex[:12]}")
    account_id: str
    direction: EntryDirection
    amount: int  # Must be strictly positive integer cents
    description: Optional[str] = None

    @field_validator("amount")
    @classmethod
    def validate_positive_amount(cls, v: int) -> int:
        from src.core.invariants import InvalidEntryAmountError
        if not isinstance(v, int) or v <= 0:
            raise InvalidEntryAmountError(f"Entry amount must be a positive integer, got: {v}")
        return v

class Transaction(BaseModel):
    id: str = Field(default_factory=lambda: f"tx_{uuid.uuid4().hex[:12]}")
    reference_id: str
    description: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    entries: List[Entry]
    status: TransactionStatus = TransactionStatus.PENDING
    hash: Optional[str] = None
    prev_hash: Optional[str] = None
