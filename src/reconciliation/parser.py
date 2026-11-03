import csv
import io
import json
from datetime import datetime, timezone
from typing import List, Union
from src.reconciliation.models import BankStatementTransaction

def _parse_amount_to_cents(val: Union[str, int, float]) -> int:
    """Converts a currency representation (e.g., '150.00', '-25.50', 5000) to integer cents."""
    if isinstance(val, int):
        return val
    if isinstance(val, float):
        return int(round(val * 100))

    cleaned = str(val).replace("$", "").replace(",", "").strip()
    return int(round(float(cleaned) * 100))

def _parse_date(val: Union[str, datetime]) -> datetime:
    """Parses various standard date formats into timezone-aware UTC datetime."""
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)

    val_str = str(val).strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            dt = datetime.strptime(val_str, fmt)
            return dt.replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return datetime.now(timezone.utc)


def parse_csv_statement(csv_content: str) -> List[BankStatementTransaction]:
    """
    Parses a CSV bank statement into standardized BankStatementTransaction records.
    Supports case-insensitive column headers: Date, Amount, Description, Reference.
    """
    reader = csv.DictReader(io.StringIO(csv_content.strip()))
    transactions: List[BankStatementTransaction] = []

    for row in reader:
        # Normalize header keys
        normalized = {k.strip().lower(): v.strip() for k, v in row.items() if k}

        date_val = normalized.get("date") or normalized.get("transaction date") or normalized.get("posted date")
        amount_val = normalized.get("amount") or normalized.get("transaction amount")
        desc_val = normalized.get("description") or normalized.get("memo") or normalized.get("payee") or "Bank Entry"
        ref_val = normalized.get("reference") or normalized.get("ref") or normalized.get("reference id") or normalized.get("id")

        if not amount_val or not date_val:
            continue

        cents = _parse_amount_to_cents(amount_val)
        dt = _parse_date(date_val)

        tx = BankStatementTransaction(
            date=dt,
            amount=cents,
            description=desc_val,
            reference=ref_val if ref_val else None,
        )
        transactions.append(tx)

    return transactions


def parse_json_statement(json_data: Union[str, List[dict]]) -> List[BankStatementTransaction]:
    """Parses JSON bank statement feeds into standardized BankStatementTransaction records."""
    if isinstance(json_data, str):
        items = json.loads(json_data)
    else:
        items = json_data

    transactions: List[BankStatementTransaction] = []
    for item in items:
        cents = _parse_amount_to_cents(item.get("amount", 0))
        dt = _parse_date(item.get("date", datetime.now(timezone.utc)))
        tx = BankStatementTransaction(
            external_id=item.get("external_id") or item.get("id") or None,
            date=dt,
            amount=cents,
            description=item.get("description", "Bank Transaction"),
            reference=item.get("reference"),
        )
        transactions.append(tx)

    return transactions

