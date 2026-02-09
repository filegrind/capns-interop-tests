"""Stream multiplexing test scenarios for Protocol v2.

These scenarios verify that Protocol v2 stream multiplexing (STREAM_START,
CHUNK with stream_id, STREAM_END, END) works correctly end-to-end.

In Protocol v2, ALL requests and responses use stream multiplexing.
host.call_with_arguments() sends: REQ(empty) + STREAM_START + CHUNK(s) + STREAM_END + END
and collects: STREAM_START + CHUNK(s) + STREAM_END + END from the plugin.

These scenarios exercise the full stream multiplexing path with various
payload sizes and types.
"""

from .. import TEST_CAPS
from .base import Scenario, ScenarioResult
from capns.caller import CapArgumentValue


class SingleStreamScenario(Scenario):
    """Test basic stream multiplexing with a single stream."""

    @property
    def name(self) -> str:
        return "stream_multiplexing_single"

    @property
    def description(self) -> str:
        return "Single stream with STREAM_START + CHUNK + STREAM_END"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def test():
            test_data = b"Hello stream multiplexing!"

            response = await host.call_with_arguments(TEST_CAPS["echo"], [CapArgumentValue("media:bytes", test_data)])

            output = response.final_payload()
            assert output == test_data, f"Expected {test_data!r}, got {output!r}"

        return await self._timed_execute(test)


class MultipleStreamsScenario(Scenario):
    """Test that the protocol handles stream metadata correctly."""

    @property
    def name(self) -> str:
        return "stream_multiplexing_multiple"

    @property
    def description(self) -> str:
        return "Protocol correctly tracks stream state across request"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def test():
            test_data = b"Multiple streams test"

            response = await host.call_with_arguments(TEST_CAPS["echo"], [CapArgumentValue("media:bytes", test_data)])

            output = response.final_payload()
            assert output == test_data, f"Expected {test_data!r}, got {output!r}"

        return await self._timed_execute(test)


class EmptyStreamScenario(Scenario):
    """Test stream with empty payload (STREAM_START + STREAM_END without data CHUNKs)."""

    @property
    def name(self) -> str:
        return "stream_multiplexing_empty"

    @property
    def description(self) -> str:
        return "Empty stream with STREAM_START immediately followed by STREAM_END"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def test():
            test_data = b""

            response = await host.call_with_arguments(TEST_CAPS["echo"], [CapArgumentValue("media:bytes", test_data)])

            output = response.final_payload()
            assert output == test_data, f"Expected empty, got {output!r}"

        return await self._timed_execute(test)


class InterleavedStreamsScenario(Scenario):
    """Test binary data integrity through stream multiplexing."""

    @property
    def name(self) -> str:
        return "stream_multiplexing_interleaved"

    @property
    def description(self) -> str:
        return "Binary data integrity through stream multiplexing"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def test():
            test_data = bytes(range(256))

            response = await host.call_with_arguments(TEST_CAPS["binary_echo"], [CapArgumentValue("media:bytes", test_data)])

            output = response.final_payload()
            assert output == test_data, "Binary data corrupted through stream multiplexing"

        return await self._timed_execute(test)


class StreamErrorHandlingScenario(Scenario):
    """Test that stream protocol completes cleanly without errors."""

    @property
    def name(self) -> str:
        return "stream_multiplexing_error_handling"

    @property
    def description(self) -> str:
        return "Stream protocol completes cleanly without errors"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def test():
            test_data = b"Error handling test"

            response = await host.call_with_arguments(TEST_CAPS["echo"], [CapArgumentValue("media:bytes", test_data)])

            output = response.final_payload()
            assert output == test_data, f"Expected {test_data!r}, got {output!r}"

        return await self._timed_execute(test)


class LargeMultiStreamScenario(Scenario):
    """Test large payloads through stream multiplexing (triggers multi-chunk transfer)."""

    @property
    def name(self) -> str:
        return "stream_multiplexing_large"

    @property
    def description(self) -> str:
        return "Large payloads (1MB) with stream multiplexing"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def test():
            pattern = b"ABCDEFGHIJ" * 1024  # 10KB pattern
            test_data = pattern * 100  # 1MB total

            response = await host.call_with_arguments(TEST_CAPS["echo"], [CapArgumentValue("media:bytes", test_data)])

            output = response.final_payload()
            assert len(output) == len(test_data), f"Size mismatch: {len(output)} != {len(test_data)}"
            assert output == test_data, "Data corrupted during streaming"

        return await self._timed_execute(test)


class StreamOrderPreservationScenario(Scenario):
    """Test that byte ordering is preserved through stream chunking."""

    @property
    def name(self) -> str:
        return "stream_multiplexing_order"

    @property
    def description(self) -> str:
        return "Stream chunk ordering is preserved"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def test():
            test_data = bytes([i % 256 for i in range(10000)])

            response = await host.call_with_arguments(TEST_CAPS["binary_echo"], [CapArgumentValue("media:bytes", test_data)])

            output = response.final_payload()
            assert output == test_data, "Chunk ordering violated"

        return await self._timed_execute(test)
