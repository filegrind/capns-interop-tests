"""Bidirectional communication interoperability tests."""

import pytest
from capns_interop.framework.orchestrator import Orchestrator
from capns_interop.scenarios.bidirectional import (
    PeerEchoScenario,
    NestedCallScenario,
    BidirectionalEchoScenario,
)
from capns_interop.scenarios.base import ScenarioStatus


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_peer_echo(plugin_binaries, plugin_name):
    """Test plugin calling host's echo capability."""
    plugin_path = plugin_binaries[plugin_name]
    if not plugin_path.exists():
        pytest.skip(f"{plugin_name.title()} plugin not built")

    orchestrator = Orchestrator()
    scenario = PeerEchoScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, f"Peer echo failed: {result.error_message}"
    print(f"  [{plugin_name}] {result}")


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_nested_call(plugin_binaries, plugin_name):
    """Test nested invocation (plugin → host → plugin)."""
    plugin_path = plugin_binaries[plugin_name]
    if not plugin_path.exists():
        pytest.skip(f"{plugin_name.title()} plugin not built")

    orchestrator = Orchestrator()
    scenario = NestedCallScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, f"Nested call failed: {result.error_message}"
    print(f"  [{plugin_name}] {result}")


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_bidirectional_echo_multi(plugin_binaries, plugin_name):
    """Test multiple bidirectional echo calls."""
    plugin_path = plugin_binaries[plugin_name]
    if not plugin_path.exists():
        pytest.skip(f"{plugin_name.title()} plugin not built")

    orchestrator = Orchestrator()
    scenario = BidirectionalEchoScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, f"Bidirectional echo multi failed: {result.error_message}"
    print(f"  [{plugin_name}] {result}")
