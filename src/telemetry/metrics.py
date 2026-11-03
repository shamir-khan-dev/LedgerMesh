import threading
from typing import Dict, List, Optional
import numpy as np

class MetricsRegistry:
    """
    High-performance thread-safe telemetry and latency percentile registry.
    Calculates streaming p50, p90, p95, and p99 percentiles and exports standard
    Prometheus exposition metrics.
    """

    def __init__(self):
        self._counters: Dict[str, int] = {}
        self._gauges: Dict[str, float] = {}
        self._latency_samples: Dict[str, List[float]] = {}
        self._lock = threading.Lock()

    def increment(self, metric: str, amount: int = 1) -> None:
        """Atomically increments a monotonic counter."""
        with self._lock:
            self._counters[metric] = self._counters.get(metric, 0) + amount

    def get_counter(self, metric: str) -> int:
        with self._lock:
            return self._counters.get(metric, 0)

    def set_gauge(self, metric: str, value: float) -> None:
        """Sets a current gauge reading."""
        with self._lock:
            self._gauges[metric] = value

    def record_latency(self, metric: str, duration_seconds: float) -> None:
        """Records an execution latency sample (in seconds). Maintains a bounded sliding window."""
        with self._lock:
            if metric not in self._latency_samples:
                self._latency_samples[metric] = []
            samples = self._latency_samples[metric]
            samples.append(duration_seconds)
            # Bound memory to 10,000 recent samples
            if len(samples) > 10000:
                self._latency_samples[metric] = samples[-10000:]

    def get_latency_summary(self, metric: str) -> Dict[str, float]:
        """Calculates min, mean, p50, p90, p95, p99, max latency percentiles."""
        with self._lock:
            samples = list(self._latency_samples.get(metric, []))

        if not samples:
            return {"count": 0, "p50": 0.0, "p90": 0.0, "p95": 0.0, "p99": 0.0, "max": 0.0}

        arr = np.array(samples)
        return {
            "count": float(len(arr)),
            "p50": float(np.percentile(arr, 50)),
            "p90": float(np.percentile(arr, 90)),
            "p95": float(np.percentile(arr, 95)),
            "p99": float(np.percentile(arr, 99)),
            "max": float(np.max(arr)),
        }

    def export_prometheus_format(self) -> str:
        """Generates standard Prometheus text exposition format."""
        lines = []

        with self._lock:
            # Counters
            for name, val in sorted(self._counters.items()):
                prom_name = f"ledgermesh_{name}"
                lines.append(f"# TYPE {prom_name} counter")
                lines.append(f"{prom_name} {val}")

            # Gauges
            for name, val in sorted(self._gauges.items()):
                prom_name = f"ledgermesh_{name}"
                lines.append(f"# TYPE {prom_name} gauge")
                lines.append(f"{prom_name} {val:.4f}")

            # Latency percentiles
            for name, samples in sorted(self._latency_samples.items()):
                if not samples:
                    continue
                arr = np.array(samples)
                p50 = float(np.percentile(arr, 50))
                p95 = float(np.percentile(arr, 95))
                p99 = float(np.percentile(arr, 99))
                lines.append(f"# TYPE ledgermesh_latency_p50_seconds gauge")
                lines.append(f'ledgermesh_latency_p50_seconds{{operation="{name}"}} {p50:.6f}')
                lines.append(f"# TYPE ledgermesh_latency_p95_seconds gauge")
                lines.append(f'ledgermesh_latency_p95_seconds{{operation="{name}"}} {p95:.6f}')
                lines.append(f"# TYPE ledgermesh_latency_p99_seconds gauge")
                lines.append(f'ledgermesh_latency_p99_seconds{{operation="{name}"}} {p99:.6f}')

        return "\n".join(lines) + "\n"

# Global singleton
GLOBAL_METRICS = MetricsRegistry()

