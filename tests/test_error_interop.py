"""Error handling interoperability tests.

Tests error propagation, invalid cap handling, malformed payloads, and
graceful shutdown across all router x host x plugin combinations.

Architecture:
    Test (Engine) → Router (RelaySwitch) → Host (PluginHost) → Plugin
"""

import json
import pytest

from capns.cbor_frame import FrameType
from capns_interop import TEST_CAPS
from capns_interop.framework.frame_test_helper import (
    make_req_id,
    send_request,
    send_simple_request,
    read_response,
    decode_cbor_response,
)
from capns_interop.framework.router_process import RouterProcess

SUPPORTED_ROUTER_LANGS = ["rust"]
SUPPORTED_HOST_LANGS = ["rust"]
SUPPORTED_PLUGIN_LANGS = ["rust", "go", "python", "swift"]


@pytest.mark.timeout(30)
@pytest.mark.parametrize("router_lang", SUPPORTED_ROUTER_LANGS)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_throw_error(router_binaries, relay_host_binaries, plugin_binaries, router_lang, host_lang, plugin_lang):
    """Test error propagation from plugin: plugin throws, host receives ERR frame."""
    router = RouterProcess(
        str(router_binaries[router_lang]),
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = router.start()

    try:
        error_msg = "Test error message"
        input_json = json.dumps({"value": error_msg}).encode()
        req_id = make_req_id()
        send_request(writer, req_id, TEST_CAPS["throw_error"], input_json, media_urn="media:payment-error;json;textable;form=map")
        _, frames = read_response(reader)

        err_frames = [f for f in frames if f.frame_type == FrameType.ERR]
        assert len(err_frames) > 0, (
            f"[{router_lang}/{host_lang}/{plugin_lang}] expected ERR frame, got: "
            f"{[f.frame_type for f in frames]}"
        )
    finally:
        router.stop()


@pytest.mark.timeout(30)
@pytest.mark.parametrize("router_lang", SUPPORTED_ROUTER_LANGS)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_invalid_cap(router_binaries, relay_host_binaries, plugin_binaries, router_lang, host_lang, plugin_lang):
    """Test calling non-existent capability returns ERR from PluginHost."""
    router = RouterProcess(
        str(router_binaries[router_lang]),
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = router.start()

    try:
        fake_cap = 'cap:in="media:void";op=nonexistent;out="media:void"'
        req_id = make_req_id()
        send_request(writer, req_id, fake_cap, b"", media_urn="media:void")
        _, frames = read_response(reader)

        err_frames = [f for f in frames if f.frame_type == FrameType.ERR]
        assert len(err_frames) > 0, (
            f"[{router_lang}/{host_lang}/{plugin_lang}] expected ERR for unknown cap, got: "
            f"{[f.frame_type for f in frames]}"
        )
    finally:
        router.stop()


@pytest.mark.timeout(30)
@pytest.mark.parametrize("router_lang", SUPPORTED_ROUTER_LANGS)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_malformed_payload(router_binaries, relay_host_binaries, plugin_binaries, router_lang, host_lang, plugin_lang):
    """Test sending malformed JSON: plugin should return ERR."""
    router = RouterProcess(
        str(router_binaries[router_lang]),
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = router.start()

    try:
        malformed_json = b"{invalid json"
        req_id = make_req_id()
        send_request(writer, req_id, TEST_CAPS["double"], malformed_json, media_urn="media:order-value;json;textable;form=map")
        _, frames = read_response(reader)

        err_frames = [f for f in frames if f.frame_type == FrameType.ERR]
        assert len(err_frames) > 0, (
            f"[{router_lang}/{host_lang}/{plugin_lang}] expected ERR for malformed JSON, got: "
            f"{[f.frame_type for f in frames]}"
        )
    finally:
        router.stop()


@pytest.mark.timeout(30)
@pytest.mark.parametrize("router_lang", SUPPORTED_ROUTER_LANGS)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_graceful_shutdown(router_binaries, relay_host_binaries, plugin_binaries, router_lang, host_lang, plugin_lang):
    """Test graceful shutdown: complete several requests then close cleanly."""
    router = RouterProcess(
        str(router_binaries[router_lang]),
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = router.start()

    try:
        for i in range(3):
            test_input = f"test-{i}".encode()
            req_id = make_req_id()
            send_request(writer, req_id, TEST_CAPS["echo"], test_input)
            output, frames = read_response(reader)
            assert output == test_input, (
                f"[{router_lang}/{host_lang}/{plugin_lang}] iteration {i}: {output!r} != {test_input!r}"
            )
    finally:
        router.stop()
