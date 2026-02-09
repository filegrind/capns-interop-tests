"""Cross-language Host x Plugin interop test matrix.

Tests all 16 combinations of 4 host languages x 4 plugin languages
across 8 core scenarios = 128 test cases.

Each test uses the two-layer subprocess model:
    pytest → test host binary (JSON-line) → test plugin binary (CBOR)

This validates that every host implementation correctly handles
the CBOR protocol when talking to every plugin implementation.
"""

import json
import pytest
from pathlib import Path
from capns_interop import TEST_CAPS
from capns_interop.framework.matrix_orchestrator import MatrixOrchestrator
from capns_interop.scenarios.base import ScenarioStatus
from capns_interop.scenarios.basic import (
    EchoScenario,
    DoubleScenario,
    BinaryEchoScenario,
)
from capns_interop.scenarios.streaming import (
    StreamChunksScenario,
    LargePayloadScenario,
)
from capns_interop.scenarios.bidirectional import (
    PeerEchoScenario,
    NestedCallScenario,
)
from capns_interop.scenarios.chunking import LargeIncomingPayloadScenario


HOSTS = ["rust", "go", "python", "swift"]
PLUGINS = ["rust", "go", "python", "swift"]

SCENARIOS = {
    "echo": EchoScenario,
    "double": DoubleScenario,
    "binary_echo": BinaryEchoScenario,
    "stream_chunks": StreamChunksScenario,
    "large_payload": LargePayloadScenario,
    "peer_echo": PeerEchoScenario,
    "nested_call": NestedCallScenario,
    "large_incoming": LargeIncomingPayloadScenario,
}


@pytest.mark.asyncio
@pytest.mark.timeout(60)
@pytest.mark.parametrize("host_lang", HOSTS)
@pytest.mark.parametrize("plugin_lang", PLUGINS)
@pytest.mark.parametrize("scenario_name", list(SCENARIOS.keys()))
async def test_host_plugin_matrix(
    host_binaries, plugin_binaries, host_lang, plugin_lang, scenario_name
):
    """Test a specific host x plugin x scenario combination."""
    host_path = host_binaries[host_lang]
    plugin_path = plugin_binaries[plugin_lang]

    scenario_cls = SCENARIOS[scenario_name]
    scenario = scenario_cls()

    orchestrator = MatrixOrchestrator(host_path)
    result = await orchestrator.run_scenario(plugin_path, scenario)

    assert result.status == ScenarioStatus.PASS, (
        f"[{host_lang}-host → {plugin_lang}-plugin] {scenario_name} failed: "
        f"{result.error_message}"
    )
