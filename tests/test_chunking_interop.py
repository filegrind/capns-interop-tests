"""Incoming request chunking interoperability tests.

Tests host sending large payloads TO plugins via chunked requests.
The relay host's PluginHost automatically chunks large arguments into
REQ(empty) + CHUNK* + END sequences.
"""

import hashlib
import json
import pytest

from capns.cbor_frame import FrameType
from capns_interop import TEST_CAPS
from capns_interop.framework.frame_test_helper import (
    HostProcess,
    make_req_id,
    send_request,
    read_response,
    decode_cbor_response,
)

SUPPORTED_HOST_LANGS = ["python", "go", "rust", "swift"]
SUPPORTED_PLUGIN_LANGS = ["rust", "go", "python", "swift"]


@pytest.mark.timeout(60)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_large_incoming_payload(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """Test plugin receiving 1MB payload: host sends large data, plugin returns size + checksum."""
    host = HostProcess(
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = host.start()

    try:
        size = 1024 * 1024
        pattern = b"ABCDEFGH"
        test_data = (pattern * (size // len(pattern) + 1))[:size]

        req_id = make_req_id()
        send_request(writer, req_id, TEST_CAPS["process_large"], test_data)
        output, frames = read_response(reader, timeout_frames=500)

        if isinstance(output, bytes):
            result = json.loads(output)
        else:
            result = output

        assert result["size"] == size, (
            f"[{host_lang}/{plugin_lang}] size mismatch: {result['size']} vs {size}"
        )

        expected_checksum = hashlib.sha256(test_data).hexdigest()
        assert result["checksum"] == expected_checksum, (
            f"[{host_lang}/{plugin_lang}] checksum mismatch"
        )
    finally:
        host.stop()


@pytest.mark.timeout(120)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_massive_incoming_payload(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """Test plugin receiving 10MB payload with heavy chunking."""
    host = HostProcess(
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = host.start()

    try:
        size = 10 * 1024 * 1024
        pattern = b"0123456789ABCDEF"
        test_data = (pattern * (size // len(pattern) + 1))[:size]

        req_id = make_req_id()
        send_request(writer, req_id, TEST_CAPS["process_large"], test_data)
        output, frames = read_response(reader, timeout_frames=5000)

        if isinstance(output, bytes):
            result = json.loads(output)
        else:
            result = output

        assert result["size"] == size, (
            f"[{host_lang}/{plugin_lang}] size mismatch: {result['size']} vs {size}"
        )

        expected_checksum = hashlib.sha256(test_data).hexdigest()
        assert result["checksum"] == expected_checksum, (
            f"[{host_lang}/{plugin_lang}] checksum mismatch"
        )
    finally:
        host.stop()


@pytest.mark.timeout(60)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_binary_incoming(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """Test plugin receiving binary data with all byte values."""
    host = HostProcess(
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = host.start()

    try:
        test_data = bytes(range(256)) * 1024  # 256 KB
        req_id = make_req_id()
        send_request(writer, req_id, TEST_CAPS["verify_binary"], test_data)
        output, frames = read_response(reader, timeout_frames=500)

        if isinstance(output, bytes):
            output_str = output.decode("utf-8", errors="replace")
        else:
            output_str = str(output)

        assert output_str == "ok", (
            f"[{host_lang}/{plugin_lang}] binary verification failed: {output_str}"
        )
    finally:
        host.stop()


@pytest.mark.timeout(90)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_hash_incoming(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """Test plugin hashing 5MB incoming payload."""
    host = HostProcess(
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = host.start()

    try:
        size = 5 * 1024 * 1024
        test_data = bytes([i % 256 for i in range(size)])
        req_id = make_req_id()
        send_request(writer, req_id, TEST_CAPS["hash_incoming"], test_data)
        output, frames = read_response(reader, timeout_frames=2000)

        if isinstance(output, bytes):
            output_str = output.decode("utf-8", errors="replace")
        else:
            output_str = str(output)

        expected_hash = hashlib.sha256(test_data).hexdigest()
        assert output_str == expected_hash, (
            f"[{host_lang}/{plugin_lang}] hash mismatch: {output_str} vs {expected_hash}"
        )
    finally:
        host.stop()


@pytest.mark.timeout(120)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_multiple_incoming(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """Test multiple large incoming requests in sequence (3 x 1MB)."""
    host = HostProcess(
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = host.start()

    try:
        size = 1024 * 1024
        for i in range(3):
            test_data = bytes([i] * size)
            req_id = make_req_id()
            send_request(writer, req_id, TEST_CAPS["process_large"], test_data)
            output, frames = read_response(reader, timeout_frames=500)

            if isinstance(output, bytes):
                result = json.loads(output)
            else:
                result = output

            assert result["size"] == size, (
                f"[{host_lang}/{plugin_lang}] request {i}: size mismatch"
            )

            expected_checksum = hashlib.sha256(test_data).hexdigest()
            assert result["checksum"] == expected_checksum, (
                f"[{host_lang}/{plugin_lang}] request {i}: checksum mismatch"
            )
    finally:
        host.stop()


@pytest.mark.timeout(30)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_zero_length_incoming(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """Test plugin receiving empty payload."""
    host = HostProcess(
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = host.start()

    try:
        req_id = make_req_id()
        send_request(writer, req_id, TEST_CAPS["process_large"], b"")
        output, frames = read_response(reader)

        if isinstance(output, bytes):
            result = json.loads(output)
        else:
            result = output

        assert result["size"] == 0, (
            f"[{host_lang}/{plugin_lang}] size should be 0, got {result['size']}"
        )

        expected_checksum = hashlib.sha256(b"").hexdigest()
        assert result["checksum"] == expected_checksum, (
            f"[{host_lang}/{plugin_lang}] empty checksum mismatch"
        )
    finally:
        host.stop()
