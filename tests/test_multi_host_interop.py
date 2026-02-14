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

# E-commerce semantic cap URNs matching the test plugin's registered capabilities
ECHO_CAP = 'cap:in=media:;out=media:'
BINARY_ECHO_CAP = 'cap:in="media:product-image;bytes";op=binary_echo;out="media:product-image;bytes"'
DOUBLE_CAP = 'cap:in="media:order-value;json;textable;form=map";op=double;out="media:loyalty-points;integer;textable;numeric;form=scalar"'

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
    """Send a complete request and return the req_id used.

    PROTOCOL V2: CHUNK payloads MUST be CBOR-encoded.
    """
    import cbor2
    req_id = MessageId.new_uuid()
    writer.write(Frame.req(req_id, cap_urn, b"", "application/octet-stream"))
    writer.write(Frame.stream_start(req_id, "arg-0", media_urn))
    # CBOR-encode payload for protocol v2
    cbor_payload = cbor2.dumps(payload)
    writer.write(Frame.chunk(req_id, "arg-0", 0, cbor_payload))
    writer.write(Frame.stream_end(req_id, "arg-0"))
    writer.write(Frame.end(req_id))
    return req_id


def _read_response(reader, max_frames=50):
    """Read response frames until END or ERR. Returns (decoded_value, all_frames).

    PROTOCOL V2: Each CHUNK payload is a complete CBOR value.
    Decodes each chunk and reconstructs the final value.
    """
    import cbor2
    chunks = []
    frames = []
    for _ in range(max_frames):
        frame = reader.read()
        if frame is None:
            break
        frames.append(frame)
        if frame.frame_type == FrameType.CHUNK and frame.payload:
            # Decode each CBOR chunk - FAIL HARD if not valid CBOR
            decoded = cbor2.loads(frame.payload)
            chunks.append(decoded)
        if frame.frame_type in (FrameType.END, FrameType.ERR):
            break

    # Reconstruct value from decoded chunks
    if not chunks:
        return None, frames
    elif len(chunks) == 1:
        return chunks[0], frames
    else:
        # Multiple chunks - concatenate bytes/strings or collect elements
        first = chunks[0]
        if isinstance(first, bytes):
            return b''.join(c for c in chunks if isinstance(c, bytes)), frames
        elif isinstance(first, str):
            return ''.join(c for c in chunks if isinstance(c, str)), frames
        else:
            return chunks, frames


# Removed _decode_cbor_bytes - _read_response now decodes CBOR chunks automatically (protocol v2)


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
        decoded, frames = _read_response(reader)

        assert decoded == b"hello-routing", (
            f"[{host_lang}/{plugin_lang}] echo mismatch: {decoded!r}"
        )

        # Send binary_echo request (different cap, same plugin)
        req_id2 = _send_request(writer, BINARY_ECHO_CAP, bytes(range(256)))
        decoded2, frames2 = _read_response(reader)

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
        # PROTOCOL V2: Each CHUNK payload is a complete CBOR value
        import cbor2
        responses = {}  # req_id_str → list of decoded chunks
        ends = 0
        for _ in range(100):
            frame = reader.read()
            if frame is None:
                break
            id_str = frame.id.to_uuid_string() if frame.id else None
            if frame.frame_type == FrameType.CHUNK and frame.payload:
                # Decode each CBOR chunk - FAIL HARD if not valid CBOR
                decoded_chunk = cbor2.loads(frame.payload)
                responses.setdefault(id_str, []).append(decoded_chunk)
            if frame.frame_type == FrameType.END:
                ends += 1
                if ends >= 2:
                    break

        id1_str = req_id1.to_uuid_string()
        id2_str = req_id2.to_uuid_string()

        # Reconstruct values from decoded chunks
        chunks1 = responses.get(id1_str, [])
        chunks2 = responses.get(id2_str, [])
        decoded1 = chunks1[0] if len(chunks1) == 1 else b''.join(c for c in chunks1 if isinstance(c, bytes))
        decoded2 = chunks2[0] if len(chunks2) == 1 else b''.join(c for c in chunks2 if isinstance(c, bytes))

        assert decoded1 == payload1, (
            f"[{host_lang}/{plugin_lang}] first request mismatch: {decoded1!r}"
        )
        assert decoded2 == payload2, (
            f"[{host_lang}/{plugin_lang}] second request mismatch: {decoded2!r}"
        )
    finally:
        _stop(proc)
