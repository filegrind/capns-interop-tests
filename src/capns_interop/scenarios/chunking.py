"""Incoming request chunking test scenarios.

These scenarios test the host sending LARGE data TO plugins via chunked requests
(REQ + CHUNK* + END protocol), ensuring plugins can receive and process chunked incoming data.
"""

import json
import hashlib
from .. import TEST_CAPS
from .base import Scenario, ScenarioResult
from capns.caller import CapArgumentValue


class LargeIncomingPayloadScenario(Scenario):
    """Test plugin receiving large incoming payload (1MB) from host."""

    @property
    def name(self) -> str:
        return "large_incoming_payload"

    @property
    def description(self) -> str:
        return "Host sends 1MB to plugin via chunked request"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            # Generate 1MB of test data
            size = 1024 * 1024
            pattern = b"ABCDEFGH"
            test_data = (pattern * (size // len(pattern) + 1))[:size]

            # Send large payload to plugin (triggers automatic chunking)
            response = await host.call_with_arguments(TEST_CAPS["process_large"], [CapArgumentValue("media:bytes", test_data)])

            # Plugin should return size + checksum
            output = response.final_payload()
            result = json.loads(output.decode())

            assert result["size"] == size, f"Size mismatch: {result['size']} vs {size}"

            # Verify checksum
            expected_checksum = hashlib.sha256(test_data).hexdigest()
            assert result["checksum"] == expected_checksum, \
                f"Checksum mismatch: {result['checksum']} vs {expected_checksum}"

        return await self._timed_execute(run)


class MassiveIncomingPayloadScenario(Scenario):
    """Test plugin receiving massive payload (10MB) with multiple chunks."""

    @property
    def name(self) -> str:
        return "massive_incoming_payload"

    @property
    def description(self) -> str:
        return "Host sends 10MB to plugin via heavily chunked request"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            # Generate 10MB of test data
            size = 10 * 1024 * 1024
            pattern = b"0123456789ABCDEF"
            test_data = (pattern * (size // len(pattern) + 1))[:size]

            # Send massive payload (will be split into many chunks)
            response = await host.call_with_arguments(TEST_CAPS["process_large"], [CapArgumentValue("media:bytes", test_data)])

            # Plugin should return size + checksum
            output = response.final_payload()
            result = json.loads(output.decode())

            assert result["size"] == size, f"Size mismatch: {result['size']} vs {size}"

            # Verify checksum
            expected_checksum = hashlib.sha256(test_data).hexdigest()
            assert result["checksum"] == expected_checksum, \
                f"Checksum mismatch: {result['checksum']} vs {expected_checksum}"

        return await self._timed_execute(run)


class BinaryIncomingScenario(Scenario):
    """Test plugin receiving binary data with all byte values."""

    @property
    def name(self) -> str:
        return "binary_incoming"

    @property
    def description(self) -> str:
        return "Host sends binary data (all 256 byte values) via chunked request"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            # Create data with all possible byte values repeated
            test_data = bytes(range(256)) * 1024  # 256 KB with all byte values

            # Send binary data to plugin
            response = await host.call_with_arguments(TEST_CAPS["verify_binary"], [CapArgumentValue("media:bytes", test_data)])

            # Plugin should verify and return "ok"
            output = response.final_payload().decode()
            assert output == "ok", f"Binary verification failed: {output}"

        return await self._timed_execute(run)


class HashIncomingScenario(Scenario):
    """Test plugin hashing large incoming data."""

    @property
    def name(self) -> str:
        return "hash_incoming"

    @property
    def description(self) -> str:
        return "Host sends 5MB, plugin computes hash of incoming chunks"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            # Generate 5MB of test data
            size = 5 * 1024 * 1024
            test_data = bytes([i % 256 for i in range(size)])

            # Send to plugin for hashing
            response = await host.call_with_arguments(TEST_CAPS["hash_incoming"], [CapArgumentValue("media:bytes", test_data)])

            # Plugin should return SHA256 hash
            output = response.final_payload().decode()
            expected_hash = hashlib.sha256(test_data).hexdigest()

            assert output == expected_hash, f"Hash mismatch: {output} vs {expected_hash}"

        return await self._timed_execute(run)


class MultipleIncomingScenario(Scenario):
    """Test multiple large incoming requests in sequence."""

    @property
    def name(self) -> str:
        return "multiple_incoming"

    @property
    def description(self) -> str:
        return "Host sends 3 large payloads sequentially (1MB each)"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            size = 1024 * 1024  # 1MB each

            for i in range(3):
                # Generate unique data for each request
                test_data = bytes([i] * size)

                # Send to plugin
                response = await host.call_with_arguments(TEST_CAPS["process_large"], [CapArgumentValue("media:bytes", test_data)])

                # Verify response
                output = response.final_payload()
                result = json.loads(output.decode())

                assert result["size"] == size, f"Request {i}: Size mismatch"

                expected_checksum = hashlib.sha256(test_data).hexdigest()
                assert result["checksum"] == expected_checksum, \
                    f"Request {i}: Checksum mismatch"

        return await self._timed_execute(run)


class ZeroLengthIncomingScenario(Scenario):
    """Test plugin receiving empty payload."""

    @property
    def name(self) -> str:
        return "zero_length_incoming"

    @property
    def description(self) -> str:
        return "Host sends empty payload to plugin"

    async def execute(self, host, plugin) -> ScenarioResult:
        async def run():
            test_data = b""

            response = await host.call_with_arguments(TEST_CAPS["process_large"], [CapArgumentValue("media:bytes", test_data)])

            output = response.final_payload()
            result = json.loads(output.decode())

            assert result["size"] == 0, f"Size should be 0, got {result['size']}"

            expected_checksum = hashlib.sha256(test_data).hexdigest()
            assert result["checksum"] == expected_checksum, "Empty checksum mismatch"

        return await self._timed_execute(run)
