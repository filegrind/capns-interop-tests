"""Heartbeat interoperability tests."""

import pytest
from capns_interop.framework.orchestrator import Orchestrator
from capns_interop.scenarios.heartbeat import (
    BasicHeartbeatScenario,
    LongOperationHeartbeatScenario,
    StatusUpdateScenario,
)
from capns_interop.scenarios.base import ScenarioStatus


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_basic_heartbeat(plugin_binaries, plugin_name):
    """Test basic heartbeat during operation."""
    plugin_path = plugin_binaries[plugin_name]
    if not plugin_path.exists():
        pytest.skip(f"{plugin_name.title()} plugin not built")

    orchestrator = Orchestrator()
    scenario = BasicHeartbeatScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, f"Basic heartbeat failed: {result.error_message}"
    print(f"  [{plugin_name}] {result}")


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_long_operation_heartbeat(plugin_binaries, plugin_name):
    """Test heartbeat during long operation (2 seconds)."""
    plugin_path = plugin_binaries[plugin_name]
    if not plugin_path.exists():
        pytest.skip(f"{plugin_name.title()} plugin not built")

    orchestrator = Orchestrator()
    scenario = LongOperationHeartbeatScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, f"Long operation heartbeat failed: {result.error_message}"
    print(f"  [{plugin_name}] {result}")


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_status_updates(plugin_binaries, plugin_name):
    """Test status updates during processing."""
    plugin_path = plugin_binaries[plugin_name]
    if not plugin_path.exists():
        pytest.skip(f"{plugin_name.title()} plugin not built")

    orchestrator = Orchestrator()
    scenario = StatusUpdateScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, f"Status updates failed: {result.error_message}"
    print(f"  [{plugin_name}] {result}")
