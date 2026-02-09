"""Performance benchmark tests."""

import pytest
from capns_interop.framework.orchestrator import Orchestrator
from capns_interop.scenarios.performance import (
    LatencyBenchmarkScenario,
    ThroughputBenchmarkScenario,
    LargePayloadThroughputScenario,
    ConcurrentStressScenario,
)
from capns_interop.scenarios.base import ScenarioStatus


@pytest.mark.asyncio
@pytest.mark.timeout(60)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_latency_benchmark(plugin_binaries, plugin_name):
    """Benchmark request/response latency."""
    plugin_path = plugin_binaries[plugin_name]
    orchestrator = Orchestrator()
    scenario = LatencyBenchmarkScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, f"Latency benchmark failed: {result.error_message}"

    if result.metrics:
        print(f"  [{plugin_name}] Latency: p50={result.metrics['p50_ms']}ms, p95={result.metrics['p95_ms']}ms, p99={result.metrics['p99_ms']}ms")
    else:
        print(f"  [{plugin_name}] {result}")


@pytest.mark.asyncio
@pytest.mark.timeout(60)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_throughput_benchmark(plugin_binaries, plugin_name):
    """Benchmark throughput (requests per second)."""
    plugin_path = plugin_binaries[plugin_name]
    orchestrator = Orchestrator()
    scenario = ThroughputBenchmarkScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, f"Throughput benchmark failed: {result.error_message}"

    if result.metrics:
        print(f"  [{plugin_name}] Throughput: {result.metrics['requests_per_second']} req/s ({result.metrics['requests']} requests)")
    else:
        print(f"  [{plugin_name}] {result}")


@pytest.mark.asyncio
@pytest.mark.timeout(60)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_large_payload_throughput(plugin_binaries, plugin_name):
    """Benchmark large payload transfer speed."""
    plugin_path = plugin_binaries[plugin_name]
    orchestrator = Orchestrator()
    scenario = LargePayloadThroughputScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, f"Large payload throughput failed: {result.error_message}"

    if result.metrics:
        print(f"  [{plugin_name}] Throughput: {result.metrics['throughput_mb_per_sec']} MB/s ({result.metrics['payload_size_mb']} MB)")
    else:
        print(f"  [{plugin_name}] {result}")


@pytest.mark.asyncio
@pytest.mark.timeout(60)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_concurrent_stress(plugin_binaries, plugin_name):
    """Test concurrent request handling."""
    plugin_path = plugin_binaries[plugin_name]
    orchestrator = Orchestrator()
    scenario = ConcurrentStressScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, f"Concurrent stress failed: {result.error_message}"
    print(f"  [{plugin_name}] {result}")
