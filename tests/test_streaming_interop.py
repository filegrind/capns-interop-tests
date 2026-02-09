"""Streaming interoperability tests."""

import pytest
from capns_interop.framework.orchestrator import Orchestrator
from capns_interop.scenarios.streaming import (
    StreamChunksScenario,
    LargePayloadScenario,
    BinaryDataScenario,
    StreamOrderingScenario,
)
from capns_interop.scenarios.base import ScenarioStatus


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_stream_chunks(plugin_binaries, plugin_name):
    """Test streaming multiple chunks."""
    plugin_path = plugin_binaries[plugin_name]
    orchestrator = Orchestrator()
    scenario = StreamChunksScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, f"Stream chunks failed: {result.error_message}"
    print(f"  [{plugin_name}] {result}")


@pytest.mark.asyncio
@pytest.mark.timeout(60)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_large_payload(plugin_binaries, plugin_name):
    """Test large payload transfer (1MB)."""
    plugin_path = plugin_binaries[plugin_name]
    orchestrator = Orchestrator()
    scenario = LargePayloadScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, f"Large payload failed: {result.error_message}"
    print(f"  [{plugin_name}] {result}")


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_binary_data(plugin_binaries, plugin_name):
    """Test binary data with all byte values."""
    plugin_path = plugin_binaries[plugin_name]
    orchestrator = Orchestrator()
    scenario = BinaryDataScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, f"Binary data failed: {result.error_message}"
    print(f"  [{plugin_name}] {result}")


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_stream_ordering(plugin_binaries, plugin_name):
    """Test streaming chunk ordering."""
    plugin_path = plugin_binaries[plugin_name]
    orchestrator = Orchestrator()
    scenario = StreamOrderingScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, f"Stream ordering failed: {result.error_message}"
    print(f"  [{plugin_name}] {result}")
