"""Stream multiplexing interoperability tests for Protocol v2.

Tests that STREAM_START/STREAM_END frame types work correctly end-to-end.
In Protocol v2, ALL requests use stream multiplexing:
  REQ(empty) + STREAM_START + CHUNK(s) + STREAM_END + END

These tests verify the full path through all host x plugin combinations.
"""

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


@pytest.mark.timeout(30)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_single_stream(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """Test single stream: STREAM_START + CHUNK + STREAM_END + END roundtrip."""
    host = HostProcess(
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = host.start()

    try:
        test_data = b"Hello stream multiplexing!"
        req_id = make_req_id()
        send_request(writer, req_id, TEST_CAPS["echo"], test_data)
        output, frames = read_response(reader)

        assert output == test_data, (
            f"[{host_lang}/{plugin_lang}] single stream mismatch: {output!r}"
        )
    finally:
        host.stop()


@pytest.mark.timeout(30)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_multiple_streams(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """Test protocol correctly tracks stream state across multiple sequential requests."""
    host = HostProcess(
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = host.start()

    try:
        for i in range(3):
            test_data = f"stream-test-{i}".encode()
            req_id = make_req_id()
            send_request(writer, req_id, TEST_CAPS["echo"], test_data)
            output, frames = read_response(reader)

            assert output == test_data, (
                f"[{host_lang}/{plugin_lang}] request {i} mismatch: {output!r}"
            )
    finally:
        host.stop()


@pytest.mark.timeout(30)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_empty_stream(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """Test empty payload through stream multiplexing."""
    host = HostProcess(
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = host.start()

    try:
        test_data = b""
        req_id = make_req_id()
        send_request(writer, req_id, TEST_CAPS["echo"], test_data)
        output, frames = read_response(reader)

        assert output == test_data, (
            f"[{host_lang}/{plugin_lang}] empty stream mismatch: {output!r}"
        )
    finally:
        host.stop()


@pytest.mark.timeout(30)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_interleaved_streams(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """Test binary data integrity through stream multiplexing."""
    host = HostProcess(
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = host.start()

    try:
        test_data = bytes(range(256))
        req_id = make_req_id()
        send_request(writer, req_id, TEST_CAPS["binary_echo"], test_data)
        output, frames = read_response(reader)

        assert output == test_data, (
            f"[{host_lang}/{plugin_lang}] binary data corrupted through stream multiplexing"
        )
    finally:
        host.stop()


@pytest.mark.timeout(30)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_stream_error_handling(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """Test that stream protocol completes cleanly without errors."""
    host = HostProcess(
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = host.start()

    try:
        test_data = b"Error handling test"
        req_id = make_req_id()
        send_request(writer, req_id, TEST_CAPS["echo"], test_data)
        output, frames = read_response(reader)

        assert output == test_data, (
            f"[{host_lang}/{plugin_lang}] mismatch: {output!r}"
        )

        # Verify no ERR frames in response
        err_frames = [f for f in frames if f.frame_type == FrameType.ERR]
        assert len(err_frames) == 0, (
            f"[{host_lang}/{plugin_lang}] unexpected ERR frames in response"
        )
    finally:
        host.stop()


@pytest.mark.timeout(60)
def test_protocol_version_negotiation(relay_host_binaries, plugin_binaries):
    """Test that all host x plugin combinations negotiate Protocol v2 successfully."""
    results = {}
    for host_lang in SUPPORTED_HOST_LANGS:
        for plugin_lang in SUPPORTED_PLUGIN_LANGS:
            host = HostProcess(
                str(relay_host_binaries[host_lang]),
                [str(plugin_binaries[plugin_lang])],
            )
            reader, writer = host.start()
            try:
                test_data = b"v2-negotiation-test"
                req_id = make_req_id()
                send_request(writer, req_id, TEST_CAPS["echo"], test_data)
                output, frames = read_response(reader)
                results[f"{host_lang}/{plugin_lang}"] = (output == test_data)
            except Exception:
                results[f"{host_lang}/{plugin_lang}"] = False
            finally:
                host.stop()

    # All combinations must succeed
    for combo, passed in results.items():
        assert passed, f"{combo} failed Protocol v2 negotiation"
