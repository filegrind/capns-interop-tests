"""Basic interoperability tests.

Tests echo, double, binary_echo, and get_manifest capabilities across all
router x host x plugin language combinations using raw CBOR frames.

Architecture:
    Test (Engine) → Router (RelaySwitch) → Host (PluginHost) → Plugin
"""

import json
import pytest

from capns_interop import TEST_CAPS
from capns_interop.framework.frame_test_helper import (
    make_req_id,
    send_request,
    read_response,
    decode_cbor_response,
)
from capns_interop.framework.router_process import RouterProcess

SUPPORTED_ROUTER_LANGS = ["rust", "swift"]
SUPPORTED_HOST_LANGS = ["rust", "swift"]
SUPPORTED_PLUGIN_LANGS = ["rust", "go", "python", "swift"]


@pytest.mark.timeout(30)
@pytest.mark.parametrize("router_lang", SUPPORTED_ROUTER_LANGS)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_echo(router_binaries, relay_host_binaries, plugin_binaries, router_lang, host_lang, plugin_lang):
    """Test echo capability: send bytes, receive identical bytes back."""
    router = RouterProcess(
        str(router_binaries[router_lang]),
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = router.start()

    try:
        test_input = b"Hello, World!"
        req_id = make_req_id()
        send_request(writer, req_id, TEST_CAPS["echo"], test_input)
        output, frames = read_response(reader)

        assert output == test_input, (
            f"[{router_lang}/{host_lang}/{plugin_lang}] echo mismatch: expected {test_input!r}, got {output!r}"
        )
    finally:
        router.stop()


@pytest.mark.timeout(30)
@pytest.mark.parametrize("router_lang", SUPPORTED_ROUTER_LANGS)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_double(router_binaries, relay_host_binaries, plugin_binaries, router_lang, host_lang, plugin_lang):
    """Test double capability: send number, receive doubled result."""
    router = RouterProcess(
        str(router_binaries[router_lang]),
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = router.start()

    try:
        test_value = 42
        input_json = json.dumps({"value": test_value}).encode()
        req_id = make_req_id()
        send_request(writer, req_id, TEST_CAPS["double"], input_json, media_urn="media:order-value;json;textable;form=map")
        output, frames = read_response(reader)

        # Plugin can return integer directly (CBOR) or JSON bytes
        if isinstance(output, int):
            result = output
        elif isinstance(output, bytes):
            result = json.loads(output)
        else:
            result = output

        expected = test_value * 2
        assert result == expected, (
            f"[{router_lang}/{host_lang}/{plugin_lang}] double mismatch: expected {expected}, got {result}"
        )
    finally:
        router.stop()


@pytest.mark.timeout(30)
@pytest.mark.parametrize("router_lang", SUPPORTED_ROUTER_LANGS)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_binary_echo(router_binaries, relay_host_binaries, plugin_binaries, router_lang, host_lang, plugin_lang):
    """Test binary echo: send all 256 byte values, receive identical data back."""
    router = RouterProcess(
        str(router_binaries[router_lang]),
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = router.start()

    try:
        test_data = bytes(range(256))
        req_id = make_req_id()
        send_request(writer, req_id, TEST_CAPS["binary_echo"], test_data)
        output, frames = read_response(reader)

        assert output == test_data, (
            f"[{router_lang}/{host_lang}/{plugin_lang}] binary echo mismatch (len: {len(output)} vs {len(test_data)})"
        )
    finally:
        router.stop()


@pytest.mark.timeout(30)
@pytest.mark.parametrize("router_lang", SUPPORTED_ROUTER_LANGS)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_get_manifest(router_binaries, relay_host_binaries, plugin_binaries, router_lang, host_lang, plugin_lang):
    """Test manifest retrieval via get_manifest cap."""
    router = RouterProcess(
        str(router_binaries[router_lang]),
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = router.start()

    try:
        req_id = make_req_id()
        send_request(writer, req_id, TEST_CAPS["get_manifest"], b"", media_urn="media:void")
        output, frames = read_response(reader)

        # Parse the manifest JSON
        manifest = json.loads(output)

        assert "name" in manifest, f"[{router_lang}/{host_lang}/{plugin_lang}] manifest missing 'name'"
        assert "version" in manifest, f"[{router_lang}/{host_lang}/{plugin_lang}] manifest missing 'version'"
        assert "caps" in manifest, f"[{router_lang}/{host_lang}/{plugin_lang}] manifest missing 'caps'"
        assert len(manifest["caps"]) >= 10, (
            f"[{router_lang}/{host_lang}/{plugin_lang}] manifest has {len(manifest['caps'])} caps, expected >= 10"
        )
    finally:
        router.stop()
