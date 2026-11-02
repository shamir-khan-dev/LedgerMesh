import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

class StructuredJsonFormatter(logging.Formatter):
    """Formats log records as structured, machine-parsable JSON lines."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Include structured extra fields if passed
        if hasattr(record, "event"):
            log_entry["event"] = record.event
        if hasattr(record, "trace_id"):
            log_entry["trace_id"] = record.trace_id
        if hasattr(record, "account_id"):
            log_entry["account_id"] = record.account_id
        if hasattr(record, "transaction_id"):
            log_entry["transaction_id"] = record.transaction_id
        if hasattr(record, "extra_data") and isinstance(record.extra_data, dict):
            log_entry.update(record.extra_data)

        if record.exc_info:
            log_entry["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_entry)


def get_structured_logger(name: str = "ledgermesh") -> logging.Logger:
    """Configures and returns a structured logger with JSON output."""
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(StructuredJsonFormatter())
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
    return logger

def generate_trace_id() -> str:
    """Generates a unique distributed trace identifier for incoming requests."""
    return f"tr_{uuid.uuid4().hex[:16]}"
