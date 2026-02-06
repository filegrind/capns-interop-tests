"""Streaming test scenarios."""

import json
from .. import TEST_CAPS
from .base import Scenario, ScenarioResult


class StreamChunksScenario(Scenario):
    """Test streaming with multiple chunks."""

    @property
    def name(self) -> str:
        return "stream_chunks"

    @property
    def description(self) -> str:
        return "Stream multiple chunks with sequence numbers"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            chunk_count = 5
            input_json = json.dumps({"value": chunk_count}).encode()

            response = await host.call(TEST_CAPS["stream_chunks"], input_json, "media:json")

            # Should be streaming response
            assert response.is_streaming(), "Expected streaming response"

            # Collect all chunks
            chunks = []
            for chunk_data in response.chunks:
                if chunk_data.chunk_type == "data":
                    chunks.append(chunk_data.data.decode())

            # Verify we got all chunks in order
            assert len(chunks) >= chunk_count, f"Expected at least {chunk_count} chunks, got {len(chunks)}"

            for i in range(chunk_count):
                expected = f"chunk-{i}"
                assert expected in chunks, f"Missing chunk: {expected}"

        return await self._timed_execute(run)


class LargePayloadScenario(Scenario):
    """Test large payload transfer with chunking."""

    @property
    def name(self) -> str:
        return "large_payload"

    @property
    def description(self) -> str:
        return "Transfer large payload (1MB) with chunking"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            size = 1024 * 1024  # 1 MB
            input_json = json.dumps({"value": size}).encode()

            response = await host.call(TEST_CAPS["generate_large"], input_json, "media:json")

            output = response.final_payload()
            assert len(output) == size, f"Expected {size} bytes, got {len(output)}"

            # Verify pattern
            pattern = b"ABCDEFGH"
            for i in range(min(1000, size)):  # Check first 1000 bytes
                expected = pattern[i % len(pattern)]
                assert output[i] == expected, f"Pattern mismatch at byte {i}"

        return await self._timed_execute(run)


class BinaryDataScenario(Scenario):
    """Test binary data with all byte values."""

    @property
    def name(self) -> str:
        return "binary_data"

    @property
    def description(self) -> str:
        return "Transfer binary data with all 256 byte values"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            # Create data with all possible byte values
            test_data = bytes(range(256)) * 100  # 25.6 KB

            response = await host.call(TEST_CAPS["binary_echo"], test_data, "media:bytes")

            output = response.final_payload()
            assert output == test_data, f"Binary data mismatch (len: {len(output)} vs {len(test_data)})"

        return await self._timed_execute(run)


class StreamOrderingScenario(Scenario):
    """Test that streaming chunks arrive in order."""

    @property
    def name(self) -> str:
        return "stream_ordering"

    @property
    def description(self) -> str:
        return "Verify streaming chunks arrive in correct order"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            chunk_count = 20
            input_json = json.dumps({"value": chunk_count}).encode()

            response = await host.call(TEST_CAPS["stream_chunks"], input_json, "media:json")

            # Collect chunks in order
            chunks = []
            for chunk_data in response.chunks:
                if chunk_data.chunk_type == "data":
                    chunks.append(chunk_data.data.decode())

            # Verify ordering
            for i in range(chunk_count):
                expected = f"chunk-{i}"
                # Find this chunk
                found_idx = None
                for idx, chunk in enumerate(chunks):
                    if chunk == expected:
                        found_idx = idx
                        break

                assert found_idx is not None, f"Missing chunk: {expected}"

                # Verify it appears after previous chunks
                if i > 0:
                    prev_expected = f"chunk-{i-1}"
                    prev_idx = None
                    for idx, chunk in enumerate(chunks):
                        if chunk == prev_expected:
                            prev_idx = idx
                            break

                    if prev_idx is not None:
                        assert found_idx > prev_idx, f"Chunk {expected} arrived before {prev_expected}"

        return await self._timed_execute(run)
