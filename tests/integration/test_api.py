import pytest
from fastapi.testclient import TestClient
from src.api.main import create_app
from src.concurrency.repository import LedgerRepository
from src.idempotency.store import InMemoryIdempotencyStore

@pytest.fixture
def client():
    repo = LedgerRepository()
    idempotency_store = InMemoryIdempotencyStore()
    app = create_app(repo=repo, idempotency_store=idempotency_store)
    return TestClient(app)

def test_health_check(client):
    res = client.get("/api/v1/health")
    assert res.status_code == 200
    assert res.json()["status"] == "healthy"

def test_create_and_query_accounts(client):
    # Create Cash Account
    res1 = client.post(
        "/api/v1/accounts",
        json={"name": "Checking Account", "code": "1010", "account_type": "ASSET", "initial_balance": 50000},
    )
    assert res1.status_code == 201
    cash_acc = res1.json()
    assert cash_acc["balance"] == 50000
    assert cash_acc["version"] == 1

    # Create Revenue Account
    res2 = client.post(
        "/api/v1/accounts",
        json={"name": "Sales Revenue", "code": "4010", "account_type": "REVENUE", "initial_balance": 0},
    )
    assert res2.status_code == 201
    rev_acc = res2.json()

    # Query all accounts
    res_list = client.get("/api/v1/accounts")
    assert res_list.status_code == 200
    assert len(res_list.json()) == 2

def test_post_balanced_transaction_with_idempotency(client):
    # Setup accounts
    cash = client.post(
        "/api/v1/accounts",
        json={"name": "Cash", "code": "1000", "account_type": "ASSET", "initial_balance": 10000},
    ).json()
    rev = client.post(
        "/api/v1/accounts",
        json={"name": "Revenue", "code": "4000", "account_type": "REVENUE", "initial_balance": 0},
    ).json()

    tx_payload = {
        "reference_id": "ORD-999",
        "description": "Order #999 Payment",
        "entries": [
            {"account_id": cash["id"], "direction": "DEBIT", "amount": 2500},
            {"account_id": rev["id"], "direction": "CREDIT", "amount": 2500},
        ],
    }

    # 1. Post transaction with Idempotency-Key
    headers = {"Idempotency-Key": "idem_test_999"}
    res1 = client.post("/api/v1/transactions", json=tx_payload, headers=headers)
    assert res1.status_code == 201
    tx_data = res1.json()
    assert tx_data["status"] == "POSTED"
    assert tx_data["hash"] is not None

    # Verify balance was updated
    acc_check = client.get(f"/api/v1/accounts/{cash['id']}").json()
    assert acc_check["balance"] == 12500  # $100 + $25

    # 2. Re-send exact same request with SAME Idempotency-Key (simulating network retry)
    res2 = client.post("/api/v1/transactions", json=tx_payload, headers=headers)
    assert res2.status_code == 201
    assert res2.json()["id"] == tx_data["id"]

    # Verify balance was NOT double-credited!
    acc_check_again = client.get(f"/api/v1/accounts/{cash['id']}").json()
    assert acc_check_again["balance"] == 12500

def test_unbalanced_transaction_rejected_by_api(client):
    cash = client.post(
        "/api/v1/accounts",
        json={"name": "Cash", "code": "1000", "account_type": "ASSET", "initial_balance": 10000},
    ).json()
    rev = client.post(
        "/api/v1/accounts",
        json={"name": "Revenue", "code": "4000", "account_type": "REVENUE", "initial_balance": 0},
    ).json()

    unbalanced_payload = {
        "reference_id": "FAIL-01",
        "description": "Unbalanced",
        "entries": [
            {"account_id": cash["id"], "direction": "DEBIT", "amount": 2500},
            {"account_id": rev["id"], "direction": "CREDIT", "amount": 1000},  # Discrepancy!
        ],
    }

    res = client.post("/api/v1/transactions", json=unbalanced_payload)
    assert res.status_code == 400
    assert "Double-entry invariant violated" in res.json()["detail"]

def test_audit_verification_endpoint(client):
    # Verify audit endpoint returns is_valid == true
    res = client.get("/api/v1/audit/verify")
    assert res.status_code == 200
    data = res.json()
    assert data["is_valid"] is True

def test_reconciliation_csv_endpoint(client):
    bank = client.post(
        "/api/v1/accounts",
        json={"name": "Operating", "code": "1000", "account_type": "ASSET", "initial_balance": 0},
    ).json()
    sales = client.post(
        "/api/v1/accounts",
        json={"name": "Sales", "code": "4000", "account_type": "REVENUE", "initial_balance": 0},
    ).json()

    # Post internal tx
    client.post(
        "/api/v1/transactions",
        json={
            "reference_id": "REC-01",
            "description": "Deposit #1",
            "entries": [
                {"account_id": bank["id"], "direction": "DEBIT", "amount": 7500},
                {"account_id": sales["id"], "direction": "CREDIT", "amount": 7500},
            ],
        },
    )

    csv_data = """Date,Amount,Description,Reference
2026-11-01,75.00,Deposit REC-01,REC-01
"""
    res = client.post(
        f"/api/v1/reconciliation/reconcile?account_id={bank['id']}&statement_id=STMT-01",
        json={"csv_content": csv_data},
    )
    assert res.status_code == 200
    rep = res.json()
    assert rep["matched_count"] == 1
    assert rep["net_discrepancy"] == 0

def test_prometheus_metrics_endpoint(client):
    res = client.get("/metrics")
    assert res.status_code == 200
    assert "ledgermesh" in res.text
