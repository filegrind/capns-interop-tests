"""Incoming request chunking interoperability tests.

Tests host sending large payloads TO plugins via chunked requests.
This validates the incoming request chunking implementation across all languages.
"""

import pytest
from capns_interop.framework.orchestrator import Orchestrator
from capns_interop.scenarios.chunking import (
    LargeIncomingPayloadScenario,
    MassiveIncomingPayloadScenario,
    BinaryIncomingScenario,
    HashIncomingScenario,
    MultipleIncomingScenario,
    ZeroLengthIncomingScenario,
)
from capns_interop.scenarios.base import ScenarioStatus


@pytest.mark.asyncio
@pytest.mark.timeout(60)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_large_incoming_payload(plugin_binaries, plugin_name):
    """Test plugin receiving 1MB incoming payload from host."""
    plugin_path = plugin_binaries[plugin_name]
    if not plugin_path.exists():
        pytest.skip(f"{plugin_name.title()} plugin not built")

    orchestrator = Orchestrator()
    scenario = LargeIncomingPayloadScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, \
        f"Large incoming payload failed: {result.error_message}"
    print(f"  [{plugin_name}] {result}")


@pytest.mark.asyncio
@pytest.mark.timeout(120)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_massive_incoming_payload(plugin_binaries, plugin_name):
    """Test plugin receiving 10MB incoming payload with heavy chunking."""
    plugin_path = plugin_binaries[plugin_name]
    if not plugin_path.exists():
        pytest.skip(f"{plugin_name.title()} plugin not built")

    orchestrator = Orchestrator()
    scenario = MassiveIncomingPayloadScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, \
        f"Massive incoming payload failed: {result.error_message}"
    print(f"  [{plugin_name}] {result}")


@pytest.mark.asyncio
@pytest.mark.timeout(60)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_binary_incoming(plugin_binaries, plugin_name):
    """Test plugin receiving binary data with all byte values."""
    plugin_path = plugin_binaries[plugin_name]
    if not plugin_path.exists():
        pytest.skip(f"{plugin_name.title()} plugin not built")

    orchestrator = Orchestrator()
    scenario = BinaryIncomingScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, \
        f"Binary incoming failed: {result.error_message}"
    print(f"  [{plugin_name}] {result}")


@pytest.mark.asyncio
@pytest.mark.timeout(90)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_hash_incoming(plugin_binaries, plugin_name):
    """Test plugin hashing 5MB incoming payload."""
    plugin_path = plugin_binaries[plugin_name]
    if not plugin_path.exists():
        pytest.skip(f"{plugin_name.title()} plugin not built")

    orchestrator = Orchestrator()
    scenario = HashIncomingScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, \
        f"Hash incoming failed: {result.error_message}"
    print(f"  [{plugin_name}] {result}")


@pytest.mark.asyncio
@pytest.mark.timeout(120)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_multiple_incoming(plugin_binaries, plugin_name):
    """Test multiple large incoming requests in sequence."""
    plugin_path = plugin_binaries[plugin_name]
    if not plugin_path.exists():
        pytest.skip(f"{plugin_name.title()} plugin not built")

    orchestrator = Orchestrator()
    scenario = MultipleIncomingScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, \
        f"Multiple incoming failed: {result.error_message}"
    print(f"  [{plugin_name}] {result}")


@pytest.mark.asyncio
@pytest.mark.timeout(30)
@pytest.mark.parametrize("plugin_name", ["rust", "python", "swift", "go"])
async def test_zero_length_incoming(plugin_binaries, plugin_name):
    """Test plugin receiving empty payload."""
    plugin_path = plugin_binaries[plugin_name]
    if not plugin_path.exists():
        pytest.skip(f"{plugin_name.title()} plugin not built")

    orchestrator = Orchestrator()
    scenario = ZeroLengthIncomingScenario()

    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, \
        f"Zero length incoming failed: {result.error_message}"
    print(f"  [{plugin_name}] {result}")
