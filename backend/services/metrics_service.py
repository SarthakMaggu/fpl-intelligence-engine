from __future__ import annotations

from collections import defaultdict
from threading import Lock


class MetricsRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self.counters = defaultdict(float)
        self.histograms = defaultdict(list)
        self.gauges = {}

    def inc(self, name: str, value: float = 1.0) -> None:
        with self._lock:
            self.counters[name] += value

    def observe(self, name: str, value: float) -> None:
        with self._lock:
            self.histograms[name].append(value)

    def set_gauge(self, name: str, value: float) -> None:
        with self._lock:
            self.gauges[name] = value

    def render_prometheus(self) -> str:
        lines: list[str] = []
        with self._lock:
            for name, value in sorted(self.counters.items()):
                lines.append(f"{name} {value}")
            for name, value in sorted(self.gauges.items()):
                lines.append(f"{name} {value}")
            for name, samples in sorted(self.histograms.items()):
                if not samples:
                    continue
                lines.append(f"{name}_count {len(samples)}")
                lines.append(f"{name}_sum {sum(samples)}")
        return "\n".join(lines) + "\n"


metrics_registry = MetricsRegistry()
