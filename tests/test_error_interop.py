"""Error handling interoperability tests."""

import pytest
from capns_interop.framework.orchestrator import Orchestrator
from capns_interop.scenarios.error_handling import (
    ThrowErrorScenario,
    InvalidCapScenario,
    MalformedPayloadScenario,
    GracefulShutdownScenario,
)
from capns_interop.scenarios.base import ScenarioStatus


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_throw_error(plugin_binaries, plugin_name):
    """Test error propagation from plugin to host."""
    plugin_path = plugin_binaries[plugin_name]
    if not plugin_path.exists():
        pytest.skip(f"{plugin_name.title()} plugin not built")

    orchestrator = Orchestrator()
    scenario = ThrowErrorScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, f"Throw error failed: {result.error_message}"
    print(f"  [{plugin_name}] {result}")


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_invalid_cap(plugin_binaries, plugin_name):
    """Test calling non-existent capability."""
    plugin_path = plugin_binaries[plugin_name]
    if not plugin_path.exists():
        pytest.skip(f"{plugin_name.title()} plugin not built")

    orchestrator = Orchestrator()
    scenario = InvalidCapScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, f"Invalid cap failed: {result.error_message}"
    print(f"  [{plugin_name}] {result}")


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_malformed_payload(plugin_binaries, plugin_name):
    """Test sending malformed JSON payload."""
    plugin_path = plugin_binaries[plugin_name]
    if not plugin_path.exists():
        pytest.skip(f"{plugin_name.title()} plugin not built")

    orchestrator = Orchestrator()
    scenario = MalformedPayloadScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, f"Malformed payload failed: {result.error_message}"
    print(f"  [{plugin_name}] {result}")


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_graceful_shutdown(plugin_binaries, plugin_name):
    """Test graceful shutdown after operations."""
    plugin_path = plugin_binaries[plugin_name]
    if not plugin_path.exists():
        pytest.skip(f"{plugin_name.title()} plugin not built")

    orchestrator = Orchestrator()
    scenario = GracefulShutdownScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, f"Graceful shutdown failed: {result.error_message}"
    print(f"  [{plugin_name}] {result}")
