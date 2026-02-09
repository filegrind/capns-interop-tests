"""Basic interoperability tests."""

import pytest
from pathlib import Path

from capns_interop.framework.orchestrator import Orchestrator
from capns_interop.scenarios.basic import (
    EchoScenario,
    DoubleScenario,
    BinaryEchoScenario,
    GetManifestScenario,
)
from capns_interop.scenarios.base import ScenarioStatus


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_rust_echo(rust_plugin):
    """Test echo capability with Rust plugin."""
    orchestrator = Orchestrator()
    scenario = EchoScenario()

    result = await orchestrator.run_scenario(rust_plugin, scenario)

    assert result.status == ScenarioStatus.PASS, f"Echo failed: {result.error_message}"
    assert result.duration_ms > 0
    print(f"  {result}")


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_rust_double(rust_plugin):
    """Test double capability with Rust plugin."""
    orchestrator = Orchestrator()
    scenario = DoubleScenario()

    result = await orchestrator.run_scenario(rust_plugin, scenario)

    assert result.status == ScenarioStatus.PASS, f"Double failed: {result.error_message}"
    assert result.duration_ms > 0
    print(f"  {result}")


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_rust_binary_echo(rust_plugin):
    """Test binary echo with Rust plugin."""
    orchestrator = Orchestrator()
    scenario = BinaryEchoScenario()

    result = await orchestrator.run_scenario(rust_plugin, scenario)

    assert (
        result.status == ScenarioStatus.PASS
    ), f"Binary echo failed: {result.error_message}"
    assert result.duration_ms > 0
    print(f"  {result}")


@pytest.mark.asyncio
@pytest.mark.timeout(30)
async def test_rust_get_manifest(rust_plugin):
    """Test manifest retrieval with Rust plugin."""
    orchestrator = Orchestrator()
    scenario = GetManifestScenario()

    result = await orchestrator.run_scenario(rust_plugin, scenario)

    assert (
        result.status == ScenarioStatus.PASS
    ), f"Get manifest failed: {result.error_message}"
    assert result.duration_ms > 0
    print(f"  {result}")


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_echo_all_plugins(plugin_binaries, plugin_name):
    """Test echo capability across all plugin implementations."""
    plugin_path = plugin_binaries[plugin_name]
    orchestrator = Orchestrator()
    scenario = EchoScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, f"Echo failed: {result.error_message}"
    print(f"  [{plugin_name}] {result}")
