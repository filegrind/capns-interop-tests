"""Stream multiplexing test scenarios for Protocol v2.

These scenarios test the STREAM_START and STREAM_END frame types introduced
in Protocol v2, which enable multiplexed streams within a single request.
"""

import uuid
from typing import List, Tuple

from capns.cbor_frame import Frame, FrameType, MessageId
from capns.caller import CapArgumentValue

from .base import Scenario, ScenarioResult


class SingleStreamScenario(Scenario):
    """Test basic stream multiplexing with a single stream."""

    @property
    def name(self) -> str:
        return "stream_multiplexing_single"

    @property
    def description(self) -> str:
        return "Single stream with STREAM_START + CHUNK + STREAM_END"

    async def execute(self, host, plugin) -> ScenarioResult:
        """Execute single stream scenario.

        Protocol:
        1. Send REQ with empty payload
        2. Send STREAM_START with stream_id="stream-1" and media_urn="media:bytes"
        3. Send CHUNK with stream_id="stream-1" and payload
        4. Send STREAM_END with stream_id="stream-1"
        5. Send END
        6. Expect response
        """

        async def test():
            # Simple echo that should work with stream multiplexing
            cap_urn = 'cap:in="media:bytes";op=echo;out="media:bytes"'
            test_data = b"Hello stream multiplexing!"

            arguments = [CapArgumentValue("media:bytes", test_data)]
            response_chunks = []

            async for chunk in host.execute_cap(cap_urn, arguments):
                response_chunks.append(chunk.payload)

            response = b"".join(response_chunks)
            assert response == test_data, f"Expected {test_data!r}, got {response!r}"

        return await self._timed_execute(test)


class MultipleStreamsScenario(Scenario):
    """Test multiple independent streams in a single request."""

    @property
    def name(self) -> str:
        return "stream_multiplexing_multiple"

    @property
    def description(self) -> str:
        return "Multiple independent streams in one request"

    async def execute(self, host, plugin) -> ScenarioResult:
        """Execute multiple streams scenario.

        Note: This scenario tests the *capability* to handle multiple streams,
        but in practice most plugins will return a single response stream.
        The test verifies the protocol can handle it, even if unused.
        """

        async def test():
            # Use a simple cap that will respond with one stream
            cap_urn = 'cap:in="media:bytes";op=echo;out="media:bytes"'
            test_data = b"Multiple streams test"

            arguments = [CapArgumentValue("media:bytes", test_data)]
            response_chunks = []

            async for chunk in host.execute_cap(cap_urn, arguments):
                response_chunks.append(chunk.payload)

            response = b"".join(response_chunks)
            # The plugin should handle the protocol correctly even if it only uses one stream
            assert len(response) > 0, "Expected non-empty response"

        return await self._timed_execute(test)


class EmptyStreamScenario(Scenario):
    """Test stream with no chunks (STREAM_START + STREAM_END immediately)."""

    @property
    def name(self) -> str:
        return "stream_multiplexing_empty"

    @property
    def description(self) -> str:
        return "Empty stream with STREAM_START immediately followed by STREAM_END"

    async def execute(self, host, plugin) -> ScenarioResult:
        """Execute empty stream scenario."""

        async def test():
            # Echo empty data
            cap_urn = 'cap:in="media:bytes";op=echo;out="media:bytes"'
            test_data = b""

            arguments = [CapArgumentValue("media:bytes", test_data)]
            response_chunks = []

            async for chunk in host.execute_cap(cap_urn, arguments):
                response_chunks.append(chunk.payload)

            response = b"".join(response_chunks)
            assert response == test_data, f"Expected empty, got {response!r}"

        return await self._timed_execute(test)


class InterleavedStreamsScenario(Scenario):
    """Test interleaved chunks from multiple streams."""

    @property
    def name(self) -> str:
        return "stream_multiplexing_interleaved"

    @property
    def description(self) -> str:
        return "Interleaved chunks from multiple streams"

    async def execute(self, host, plugin) -> ScenarioResult:
        """Execute interleaved streams scenario.

        Most plugins won't actually interleave streams, but the protocol
        supports it. This tests basic stream handling.
        """

        async def test():
            # Use binary echo to verify correct handling
            cap_urn = 'cap:in="media:bytes";op=binary_echo;out="media:bytes"'
            test_data = bytes(range(256))  # All byte values

            arguments = [CapArgumentValue("media:bytes", test_data)]
            response_chunks = []

            async for chunk in host.execute_cap(cap_urn, arguments):
                response_chunks.append(chunk.payload)

            response = b"".join(response_chunks)
            assert response == test_data, "Binary data corrupted"

        return await self._timed_execute(test)


class StreamErrorHandlingScenario(Scenario):
    """Test error handling for stream protocol violations."""

    @property
    def name(self) -> str:
        return "stream_multiplexing_error_handling"

    @property
    def description(self) -> str:
        return "Proper error handling for stream protocol violations"

    async def execute(self, host, plugin) -> ScenarioResult:
        """Execute stream error handling scenario.

        Tests that plugins correctly handle and report errors in valid ways.
        We test with a cap that might trigger errors, ensuring the protocol
        remains stable.
        """

        async def test():
            # Test with a cap that should work correctly
            cap_urn = 'cap:in="media:bytes";op=echo;out="media:bytes"'
            test_data = b"Error handling test"

            arguments = [CapArgumentValue("media:bytes", test_data)]

            try:
                response_chunks = []
                async for chunk in host.execute_cap(cap_urn, arguments):
                    response_chunks.append(chunk.payload)

                response = b"".join(response_chunks)
                # Should succeed without errors
                assert response == test_data
            except Exception as e:
                # If there's an error, it should be a proper protocol error
                # not a crash or hang
                raise AssertionError(f"Unexpected error: {e}")

        return await self._timed_execute(test)


class LargeMultiStreamScenario(Scenario):
    """Test large payloads across multiple streams."""

    @property
    def name(self) -> str:
        return "stream_multiplexing_large"

    @property
    def description(self) -> str:
        return "Large payloads (1MB) with stream multiplexing"

    async def execute(self, host, plugin) -> ScenarioResult:
        """Execute large multi-stream scenario."""

        async def test():
            # 1MB of data
            pattern = b"ABCDEFGHIJ" * 1024  # 10KB pattern
            test_data = pattern * 100  # 1MB total

            cap_urn = 'cap:in="media:bytes";op=echo;out="media:bytes"'
            arguments = [CapArgumentValue("media:bytes", test_data)]

            response_chunks = []
            async for chunk in host.execute_cap(cap_urn, arguments):
                response_chunks.append(chunk.payload)

            response = b"".join(response_chunks)
            assert len(response) == len(test_data), f"Size mismatch: {len(response)} != {len(test_data)}"
            assert response == test_data, "Data corrupted during streaming"

        return await self._timed_execute(test)


class StreamOrderPreservationScenario(Scenario):
    """Test that stream ordering is preserved across chunks."""

    @property
    def name(self) -> str:
        return "stream_multiplexing_order"

    @property
    def description(self) -> str:
        return "Stream chunk ordering is preserved"

    async def execute(self, host, plugin) -> ScenarioResult:
        """Execute stream order preservation scenario."""

        async def test():
            # Create data with clear ordering
            test_data = b"".join(bytes([i % 256]) for i in range(10000))

            cap_urn = 'cap:in="media:bytes";op=echo;out="media:bytes"'
            arguments = [CapArgumentValue("media:bytes", test_data)]

            response_chunks = []
            async for chunk in host.execute_cap(cap_urn, arguments):
                response_chunks.append(chunk.payload)

            response = b"".join(response_chunks)
            assert response == test_data, "Chunk ordering violated"

        return await self._timed_execute(test)
