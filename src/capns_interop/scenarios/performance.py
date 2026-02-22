"""Performance benchmark scenarios."""

import json
import time
import statistics
from .. import TEST_CAPS
from .base import Scenario, ScenarioResult, ScenarioStatus
from capns.cap.caller import CapArgumentValue


class LatencyBenchmarkScenario(Scenario):
    """Benchmark request/response latency."""

    @property
    def name(self) -> str:
        return "latency_benchmark"

    @property
    def description(self) -> str:
        return "Measure request/response latency (100 iterations)"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            iterations = 100
            latencies = []

            for _ in range(iterations):
                test_input = b"benchmark"

                start = time.perf_counter()
                response = await host.call_with_arguments(TEST_CAPS["echo"], [CapArgumentValue("media:", test_input)])
                output = response.final_payload()
                duration = (time.perf_counter() - start) * 1000  # ms

                assert output == test_input
                latencies.append(duration)

            # Calculate statistics
            p50 = statistics.median(latencies)
            p95 = statistics.quantiles(latencies, n=20)[18]  # 95th percentile
            p99 = statistics.quantiles(latencies, n=100)[98]  # 99th percentile
            avg = statistics.mean(latencies)

            # Store metrics
            metrics = {
                "iterations": iterations,
                "p50_ms": round(p50, 2),
                "p95_ms": round(p95, 2),
                "p99_ms": round(p99, 2),
                "avg_ms": round(avg, 2),
            }

            # Verify reasonable latency (under 100ms for p99)
            assert p99 < 100, f"P99 latency too high: {p99:.2f}ms"

            return ScenarioResult(
                status=ScenarioStatus.PASS,
                duration_ms=sum(latencies),
                metrics=metrics
            )

        return await self._timed_execute(run)


class ThroughputBenchmarkScenario(Scenario):
    """Benchmark throughput (requests per second)."""

    @property
    def name(self) -> str:
        return "throughput_benchmark"

    @property
    def description(self) -> str:
        return "Measure throughput (requests/second)"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            duration_seconds = 2
            test_input = b"throughput"

            start = time.perf_counter()
            count = 0

            while (time.perf_counter() - start) < duration_seconds:
                response = await host.call_with_arguments(TEST_CAPS["echo"], [CapArgumentValue("media:", test_input)])
                output = response.final_payload()
                assert output == test_input
                count += 1

            elapsed = time.perf_counter() - start
            rps = count / elapsed

            metrics = {
                "requests": count,
                "duration_seconds": round(elapsed, 2),
                "requests_per_second": round(rps, 2),
            }

            # Verify reasonable throughput (at least 100 req/s)
            assert rps > 100, f"Throughput too low: {rps:.2f} req/s"

            return ScenarioResult(
                status=ScenarioStatus.PASS,
                duration_ms=elapsed * 1000,
                metrics=metrics
            )

        return await self._timed_execute(run)


class LargePayloadThroughputScenario(Scenario):
    """Benchmark large payload transfer speed."""

    @property
    def name(self) -> str:
        return "large_payload_throughput"

    @property
    def description(self) -> str:
        return "Measure large payload throughput (MB/sec)"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            payload_size = 10 * 1024 * 1024  # 10 MB
            input_json = json.dumps({"value": payload_size}).encode()

            start = time.perf_counter()
            response = await host.call_with_arguments(TEST_CAPS["generate_large"], [CapArgumentValue("media:json", input_json)])
            output = response.concatenated()
            elapsed = time.perf_counter() - start

            assert len(output) == payload_size

            mb_per_sec = (payload_size / (1024 * 1024)) / elapsed

            metrics = {
                "payload_size_mb": round(payload_size / (1024 * 1024), 2),
                "duration_seconds": round(elapsed, 2),
                "throughput_mb_per_sec": round(mb_per_sec, 2),
            }

            # Verify reasonable throughput (at least 1 MB/s with CBOR + chunking overhead)
            assert mb_per_sec > 1, f"Throughput too low: {mb_per_sec:.2f} MB/s"

            return ScenarioResult(
                status=ScenarioStatus.PASS,
                duration_ms=elapsed * 1000,
                metrics=metrics
            )

        return await self._timed_execute(run)


class MatrixThroughputScenario:
    """Throughput measurement for the host x plugin matrix.

    NOT a Scenario subclass — uses RemoteHost.run_throughput() which
    delegates the entire benchmark to the host binary.  The host calls
    generate_large over CBOR (chunked automatically), measures wall-clock
    time, and returns only the metric.  No payload crosses JSON-lines.
    """

    def __init__(self, payload_mb: int = 5):
        self.payload_mb = payload_mb


class ConcurrentStressScenario(Scenario):
    """Test concurrent request handling."""

    @property
    def name(self) -> str:
        return "concurrent_stress"

    @property
    def description(self) -> str:
        return "Concurrent workload simulation"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            work_units = 100
            input_json = json.dumps({"value": work_units}).encode()

            response = await host.call_with_arguments(TEST_CAPS["concurrent_stress"], [CapArgumentValue("media:json", input_json)])

            output = response.final_payload()
            # Just verify it completed successfully
            assert output.startswith(b"computed-"), f"Unexpected output: {output!r}"

        return await self._timed_execute(run)
