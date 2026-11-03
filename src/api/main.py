import os
import time
from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import FastAPI, Header, HTTPException, Query, Request, Response, status
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src.core.models import (
    Account,
    AccountType,
    Entry,
    EntryDirection,
    Transaction,
    TransactionStatus,
)
from src.core.invariants import (
    UnbalancedTransactionError,
    InvalidEntryAmountError,
    InvalidTransactionStructureError,
    InsufficientFundsError,
)
from src.audit.hasher import (
    verify_audit_chain,
    compute_merkle_root,
    AuditVerificationResult,
)
from src.concurrency.repository import (
    LedgerRepository,
    AccountNotFoundError,
    OptimisticLockConflictError,
)
from src.concurrency.executor import LedgerExecutor
from src.idempotency.store import (
    InMemoryIdempotencyStore,
    IdempotencyConflictError,
    IdempotencyPayloadMismatchError,
)
from src.reconciliation.parser import (
    parse_csv_statement,
    parse_json_statement,
)
from src.reconciliation.engine import (
    ReconciliationEngine,
    ReconciliationReport,
)
from src.telemetry.metrics import GLOBAL_METRICS, MetricsRegistry
from src.telemetry.logger import get_structured_logger, generate_trace_id

logger = get_structured_logger("ledgermesh.api")

# DTO schemas
class CreateAccountRequest(BaseModel):
    name: str
    code: str
    account_type: AccountType
    currency: str = "USD"
    initial_balance: int = 0

class CreateEntryRequest(BaseModel):
    account_id: str
    direction: EntryDirection
    amount: int
    description: Optional[str] = None

class CreateTransactionRequest(BaseModel):
    reference_id: str
    description: str
    entries: List[CreateEntryRequest]

class ReconcileRequest(BaseModel):
    csv_content: Optional[str] = None
    statement_items: Optional[List[dict]] = None

class AuditVerifyResponse(BaseModel):
    is_valid: bool
    total_verified: int
    tampered_transaction_id: Optional[str] = None
    error_message: Optional[str] = None
    merkle_root: str


def create_app(
    repo: Optional[LedgerRepository] = None,
    idempotency_store: Optional[InMemoryIdempotencyStore] = None,
    metrics: Optional[MetricsRegistry] = None,
) -> FastAPI:
    repository = repo or LedgerRepository()
    idem_store = idempotency_store or InMemoryIdempotencyStore()
    metrics_reg = metrics or GLOBAL_METRICS
    executor = LedgerExecutor(repository)
    reconciler = ReconciliationEngine(repository)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        accs = await repository.list_accounts()
        if not accs:
            await repository.create_account("Operating Checking (SVB)", "1000", AccountType.ASSET, initial_balance=5000000)
            await repository.create_account("Accounts Receivable", "1200", AccountType.ASSET, initial_balance=1250000)
            await repository.create_account("Subscription SaaS Revenue", "4000", AccountType.REVENUE, initial_balance=0)
            await repository.create_account("Accounts Payable", "2000", AccountType.LIABILITY, initial_balance=2000000)
        yield

    app = FastAPI(
        title="LedgerMesh Engine",
        version="1.0.0",
        description="High-Concurrency Double-Entry Financial Clearing & Audit Engine",
        lifespan=lifespan,
    )

    # Middleware: Distributed Trace ID & Request Latency Instrumentation
    @app.middleware("http")
    async def trace_and_telemetry_middleware(request: Request, call_next):
        trace_id = request.headers.get("X-Trace-Id") or generate_trace_id()
        request.state.trace_id = trace_id
        start_time = time.perf_counter()

        response: Response = await call_next(request)

        duration = time.perf_counter() - start_time
        response.headers["X-Trace-Id"] = trace_id
        response.headers["X-Response-Time-Sec"] = f"{duration:.6f}"

        metrics_reg.record_latency("http_request_duration", duration)
        metrics_reg.increment(f"http_status_{response.status_code}")
        return response

    @app.get("/api/v1/health")
    async def health_check():
        return {"status": "healthy", "service": "LedgerMesh", "version": "1.0.0"}

    @app.get("/metrics", response_class=PlainTextResponse)
    async def prometheus_metrics():
        return metrics_reg.export_prometheus_format()

    # Accounts API
    @app.post("/api/v1/accounts", response_model=Account, status_code=status.HTTP_201_CREATED)
    async def create_account(req: CreateAccountRequest):
        account = await repository.create_account(
            name=req.name,
            code=req.code,
            account_type=req.account_type,
            currency=req.currency,
            initial_balance=req.initial_balance,
        )
        metrics_reg.increment("accounts_created_total")
        return account

    @app.get("/api/v1/accounts", response_model=List[Account])
    async def list_accounts():
        return await repository.list_accounts()

    @app.get("/api/v1/accounts/{account_id}", response_model=Account)
    async def get_account(account_id: str):
        acc = await repository.get_account(account_id)
        if not acc:
            raise HTTPException(status_code=404, detail=f"Account '{account_id}' not found")
        return acc

    # Transactions API
    @app.post("/api/v1/transactions", response_model=Transaction, status_code=status.HTTP_201_CREATED)
    async def create_transaction(
        req: CreateTransactionRequest,
        idempotency_key: Optional[str] = Header(None, alias="Idempotency-Key"),
    ):
        start_time = time.perf_counter()
        payload_dict = req.model_dump(mode="json")

        # 1. Idempotency Check & In-Flight Lock Acquisition
        if idempotency_key:
            try:
                acquired = await idem_store.acquire_lock(idempotency_key, payload_dict)
                if not acquired:
                    # Key was already successfully completed, return cached response
                    cached = await idem_store.get_record(idempotency_key)
                    metrics_reg.increment("idempotency_hits_total")
                    if cached and cached.response_body:
                        return cached.response_body
            except IdempotencyConflictError as e:
                metrics_reg.increment("idempotency_conflicts_total")
                raise HTTPException(status_code=409, detail=str(e))
            except IdempotencyPayloadMismatchError as e:
                metrics_reg.increment("idempotency_mismatches_total")
                raise HTTPException(status_code=409, detail=str(e))

        # 2. Build Transaction Entity
        try:
            tx = Transaction(
                reference_id=req.reference_id,
                description=req.description,
                entries=[
                    Entry(
                        account_id=e.account_id,
                        direction=e.direction,
                        amount=e.amount,
                        description=e.description,
                    )
                    for e in req.entries
                ],
            )
        except (InvalidEntryAmountError, InvalidTransactionStructureError) as e:
            metrics_reg.increment("transactions_rejected_total")
            if idempotency_key:
                await idem_store.fail_request(idempotency_key, str(e))
            raise HTTPException(status_code=400, detail=str(e))

        # 3. Execute with OCC & Atomic Isolation
        try:
            posted_tx = await executor.execute_transaction(tx)
            metrics_reg.increment("transactions_posted_total")
            duration = time.perf_counter() - start_time
            metrics_reg.record_latency("transaction_execution", duration)

            # Store completed response for idempotency replay
            if idempotency_key:
                await idem_store.complete_request(
                    idempotency_key,
                    status_code=201,
                    response_body=posted_tx.model_dump(mode="json"),
                )

            return posted_tx

        except (UnbalancedTransactionError, InsufficientFundsError) as e:
            metrics_reg.increment("transactions_rejected_total")
            if idempotency_key:
                await idem_store.fail_request(idempotency_key, str(e))
            raise HTTPException(status_code=400, detail=str(e))

        except AccountNotFoundError as e:
            metrics_reg.increment("transactions_rejected_total")
            if idempotency_key:
                await idem_store.fail_request(idempotency_key, str(e))
            raise HTTPException(status_code=404, detail=str(e))

        except OptimisticLockConflictError as e:
            metrics_reg.increment("occ_conflicts_total")
            if idempotency_key:
                await idem_store.fail_request(idempotency_key, str(e))
            raise HTTPException(status_code=409, detail=str(e))

    @app.get("/api/v1/transactions", response_model=List[Transaction])
    async def list_transactions(limit: int = Query(100, ge=1, le=1000), offset: int = Query(0, ge=0)):
        return await repository.list_transactions(limit=limit, offset=offset)

    @app.get("/api/v1/transactions/{transaction_id}", response_model=Transaction)
    async def get_transaction(transaction_id: str):
        tx = await repository.get_transaction(transaction_id)
        if not tx:
            raise HTTPException(status_code=404, detail=f"Transaction '{transaction_id}' not found")
        return tx

    # Cryptographic Audit Verification API
    @app.get("/api/v1/audit/verify", response_model=AuditVerifyResponse)
    async def verify_ledger_audit():
        all_txs = await repository.list_transactions(limit=10000)
        result: AuditVerificationResult = verify_audit_chain(all_txs)
        merkle = compute_merkle_root([t.hash for t in all_txs if t.hash])
        return AuditVerifyResponse(
            is_valid=result.is_valid,
            total_verified=result.total_verified,
            tampered_transaction_id=result.tampered_transaction_id,
            error_message=result.error_message,
            merkle_root=merkle,
        )

    # Multi-Bank Reconciliation API
    @app.post("/api/v1/reconciliation/reconcile", response_model=ReconciliationReport)
    async def reconcile_bank_statement(
        account_id: str = Query(..., description="Target bank/cash account ID"),
        statement_id: str = Query(..., description="Unique bank statement identifier"),
        req: ReconcileRequest = ...,
    ):
        if req.csv_content:
            bank_txs = parse_csv_statement(req.csv_content)
        elif req.statement_items:
            bank_txs = parse_json_statement(req.statement_items)
        else:
            raise HTTPException(
                status_code=400,
                detail="Must provide either 'csv_content' or 'statement_items'",
            )

        try:
            report = await reconciler.reconcile_account(
                account_id=account_id,
                statement_id=statement_id,
                external_transactions=bank_txs,
            )
            metrics_reg.increment("reconciliations_completed_total")
            metrics_reg.set_gauge("last_reconciliation_discrepancy", float(report.net_discrepancy))
            return report
        except ValueError as e:
            raise HTTPException(status_code=404, detail=str(e))

    # Mount interactive frontend web experience
    frontend_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "frontend"))
    if os.path.exists(frontend_dir):
        app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")

    return app

# Default ASGI app instance for uvicorn
app = create_app()

