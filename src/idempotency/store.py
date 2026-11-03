import asyncio
import hashlib
import json
from datetime import datetime, timezone, timedelta
from enum import Enum
from typing import Any, Dict, Optional
from pydantic import BaseModel, Field

class IdempotencyStatus(str, Enum):
    IN_FLIGHT = "IN_FLIGHT"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"

class IdempotencyConflictError(Exception):
    """Raised when a request with the same idempotency key is already in-flight."""
    pass

class IdempotencyPayloadMismatchError(Exception):
    """Raised when an idempotency key is reused with a different request payload."""
    pass

class IdempotencyRecord(BaseModel):
    key: str
    payload_hash: str
    status: IdempotencyStatus
    status_code: Optional[int] = None
    response_body: Optional[Any] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    expires_at: Optional[datetime] = None


def hash_payload(payload: Any) -> str:
    """Computes a deterministic SHA-256 fingerprint for request payloads."""
    if payload is None:
        raw_bytes = b""
    elif isinstance(payload, bytes):
        raw_bytes = payload
    elif isinstance(payload, str):
        raw_bytes = payload.encode("utf-8")
    else:
        raw_bytes = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw_bytes).hexdigest()


class InMemoryIdempotencyStore:
    """
    Thread-safe, high-performance in-memory idempotency store with TTL expiration
    and atomic check-and-set locking semantics.
    """

    def __init__(self):
        self._records: Dict[str, IdempotencyRecord] = {}
        self._lock = asyncio.Lock()

    async def acquire_lock(self, key: str, payload: Any, ttl_seconds: int = 3600) -> bool:
        """
        Attempts to acquire the idempotency execution lock.
        - Returns True if lock acquired (new request execution starts).
        - Returns False if request was already completed previously (cached result available).
        - Raises IdempotencyConflictError if request is currently in-flight.
        - Raises IdempotencyPayloadMismatchError if payload does not match original request.
        """
        payload_hash = hash_payload(payload)

        async with self._lock:
            existing = self._records.get(key)
            if existing:
                # Check for payload tampering or accidental key reuse
                if existing.payload_hash != payload_hash:
                    raise IdempotencyPayloadMismatchError(
                        f"Payload does not match original request for idempotency key '{key}'"
                    )

                if existing.status == IdempotencyStatus.IN_FLIGHT:
                    raise IdempotencyConflictError(
                        f"Request with idempotency key '{key}' is currently in-flight"
                    )

                if existing.status == IdempotencyStatus.COMPLETED:
                    return False  # Already completed; use cached response

            # Record is new or previously failed - acquire lock
            now = datetime.now(timezone.utc)
            self._records[key] = IdempotencyRecord(
                key=key,
                payload_hash=payload_hash,
                status=IdempotencyStatus.IN_FLIGHT,
                created_at=now,
                expires_at=now + timedelta(seconds=ttl_seconds),
            )
            return True

    async def complete_request(
        self, key: str, status_code: int, response_body: Any
    ) -> None:
        """Atomically transitions in-flight record to COMPLETED and stores response payload."""
        async with self._lock:
            record = self._records.get(key)
            if record:
                record.status = IdempotencyStatus.COMPLETED
                record.status_code = status_code
                record.response_body = response_body

    async def fail_request(self, key: str, error_message: Optional[str] = None) -> None:
        """Marks in-flight record as FAILED or clears lock so client can retry."""
        async with self._lock:
            if key in self._records:
                self._records[key].status = IdempotencyStatus.FAILED

    async def get_record(self, key: str) -> Optional[IdempotencyRecord]:
        """Fetches the idempotency record for a given key, if present and non-expired."""
        async with self._lock:
            record = self._records.get(key)
            if record and record.expires_at:
                if datetime.now(timezone.utc) > record.expires_at:
                    del self._records[key]
                    return None
            return record

