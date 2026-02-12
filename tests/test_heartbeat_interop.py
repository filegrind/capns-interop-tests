"""Heartbeat interoperability tests.

Tests heartbeat handling during operations: basic heartbeat, long-running
operations, and status updates. Heartbeats are handled internally by the
relay host (never forwarded to the test).
"""

import json
import pytest

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
def test_basic_heartbeat(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """Test heartbeat during 500ms operation: plugin sends heartbeats, host handles locally."""
    host = HostProcess(
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = host.start()

    try:
        duration_ms = 500
        input_json = json.dumps({"value": duration_ms}).encode()
        req_id = make_req_id()
        send_request(writer, req_id, TEST_CAPS["heartbeat_stress"], input_json, media_urn="media:monitoring-duration-ms;json;textable;form=map")
        output, frames = read_response(reader)

        if isinstance(output, bytes):
            output_str = output.decode("utf-8", errors="replace")
        else:
            output_str = str(output)

        expected = f"stressed-{duration_ms}ms"
        assert output_str == expected, (
            f"[{host_lang}/{plugin_lang}] expected {expected!r}, got {output_str!r}"
        )
    finally:
        host.stop()


@pytest.mark.timeout(30)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_long_operation_heartbeat(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """Test heartbeat during 2-second operation: verifies no timeout/deadlock."""
    host = HostProcess(
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = host.start()

    try:
        duration_ms = 2000
        input_json = json.dumps({"value": duration_ms}).encode()
        req_id = make_req_id()
        send_request(writer, req_id, TEST_CAPS["heartbeat_stress"], input_json, media_urn="media:monitoring-duration-ms;json;textable;form=map")
        output, frames = read_response(reader)

        if isinstance(output, bytes):
            output_str = output.decode("utf-8", errors="replace")
        else:
            output_str = str(output)

        expected = f"stressed-{duration_ms}ms"
        assert output_str == expected, (
            f"[{host_lang}/{plugin_lang}] expected {expected!r}, got {output_str!r}"
        )
    finally:
        host.stop()


@pytest.mark.timeout(30)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_status_updates(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """Test status updates during processing: plugin sends LOG frames, verify response."""
    host = HostProcess(
        str(relay_host_binaries[host_lang]),
        [str(plugin_binaries[plugin_lang])],
    )
    reader, writer = host.start()

    try:
        steps = 5
        input_json = json.dumps({"value": steps}).encode()
        req_id = make_req_id()
        send_request(writer, req_id, TEST_CAPS["with_status"], input_json, media_urn="media:fulfillment-steps;json;textable;form=map")
        output, frames = read_response(reader)

        if isinstance(output, bytes):
            output_str = output.decode("utf-8", errors="replace")
        else:
            output_str = str(output)

        assert output_str == "completed", (
            f"[{host_lang}/{plugin_lang}] expected 'completed', got {output_str!r}"
        )
    finally:
        host.stop()
