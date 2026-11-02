import pytest
import asyncio
from src.idempotency.store import (
    InMemoryIdempotencyStore,
    IdempotencyRecord,
    IdempotencyStatus,
    IdempotencyConflictError,
    IdempotencyPayloadMismatchError,
)

@pytest.mark.anyio
async def test_acquire_and_complete_idempotency():
    store = InMemoryIdempotencyStore()
    key = "idem_key_001"
    payload = {"reference_id": "tx_abc", "amount": 5000}

    # 1. Acquire in-flight lock
    acquired = await store.acquire_lock(key, payload)
    assert acquired is True

    # 2. Complete with cached response
    response_data = {"id": "tx_123", "status": "POSTED"}
    await store.complete_request(key, status_code=201, response_body=response_data)

    # 3. Retrieve completed record
    record = await store.get_record(key)
    assert record is not None
    assert record.status == IdempotencyStatus.COMPLETED
    assert record.status_code == 201
    assert record.response_body == response_data

@pytest.mark.anyio
async def test_concurrent_duplicate_in_flight_rejected():
    store = InMemoryIdempotencyStore()
    key = "idem_key_002"
    payload = {"reference_id": "tx_xyz", "amount": 1000}

    # First caller acquires lock
    acquired_1 = await store.acquire_lock(key, payload)
    assert acquired_1 is True

    # Second concurrent caller with same key while in-flight must raise IdempotencyConflictError
    with pytest.raises(IdempotencyConflictError) as exc_info:
        await store.acquire_lock(key, payload)
    assert "currently in-flight" in str(exc_info.value)

@pytest.mark.anyio
async def test_payload_mismatch_rejected():
    store = InMemoryIdempotencyStore()
    key = "idem_key_003"
    original_payload = {"reference_id": "tx_original", "amount": 2000}
    altered_payload = {"reference_id": "tx_original", "amount": 99999} # Different amount!

    # Complete first request
    await store.acquire_lock(key, original_payload)
    await store.complete_request(key, status_code=201, response_body={"success": True})

    # Second request with same key but altered payload must raise IdempotencyPayloadMismatchError
    with pytest.raises(IdempotencyPayloadMismatchError) as exc_info:
        await store.acquire_lock(key, altered_payload)
    assert "Payload does not match original request" in str(exc_info.value)
