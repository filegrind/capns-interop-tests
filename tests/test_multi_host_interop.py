"""Multi-plugin host interop tests.

Tests the PluginHost routing with multiple plugins across language combinations.
Each relay host binary (Rust/Go/Python/Swift) manages multiple plugin binaries
and routes requests by cap URN.

Architecture:
    Python test ←CBOR frames→ relay_host binary (PluginHost) → plugin1
                                                               → plugin2

The test writes raw CBOR frames (REQ/STREAM_START/CHUNK/STREAM_END/END) to the
relay host's stdin, and reads response frames from stdout.
"""

import hashlib
import os
import subprocess
import sys
import time

import pytest

# Add capns-py to path for frame I/O
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_project_root, "..", "capns-py", "src"))
sys.path.insert(0, os.path.join(_project_root, "..", "tagged-urn-py", "src"))

from capns.cbor_frame import Frame, FrameType, MessageId
from capns.cbor_io import FrameReader, FrameWriter

# Cap URNs matching the test plugin's registered capabilities
ECHO_CAP = 'cap:in="media:string;textable;form=scalar";op=echo;out="media:string;textable;form=scalar"'
BINARY_ECHO_CAP = 'cap:in="media:bytes";op=binary_echo;out="media:bytes"'
DOUBLE_CAP = 'cap:in="media:number;form=scalar";op=double;out="media:number;form=scalar"'

SUPPORTED_HOST_LANGS = ["python", "go", "rust", "swift"]
SUPPORTED_PLUGIN_LANGS = ["rust", "go", "python", "swift"]


def _build_env():
    env = os.environ.copy()
    env["PYTHON_EXECUTABLE"] = sys.executable
    python_paths = [
        os.path.join(_project_root, "..", "capns-py", "src"),
        os.path.join(_project_root, "..", "tagged-urn-py", "src"),
    ]
    if "PYTHONPATH" in env:
        python_paths.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = ":".join(python_paths)
    return env


def _start_relay_host(relay_host_binary, plugin_paths, relay=False):
    """Start a relay host binary with given plugins, return (proc, reader, writer)."""
    cmd = []
    binary = str(relay_host_binary)
    if binary.endswith(".py"):
        cmd = [sys.executable, binary]
    else:
        cmd = [binary]

    if relay:
        cmd.append("--relay")

    for p in plugin_paths:
        cmd.extend(["--spawn", str(p)])

    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=_build_env(),
    )

    reader = FrameReader(proc.stdout)
    writer = FrameWriter(proc.stdin)
    return proc, reader, writer


def _send_request(writer, cap_urn, payload, media_urn="media:bytes"):
    """Send a complete request and return the req_id used."""
    req_id = MessageId.new_uuid()
    writer.write(Frame.req(req_id, cap_urn, b"", "application/octet-stream"))
    writer.write(Frame.stream_start(req_id, "arg-0", media_urn))
    writer.write(Frame.chunk(req_id, "arg-0", 0, payload))
    writer.write(Frame.stream_end(req_id, "arg-0"))
    writer.write(Frame.end(req_id))
    return req_id


def _read_response(reader, max_frames=50):
    """Read response frames until END or ERR. Returns (chunk_data, all_frames)."""
    chunks = bytearray()
    frames = []
    for _ in range(max_frames):
        frame = reader.read()
        if frame is None:
            break
        frames.append(frame)
        if frame.frame_type == FrameType.CHUNK and frame.payload:
            chunks.extend(frame.payload)
        if frame.frame_type in (FrameType.END, FrameType.ERR):
            break
    return bytes(chunks), frames


def _decode_cbor_bytes(raw):
    """Decode a CBOR byteString from response data."""
    import cbor2
    try:
        return cbor2.loads(raw)
    except Exception:
        return raw


def _stop(proc, timeout=5):
    try:
        proc.stdin.close()
    except Exception:
        pass
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2)


# ============================================================
# Test: Two plugins with distinct caps route independently
# ============================================================

@pytest.mark.timeout(30)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_two_plugin_routing(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """Route requests to two instances of the same plugin, verify both respond."""
    host_binary = relay_host_binaries[host_lang]
    plugin_binary = plugin_binaries[plugin_lang]

    # Spawn host with the same plugin twice - both handle the same caps
    # but we verify both get attached successfully
    proc, reader, writer = _start_relay_host(host_binary, [str(plugin_binary), str(plugin_binary)])

    try:
        # Send echo request
        req_id = _send_request(writer, ECHO_CAP, b"hello-routing")
        raw, frames = _read_response(reader)
        decoded = _decode_cbor_bytes(raw)

        assert decoded == b"hello-routing", (
            f"[{host_lang}/{plugin_lang}] echo mismatch: {decoded!r}"
        )

        # Send binary_echo request (different cap, same plugin)
        req_id2 = _send_request(writer, BINARY_ECHO_CAP, bytes(range(256)))
        raw2, frames2 = _read_response(reader)
        decoded2 = _decode_cbor_bytes(raw2)

        assert decoded2 == bytes(range(256)), (
            f"[{host_lang}/{plugin_lang}] binary_echo data mismatch"
        )
    finally:
        _stop(proc)


# ============================================================
# Test: Request to unknown cap returns ERR
# ============================================================

@pytest.mark.timeout(15)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
def test_unknown_cap_returns_err(relay_host_binaries, plugin_binaries, host_lang):
    """Request for unknown cap must return ERR frame."""
    host_binary = relay_host_binaries[host_lang]
    plugin_binary = plugin_binaries["rust"]

    proc, reader, writer = _start_relay_host(host_binary, [str(plugin_binary)])

    try:
        req_id = MessageId.new_uuid()
        writer.write(Frame.req(req_id, "cap:op=nonexistent-cap-xyz", b"", "text/plain"))
        writer.write(Frame.end(req_id))

        _, frames = _read_response(reader)
        err_frames = [f for f in frames if f.frame_type == FrameType.ERR]

        assert len(err_frames) > 0, (
            f"[{host_lang}] must receive ERR for unknown cap, got: "
            f"{[f.frame_type for f in frames]}"
        )
    finally:
        _stop(proc)


# ============================================================
# Test: Concurrent requests to same plugin
# ============================================================

@pytest.mark.timeout(30)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_concurrent_requests(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """Two requests sent before reading any response both complete correctly."""
    host_binary = relay_host_binaries[host_lang]
    plugin_binary = plugin_binaries[plugin_lang]

    proc, reader, writer = _start_relay_host(host_binary, [str(plugin_binary)])

    try:
        payload1 = b"first-request"
        payload2 = b"second-request"

        # Send both requests before reading
        req_id1 = _send_request(writer, ECHO_CAP, payload1)
        req_id2 = _send_request(writer, ECHO_CAP, payload2)

        # Read both responses (they may arrive interleaved)
        responses = {}  # req_id_str → chunks
        ends = 0
        for _ in range(100):
            frame = reader.read()
            if frame is None:
                break
            id_str = frame.id.to_uuid_string() if frame.id else None
            if frame.frame_type == FrameType.CHUNK and frame.payload:
                responses.setdefault(id_str, bytearray()).extend(frame.payload)
            if frame.frame_type == FrameType.END:
                ends += 1
                if ends >= 2:
                    break

        id1_str = req_id1.to_uuid_string()
        id2_str = req_id2.to_uuid_string()

        decoded1 = _decode_cbor_bytes(bytes(responses.get(id1_str, b"")))
        decoded2 = _decode_cbor_bytes(bytes(responses.get(id2_str, b"")))

        assert decoded1 == payload1, (
            f"[{host_lang}/{plugin_lang}] first request mismatch: {decoded1!r}"
        )
        assert decoded2 == payload2, (
            f"[{host_lang}/{plugin_lang}] second request mismatch: {decoded2!r}"
        )
    finally:
        _stop(proc)
