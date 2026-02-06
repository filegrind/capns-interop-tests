"""Heartbeat test scenarios."""

import json
from .. import TEST_CAPS
from .base import Scenario, ScenarioResult


class BasicHeartbeatScenario(Scenario):
    """Test basic heartbeat during operation."""

    @property
    def name(self) -> str:
        return "basic_heartbeat"

    @property
    def description(self) -> str:
        return "Basic heartbeat ping/pong during operation"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            # Operation that takes 500ms
            duration_ms = 500
            input_json = json.dumps({"value": duration_ms}).encode()

            response = await host.call(TEST_CAPS["heartbeat_stress"], input_json, "media:json")

            output = response.final_payload()
            expected = f"stressed-{duration_ms}ms".encode()
            assert output == expected, f"Expected {expected!r}, got {output!r}"

        return await self._timed_execute(run)


class LongOperationHeartbeatScenario(Scenario):
    """Test heartbeat during long-running operation."""

    @property
    def name(self) -> str:
        return "long_operation_heartbeat"

    @property
    def description(self) -> str:
        return "Heartbeat during long operation (2 seconds)"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            # Operation that takes 2 seconds
            duration_ms = 2000
            input_json = json.dumps({"value": duration_ms}).encode()

            response = await host.call(TEST_CAPS["heartbeat_stress"], input_json, "media:json")

            output = response.final_payload()
            expected = f"stressed-{duration_ms}ms".encode()
            assert output == expected, f"Expected {expected!r}, got {output!r}"

        return await self._timed_execute(run)


class StatusUpdateScenario(Scenario):
    """Test status updates during processing."""

    @property
    def name(self) -> str:
        return "status_updates"

    @property
    def description(self) -> str:
        return "Receive status updates during processing"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            steps = 5
            input_json = json.dumps({"value": steps}).encode()

            response = await host.call(TEST_CAPS["with_status"], input_json, "media:json")

            # Final result
            output = response.final_payload()
            assert output == b"completed", f"Expected b'completed', got {output!r}"

            # Status updates should have been sent (logged but not validated here)
            # In a real implementation, we'd capture LOG frames

        return await self._timed_execute(run)
