"""Relay interop tests.

Tests the RelaySlave/RelayMaster protocol across language combinations.
Each relay host binary (Rust/Go/Python/Swift) manages a plugin behind a
RelaySlave layer. The test acts as the RelayMaster.

Architecture:
    Python test (RelayMaster) ←CBOR frames→ relay_host binary (RelaySlave → PluginHost → plugin)

The relay layer adds two intercepted frame types:
  - RelayNotify (slave → master): Capability advertisement on startup
  - RelayState (master → slave): Resource state updates, never reach plugins

All other frames pass through transparently.
"""

import json
import os
import subprocess
import sys
import time

import pytest

# Add capns-py to path for frame I/O
_project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_project_root, "..", "capns-py", "src"))
sys.path.insert(0, os.path.join(_project_root, "..", "tagged-urn-py", "src"))

from capns.cbor_frame import Frame, FrameType, Limits, MessageId
from capns.cbor_io import FrameReader, FrameWriter
from capns.plugin_relay import RelayMaster

# E-commerce semantic cap URNs matching test plugin
ECHO_CAP = 'cap:in=media:;out=media:'
BINARY_ECHO_CAP = 'cap:in="media:product-image;bytes";op=binary_echo;out="media:product-image;bytes"'

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


def _start_relay_host(relay_host_binary, plugin_paths, relay=True):
    """Start a relay host binary in relay mode, return (proc, reader, writer)."""
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

    Protocol v2: CHUNK payloads must be CBOR-encoded.
    """
    import cbor2
    req_id = MessageId.new_uuid()
    writer.write(Frame.req(req_id, cap_urn, b"", "application/octet-stream"))
    writer.write(Frame.stream_start(req_id, "arg-0", media_urn))
    # CBOR-encode the payload per protocol v2
    cbor_payload = cbor2.dumps(payload)
    writer.write(Frame.chunk(req_id, "arg-0", 0, cbor_payload))
    writer.write(Frame.stream_end(req_id, "arg-0"))
    writer.write(Frame.end(req_id))
    return req_id


def _read_response(reader, max_frames=50):
    """Read response frames until END or ERR. Returns (decoded_data, all_frames).

    Protocol v2: Each CHUNK payload is CBOR-encoded and must be decoded.
    Multiple byte chunks are concatenated.
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
            # Decode each CBOR chunk
            decoded = cbor2.loads(frame.payload)
            chunks.append(decoded)
        if frame.frame_type in (FrameType.END, FrameType.ERR):
            break

    # Reconstruct based on type (matching frame_test_helper.py logic)
    if not chunks:
        return b'', frames
    elif len(chunks) == 1:
        return chunks[0], frames
    else:
        # Multiple chunks: concatenate if bytes
        first = chunks[0]
        if isinstance(first, bytes):
            return b''.join(c for c in chunks if isinstance(c, bytes)), frames
        else:
            return chunks, frames



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
# Test: Relay sends initial RelayNotify with manifest + limits
# ============================================================

@pytest.mark.timeout(15)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_relay_initial_notify(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """RelaySlave sends RelayNotify on startup with manifest and limits."""
    host_binary = relay_host_binaries[host_lang]
    plugin_binary = plugin_binaries[plugin_lang]

    proc, reader, writer = _start_relay_host(host_binary, [str(plugin_binary)])

    try:
        # First frame must be RelayNotify
        master = RelayMaster.connect(reader)

        # Manifest must be valid JSON containing at least one cap
        manifest = master.manifest
        assert manifest is not None, f"[{host_lang}/{plugin_lang}] manifest is None"
        manifest_str = manifest.decode("utf-8") if isinstance(manifest, bytes) else manifest
        parsed = json.loads(manifest_str)
        assert isinstance(parsed, (list, dict)), (
            f"[{host_lang}/{plugin_lang}] manifest not JSON list/dict: {type(parsed)}"
        )

        # Limits must have valid values
        limits = master.limits
        assert limits.max_frame > 0, f"[{host_lang}/{plugin_lang}] max_frame must be > 0"
        assert limits.max_chunk > 0, f"[{host_lang}/{plugin_lang}] max_chunk must be > 0"

    finally:
        _stop(proc)


# ============================================================
# Test: Request passes through relay transparently
# ============================================================

@pytest.mark.timeout(30)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_relay_request_passthrough(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """REQ through relay reaches plugin, response comes back through relay."""
    host_binary = relay_host_binaries[host_lang]
    plugin_binary = plugin_binaries[plugin_lang]

    proc, reader, writer = _start_relay_host(host_binary, [str(plugin_binary)])

    try:
        # Read initial RelayNotify
        master = RelayMaster.connect(reader)

        # Send echo request through relay
        req_id = _send_request(writer, ECHO_CAP, b"relay-echo-test")
        raw, frames = _read_response(reader)
        decoded = raw

        assert decoded == b"relay-echo-test", (
            f"[{host_lang}/{plugin_lang}] echo mismatch through relay: {decoded!r}"
        )
    finally:
        _stop(proc)


# ============================================================
# Test: RelayState from master is stored by slave (not forwarded to plugin)
# ============================================================

@pytest.mark.timeout(15)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_relay_state_delivery(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """RelayState sent by master is stored by slave. Plugin never sees it.

    We verify this indirectly: if the relay state reached the plugin as a regular
    frame, the plugin runtime would send an ERR (relay frames reaching runtime is
    a protocol error per Phase 5). Since the echo still works, the relay correctly
    intercepted the RelayState.
    """
    host_binary = relay_host_binaries[host_lang]
    plugin_binary = plugin_binaries[plugin_lang]

    proc, reader, writer = _start_relay_host(host_binary, [str(plugin_binary)])

    try:
        master = RelayMaster.connect(reader)

        # Send RelayState to slave
        RelayMaster.send_state(writer, b'{"memory_mb": 1024}')

        # Now send a regular request — if RelayState leaked to the plugin,
        # the plugin runtime would error out and this request would fail
        req_id = _send_request(writer, ECHO_CAP, b"after-relay-state")
        raw, frames = _read_response(reader)
        decoded = raw

        assert decoded == b"after-relay-state", (
            f"[{host_lang}/{plugin_lang}] echo after RelayState failed: {decoded!r}"
        )
    finally:
        _stop(proc)


# ============================================================
# Test: Unknown cap returns ERR through relay
# ============================================================

@pytest.mark.timeout(15)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
def test_relay_unknown_cap_returns_err(relay_host_binaries, plugin_binaries, host_lang):
    """Request for unknown cap through relay returns ERR frame."""
    host_binary = relay_host_binaries[host_lang]
    plugin_binary = plugin_binaries["rust"]

    proc, reader, writer = _start_relay_host(host_binary, [str(plugin_binary)])

    try:
        master = RelayMaster.connect(reader)

        req_id = MessageId.new_uuid()
        writer.write(Frame.req(req_id, "cap:op=nonexistent-relay-xyz", b"", "text/plain"))
        writer.write(Frame.end(req_id))

        _, frames = _read_response(reader)
        err_frames = [f for f in frames if f.frame_type == FrameType.ERR]

        assert len(err_frames) > 0, (
            f"[{host_lang}] must receive ERR for unknown cap through relay, got: "
            f"{[f.frame_type for f in frames]}"
        )
    finally:
        _stop(proc)


# ============================================================
# Test: Mixed traffic (RelayState + requests interleaved)
# ============================================================

@pytest.mark.timeout(30)
@pytest.mark.parametrize("host_lang", SUPPORTED_HOST_LANGS)
@pytest.mark.parametrize("plugin_lang", SUPPORTED_PLUGIN_LANGS)
def test_relay_mixed_traffic(relay_host_binaries, plugin_binaries, host_lang, plugin_lang):
    """RelayState frames interleaved with requests work correctly."""
    host_binary = relay_host_binaries[host_lang]
    plugin_binary = plugin_binaries[plugin_lang]

    proc, reader, writer = _start_relay_host(host_binary, [str(plugin_binary)])

    try:
        master = RelayMaster.connect(reader)

        # Interleave: RelayState, request, RelayState, request
        RelayMaster.send_state(writer, b'{"step": 1}')

        req_id1 = _send_request(writer, ECHO_CAP, b"mixed-1")
        raw1, _ = _read_response(reader)
        decoded1 = raw1

        RelayMaster.send_state(writer, b'{"step": 2}')

        req_id2 = _send_request(writer, BINARY_ECHO_CAP, bytes(range(64)))
        raw2, _ = _read_response(reader)
        decoded2 = raw2

        assert decoded1 == b"mixed-1", (
            f"[{host_lang}/{plugin_lang}] first request after state: {decoded1!r}"
        )
        assert decoded2 == bytes(range(64)), (
            f"[{host_lang}/{plugin_lang}] second request after state: {decoded2!r}"
        )
    finally:
        _stop(proc)
