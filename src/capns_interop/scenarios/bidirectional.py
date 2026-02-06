"""Bidirectional communication test scenarios."""

import json
from .. import TEST_CAPS
from .base import Scenario, ScenarioResult


class PeerEchoScenario(Scenario):
    """Test plugin calling host's echo capability."""

    @property
    def name(self) -> str:
        return "peer_echo"

    @property
    def description(self) -> str:
        return "Plugin calls host echo via PeerInvoker"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            test_input = b"Hello from host!"

            # Plugin will call back to host's echo with the raw bytes
            # peer_echo handler sends the input as-is to host's echo
            response = await host.call(TEST_CAPS["peer_echo"], test_input, "media:bytes")

            output = response.final_payload()
            # The plugin echoes back what the host echo returned
            assert output == test_input, f"Expected {test_input!r}, got {output!r}"

        return await self._timed_execute(run)


class NestedCallScenario(Scenario):
    """Test nested invocation: plugin → host → plugin."""

    @property
    def name(self) -> str:
        return "nested_call"

    @property
    def description(self) -> str:
        return "Nested invocation (plugin → host → plugin)"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            value = 21
            input_json = json.dumps({"value": value}).encode()

            # Plugin calls host's double (21 * 2 = 42), then doubles again locally (42 * 2 = 84)
            response = await host.call(TEST_CAPS["nested_call"], input_json, "media:json")

            output = response.final_payload()
            result = json.loads(output)
            expected = value * 4  # Doubled twice
            assert result == expected, f"Expected {expected}, got {result}"

        return await self._timed_execute(run)


class BidirectionalEchoScenario(Scenario):
    """Test bidirectional echo multiple times."""

    @property
    def name(self) -> str:
        return "bidirectional_echo_multi"

    @property
    def description(self) -> str:
        return "Multiple bidirectional echo calls"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            # Test multiple peer calls in sequence
            test_values = [b"Test1", b"Test2", b"Test3"]

            for test_val in test_values:
                response = await host.call(TEST_CAPS["peer_echo"], test_val, "media:bytes")

                output = response.final_payload()
                assert output == test_val, f"Expected {test_val!r}, got {output!r}"

        return await self._timed_execute(run)
