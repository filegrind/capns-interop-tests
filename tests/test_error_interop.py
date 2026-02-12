"""Error handling interoperability tests.

Tests error propagation, invalid cap handling, malformed payloads, and
graceful shutdown across all host x plugin combinations.
"""

import json
import pytest

from capns.cbor_frame import FrameType
from capns_interop import TEST_CAPS
from capns_interop.framework.frame_test_helper import (
    HostProcess,
    make_req_id,
    send_request,
    send_simple_request,
    read_response,
    decode_cbor_response,
)

SUPPORTED_HOST_LANGS = ["python", "go", "rust", "swift"]
SUPPORTED_PLUGIN_LANGS = ["rust", "go", "python", "swift"]


@pytest.mark.timeout(30)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_throw_error(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """Test error propagation from plugin: plugin throws, host receives ERR frame."""
    host = HostProcess(
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = host.start()

    try:
        error_msg = "Test error message"
        input_json = json.dumps({"value": error_msg}).encode()
        req_id = make_req_id()
        send_request(writer, req_id, TEST_CAPS["throw_error"], input_json, media_urn="media:payment-error;json;textable;form=map")
        _, frames = read_response(reader)

        err_frames = [f for f in frames if f.frame_type == FrameType.ERR]
        assert len(err_frames) > 0, (
            f"[{host_lang}/{plugin_lang}] expected ERR frame, got: "
            f"{[f.frame_type for f in frames]}"
        )
    finally:
        host.stop()


@pytest.mark.timeout(30)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_invalid_cap(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """Test calling non-existent capability returns ERR from PluginHost."""
    host = HostProcess(
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = host.start()

    try:
        fake_cap = 'cap:in="media:void";op=nonexistent;out="media:void"'
        req_id = make_req_id()
        send_simple_request(writer, req_id, fake_cap)
        _, frames = read_response(reader)

        err_frames = [f for f in frames if f.frame_type == FrameType.ERR]
        assert len(err_frames) > 0, (
            f"[{host_lang}/{plugin_lang}] expected ERR for unknown cap, got: "
            f"{[f.frame_type for f in frames]}"
        )
    finally:
        host.stop()


@pytest.mark.timeout(30)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_malformed_payload(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """Test sending malformed JSON: plugin should return ERR."""
    host = HostProcess(
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = host.start()

    try:
        malformed_json = b"{invalid json"
        req_id = make_req_id()
        send_request(writer, req_id, TEST_CAPS["double"], malformed_json, media_urn="media:order-value;json;textable;form=map")
        _, frames = read_response(reader)

        err_frames = [f for f in frames if f.frame_type == FrameType.ERR]
        assert len(err_frames) > 0, (
            f"[{host_lang}/{plugin_lang}] expected ERR for malformed JSON, got: "
            f"{[f.frame_type for f in frames]}"
        )
    finally:
        host.stop()


@pytest.mark.timeout(30)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_graceful_shutdown(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """Test graceful shutdown: complete several requests then close cleanly."""
    host = HostProcess(
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = host.start()

    try:
        for i in range(3):
            test_input = f"test-{i}".encode()
            req_id = make_req_id()
            send_request(writer, req_id, TEST_CAPS["echo"], test_input)
            output, frames = read_response(reader)
            assert output == test_input, (
                f"[{host_lang}/{plugin_lang}] iteration {i}: {output!r} != {test_input!r}"
            )
    finally:
        host.stop()
