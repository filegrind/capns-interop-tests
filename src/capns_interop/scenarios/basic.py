"""Basic test scenarios (echo, double, binary)."""

import json
from .. import TEST_CAPS
from .base import Scenario, ScenarioResult
from capns.cap.caller import CapArgumentValue


class EchoScenario(Scenario):
    """Test simple echo capability."""

    @property
    def name(self) -> str:
        return "echo"

    @property
    def description(self) -> str:
        return "Simple string echo"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            test_input = b"Hello, World!"
            response = await host.call_with_arguments(TEST_CAPS["echo"], [CapArgumentValue("media:bytes", test_input)])

            # Get the final payload
            output = response.final_payload()
            assert output == test_input, f"Expected {test_input!r}, got {output!r}"

        return await self._timed_execute(run)


class DoubleScenario(Scenario):
    """Test number doubling capability."""

    @property
    def name(self) -> str:
        return "double"

    @property
    def description(self) -> str:
        return "Double a number"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            test_input = 42
            input_json = json.dumps({"value": test_input}).encode()

            response = await host.call_with_arguments(TEST_CAPS["double"], [CapArgumentValue("media:json", input_json)])

            output = response.final_payload()
            result_value = json.loads(output)
            expected = test_input * 2

            assert (
                result_value == expected
            ), f"Expected {expected}, got {result_value}"

        return await self._timed_execute(run)


class BinaryEchoScenario(Scenario):
    """Test binary data echo."""

    @property
    def name(self) -> str:
        return "binary_echo"

    @property
    def description(self) -> str:
        return "Echo binary data"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            # Test with various binary patterns
            test_data = bytes(range(256))  # All byte values

            response = await host.call_with_arguments(TEST_CAPS["binary_echo"], [CapArgumentValue("media:bytes", test_data)])

            output = response.final_payload()
            assert output == test_data, f"Binary data mismatch"

        return await self._timed_execute(run)


class GetManifestScenario(Scenario):
    """Test manifest retrieval."""

    @property
    def name(self) -> str:
        return "get_manifest"

    @property
    def description(self) -> str:
        return "Retrieve plugin manifest"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            manifest_bytes = host.get_plugin_manifest()
            assert manifest_bytes is not None, "No manifest available"

            # Parse the manifest JSON
            manifest = json.loads(manifest_bytes)
            assert "name" in manifest, "Manifest missing 'name' field"
            assert "version" in manifest, "Manifest missing 'version' field"
            assert "caps" in manifest, "Manifest missing 'caps' field"
            assert len(manifest["caps"]) >= 13, "Manifest missing test capabilities"

        return await self._timed_execute(run)
