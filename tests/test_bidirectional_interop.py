"""Bidirectional communication interoperability tests.

Tests plugin → host → plugin peer invocations. When a plugin makes a peer
request (e.g., calls host's echo), the PluginHost routes it to another plugin
instance (or back to the same one in a new request). This tests the full
3-tier path through all router x host x plugin combinations.

Architecture:
  Test (Engine) → Router → Host → Plugin

Where Router = RelaySwitch + RelayMaster (subprocess).
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

SUPPORTED_ROUTER_LANGS = ["rust"]  # TODO: Add go, python, swift when implemented
SUPPORTED_HOST_LANGS = ["rust"]  # Only relay hosts work with routers
SUPPORTED_PLUGIN_LANGS = ["rust", "go", "python", "swift"]


@pytest.mark.timeout(30)
@pytest.mark.parametrize("router_lang", SUPPORTED_ROUTER_LANGS)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_peer_echo(router_binaries, relay_host_binaries, plugin_binaries, router_lang, host_lang, plugin_lang):
    """Test plugin calling host's echo via PeerInvoker.

    Plugin receives peer_echo request, calls back to echo capability via
    PeerInvoker, and returns the result. The PluginHost routes the peer
    request to the plugin's own echo handler.

    Uses 3-tier architecture: Router (RelaySwitch) → Host (PluginHost) → Plugin.
    """
    router = RouterProcess(
        str(router_binaries[router_lang]),
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = router.start()

    try:
        test_input = b"Hello from peer!"
        req_id = make_req_id()
        send_request(writer, req_id, TEST_CAPS["peer_echo"], test_input)
        output, frames = read_response(reader)

        assert output == test_input, (
            f"[{router_lang}/{host_lang}/{plugin_lang}] peer echo mismatch: expected {test_input!r}, got {output!r}"
        )
    finally:
        router.stop()


@pytest.mark.timeout(30)
@pytest.mark.parametrize("router_lang", SUPPORTED_ROUTER_LANGS)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_nested_call(router_binaries, relay_host_binaries, plugin_binaries, router_lang, host_lang, plugin_lang):
    """Test nested invocation: plugin → host's double → back to plugin.

    Plugin receives nested_call with value 21, calls host's double (21 * 2 = 42),
    then doubles the result locally (42 * 2 = 84). The PluginHost routes the
    peer double request to the plugin's own double handler.

    Uses 3-tier architecture: Router (RelaySwitch) → Host (PluginHost) → Plugin.
    """
    router = RouterProcess(
        str(router_binaries[router_lang]),
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = router.start()

    try:
        value = 21
        input_json = json.dumps({"value": value}).encode()
        req_id = make_req_id()
        send_request(writer, req_id, TEST_CAPS["nested_call"], input_json, media_urn="media:order-value;json;textable;form=map")
        output, frames = read_response(reader)

        if isinstance(output, bytes):
            result = json.loads(output)
        else:
            result = output

        expected = value * 4  # Doubled twice: 21 * 2 * 2 = 84
        assert result == expected, (
            f"[{router_lang}/{host_lang}/{plugin_lang}] nested call mismatch: expected {expected}, got {result}"
        )
    finally:
        router.stop()


@pytest.mark.timeout(30)
@pytest.mark.parametrize("router_lang", SUPPORTED_ROUTER_LANGS)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_bidirectional_echo_multi(router_binaries, relay_host_binaries, plugin_binaries, router_lang, host_lang, plugin_lang):
    """Test multiple sequential bidirectional echo calls.

    Uses 3-tier architecture: Router (RelaySwitch) → Host (PluginHost) → Plugin.
    """
    router = RouterProcess(
        str(router_binaries[router_lang]),
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = router.start()

    try:
        test_values = [b"Test1", b"Test2", b"Test3"]
        for test_val in test_values:
            req_id = make_req_id()
            send_request(writer, req_id, TEST_CAPS["peer_echo"], test_val)
            output, frames = read_response(reader)

            assert output == test_val, (
                f"[{router_lang}/{host_lang}/{plugin_lang}] peer echo mismatch: "
                f"expected {test_val!r}, got {output!r}"
            )
    finally:
        router.stop()
