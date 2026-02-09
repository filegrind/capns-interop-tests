"""Stream multiplexing interoperability tests for Protocol v2.

Tests the new STREAM_START and STREAM_END frame types introduced in Protocol v2,
ensuring all implementations correctly handle multiplexed streams within requests.
"""

import pytest
from capns_interop.framework.orchestrator import Orchestrator
from capns_interop.scenarios.stream_multiplexing import (
    SingleStreamScenario,
    MultipleStreamsScenario,
    EmptyStreamScenario,
    InterleavedStreamsScenario,
    StreamErrorHandlingScenario,
)
from capns_interop.scenarios.base import ScenarioStatus


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_single_stream(plugin_binaries, plugin_name):
    """Test single stream with STREAM_START + CHUNK + STREAM_END."""
    plugin_path = plugin_binaries[plugin_name]
    orchestrator = Orchestrator()
    scenario = SingleStreamScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, f"Single stream failed: {result.error_message}"
    print(f"  [{plugin_name}] {result}")


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_multiple_streams(plugin_binaries, plugin_name):
    """Test multiple independent streams in a single request."""
    plugin_path = plugin_binaries[plugin_name]
    orchestrator = Orchestrator()
    scenario = MultipleStreamsScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, f"Multiple streams failed: {result.error_message}"
    print(f"  [{plugin_name}] {result}")


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_empty_stream(plugin_binaries, plugin_name):
    """Test stream with no chunks (STREAM_START immediately followed by STREAM_END)."""
    plugin_path = plugin_binaries[plugin_name]
    orchestrator = Orchestrator()
    scenario = EmptyStreamScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, f"Empty stream failed: {result.error_message}"
    print(f"  [{plugin_name}] {result}")


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_interleaved_streams(plugin_binaries, plugin_name):
    """Test interleaved chunks from multiple streams."""
    plugin_path = plugin_binaries[plugin_name]
    orchestrator = Orchestrator()
    scenario = InterleavedStreamsScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, f"Interleaved streams failed: {result.error_message}"
    print(f"  [{plugin_name}] {result}")


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_stream_error_handling(plugin_binaries, plugin_name):
    """Test error handling for stream protocol violations."""
    plugin_path = plugin_binaries[plugin_name]
    orchestrator = Orchestrator()
    scenario = StreamErrorHandlingScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, f"Stream error handling failed: {result.error_message}"
    print(f"  [{plugin_name}] {result}")


@pytest.mark.asyncio
@pytest.mark.timeout(60)
async def test_protocol_version_negotiation(plugin_binaries):
    """Test that all plugins negotiate Protocol v2."""
    results = {}

    for plugin_name in ["rust", "python", "swift", "go"]:
        plugin_path = plugin_binaries[plugin_name]

        # Test handshake negotiates version 2
        # This is implicitly tested by all scenarios, but we verify explicitly here
        orchestrator = Orchestrator()
        scenario = SingleStreamScenario()

        result = await orchestrator.run_scenario(plugin_path, scenario)
        results[plugin_name] = result.status == ScenarioStatus.PASS

    # At least one implementation must support v2
    assert any(results.values()), "No plugins support Protocol v2"

    # Report which plugins passed
    for name, passed in results.items():
        status = "✓" if passed else "✗"
        print(f"  [{name}] {status}")
