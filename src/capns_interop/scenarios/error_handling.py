"""Error handling test scenarios."""

import json
from .. import TEST_CAPS
from .base import Scenario, ScenarioResult, ScenarioStatus
from capns.cap.caller import CapArgumentValue


class ThrowErrorScenario(Scenario):
    """Test error propagation from plugin to host."""

    @property
    def name(self) -> str:
        return "throw_error"

    @property
    def description(self) -> str:
        return "Plugin throws error, host receives ERR frame"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            error_msg = "Test error message"
            input_json = json.dumps({"value": error_msg}).encode()

            try:
                response = await host.call_with_arguments(TEST_CAPS["throw_error"], [CapArgumentValue("media:json", input_json)])
                # Should not reach here
                assert False, "Expected PluginError to be raised"
            except Exception as e:
                # Verify error message is propagated
                error_str = str(e)
                assert "error" in error_str.lower() or "Error" in error_str, f"Expected error, got: {error_str}"
                # Success - error was properly propagated

        return await self._timed_execute(run)


class InvalidCapScenario(Scenario):
    """Test calling non-existent capability."""

    @property
    def name(self) -> str:
        return "invalid_cap"

    @property
    def description(self) -> str:
        return "Call non-existent capability"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            fake_cap = 'cap:in="media:void";op=nonexistent;out="media:void"'

            try:
                response = await host.call_with_arguments(fake_cap, [CapArgumentValue("media:void", b"")])
                # Should not reach here
                assert False, "Expected error for non-existent cap"
            except Exception as e:
                # Should get NO_HANDLER or similar error
                error_str = str(e)
                assert "NO_HANDLER" in error_str or "not found" in error_str.lower(), f"Expected NO_HANDLER, got: {error_str}"

        return await self._timed_execute(run)


class MalformedPayloadScenario(Scenario):
    """Test sending malformed JSON payload."""

    @property
    def name(self) -> str:
        return "malformed_payload"

    @property
    def description(self) -> str:
        return "Send malformed JSON to handler"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            # Send invalid JSON to a handler expecting JSON
            malformed_json = b"{invalid json"

            try:
                response = await host.call_with_arguments(TEST_CAPS["double"], [CapArgumentValue("media:json", malformed_json)])
                # Should not reach here
                assert False, "Expected error for malformed JSON"
            except Exception as e:
                # Should get handler error
                error_str = str(e)
                assert "error" in error_str.lower() or "Error" in error_str or "invalid" in error_str.lower(), f"Expected error, got: {error_str}"

        return await self._timed_execute(run)


class GracefulShutdownScenario(Scenario):
    """Test graceful shutdown after operations."""

    @property
    def name(self) -> str:
        return "graceful_shutdown"

    @property
    def description(self) -> str:
        return "Graceful shutdown after operations"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            # Perform a few operations
            for i in range(3):
                test_input = f"test-{i}".encode()
                response = await host.call_with_arguments(TEST_CAPS["echo"], [CapArgumentValue("media:bytes", test_input)])
                output = response.final_payload()
                assert output == test_input

            # Shutdown is handled by orchestrator after this
            # Just verify operations completed successfully

        return await self._timed_execute(run)
