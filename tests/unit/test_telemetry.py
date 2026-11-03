import pytest
from src.telemetry.metrics import MetricsRegistry

def test_metrics_registry_counters_and_latency_percentiles():
    metrics = MetricsRegistry()

    metrics.increment("transactions_total", 10)
    metrics.increment("transactions_posted", 9)
    metrics.increment("occ_conflicts_total", 3)

    assert metrics.get_counter("transactions_total") == 10
    assert metrics.get_counter("transactions_posted") == 9
    assert metrics.get_counter("occ_conflicts_total") == 3

    # Record some latency samples (in seconds)
    samples = [0.001, 0.002, 0.003, 0.004, 0.005, 0.010, 0.020, 0.050, 0.100, 0.200]
    for s in samples:
        metrics.record_latency("transaction_execution", s)

    summary = metrics.get_latency_summary("transaction_execution")
    assert summary["count"] == 10
    assert summary["p50"] > 0
    assert summary["p95"] >= summary["p50"]
    assert summary["p99"] >= summary["p95"]

    # Verify Prometheus exposition text output
    prom_text = metrics.export_prometheus_format()
    assert "ledgermesh_transactions_total" in prom_text
    assert "ledgermesh_occ_conflicts_total" in prom_text
    assert "ledgermesh_latency_p99_seconds" in prom_text

