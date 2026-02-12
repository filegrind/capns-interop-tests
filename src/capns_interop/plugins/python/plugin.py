#!/usr/bin/env python3
"""
Interoperability test plugin (Python)

Implements all 13 standard test capabilities for cross-language protocol testing.
"""

import sys
import json
import time
import hashlib
import os
from pathlib import Path

# Add capns-py and tagged-urn-py to path - try multiple strategies
def add_module_paths():
    """Find and add capns-py and tagged-urn-py to sys.path."""
    paths_added = set()

    # Try environment variables first
    if "CAPNS_PY_PATH" in os.environ:
        sys.path.insert(0, os.environ["CAPNS_PY_PATH"])
        paths_added.add("capns")
    if "TAGGED_URN_PY_PATH" in os.environ:
        sys.path.insert(0, os.environ["TAGGED_URN_PY_PATH"])
        paths_added.add("tagged_urn")

    if len(paths_added) == 2:
        return  # Both found via env vars

    # Try to find modules relative to this file
    current = Path(__file__).resolve().parent
    for _ in range(10):  # Search up to 10 levels
        if "capns" not in paths_added:
            capns_py = current / "capns-py" / "src"
            if capns_py.exists():
                sys.path.insert(0, str(capns_py))
                paths_added.add("capns")

        if "tagged_urn" not in paths_added:
            tagged_urn_py = current / "tagged-urn-py" / "src"
            if tagged_urn_py.exists():
                sys.path.insert(0, str(tagged_urn_py))
                paths_added.add("tagged_urn")

        if len(paths_added) == 2:
            return  # Both found

        current = current.parent
        if current == current.parent:  # Reached filesystem root
            break

    # Last resort: assume we're in filegrind project
    if "capns" not in paths_added:
        capns_path = Path.home() / "ws" / "prj" / "filegrind" / "capns-py" / "src"
        if capns_path.exists():
            sys.path.insert(0, str(capns_path))

    if "tagged_urn" not in paths_added:
        tagged_urn_path = Path.home() / "ws" / "prj" / "filegrind" / "tagged-urn-py" / "src"
        if tagged_urn_path.exists():
            sys.path.insert(0, str(tagged_urn_path))

add_module_paths()

from capns.plugin_runtime import PluginRuntime
from capns.manifest import CapManifest, Cap
from capns.cap_urn import CapUrn, CapUrnBuilder
from capns.caller import CapArgumentValue
from capns.cap import CapArg, CapOutput, StdinSource, PositionSource
from capns.cbor_frame import Frame, FrameType
import queue


def collect_payload(frames: queue.Queue) -> bytes:
    """Collect all CHUNK frames, decode each as CBOR, and accumulate bytes.
    PROTOCOL: Each CHUNK payload is a complete, independently decodable CBOR value.
    For bytes values, extract and concatenate the bytes.
    For str values, extract and concatenate as UTF-8 bytes.
    """
    import cbor2
    accumulated = bytearray()
    while True:
        try:
            frame = frames.get(timeout=30)
            if frame.frame_type == FrameType.CHUNK:
                if frame.payload:
                    # Each CHUNK payload MUST be valid CBOR - decode it
                    value = cbor2.loads(frame.payload)

                    # Extract bytes from CBOR value
                    if isinstance(value, bytes):
                        accumulated.extend(value)
                    elif isinstance(value, str):
                        accumulated.extend(value.encode('utf-8'))
                    else:
                        raise ValueError(f"Unexpected CBOR type in CHUNK: expected bytes or str, got {type(value)}")
            elif frame.frame_type == FrameType.END:
                break
        except queue.Empty:
            break
    return bytes(accumulated)


def collect_peer_response(peer_frames: queue.Queue):
    """Collect peer response frames, decode each CHUNK as CBOR, and reconstruct value.
    For simple values (bytes/str/int), there's typically one chunk.
    For arrays/maps, multiple chunks are combined.
    """
    import cbor2
    chunks = []
    while True:
        try:
            frame = peer_frames.get(timeout=30)
            if frame.frame_type == FrameType.CHUNK:
                if frame.payload:
                    # Each CHUNK payload MUST be valid CBOR - decode it
                    value = cbor2.loads(frame.payload)
                    chunks.append(value)
            elif frame.frame_type == FrameType.END:
                break
            elif frame.frame_type == FrameType.ERR:
                code = frame.error_code() or "UNKNOWN"
                message = frame.error_message() or "Unknown error"
                raise RuntimeError(f"[{code}] {message}")
        except queue.Empty:
            break

    # Reconstruct value from chunks
    if not chunks:
        raise RuntimeError("No chunks received")
    elif len(chunks) == 1:
        # Single chunk - return value as-is
        return chunks[0]
    else:
        # Multiple chunks - concatenate bytes/strings, or collect array elements
        first = chunks[0]
        if isinstance(first, bytes):
            # Concatenate all byte chunks
            result = b''.join(c for c in chunks if isinstance(c, bytes))
            return result
        elif isinstance(first, str):
            # Concatenate all string chunks
            result = ''.join(c for c in chunks if isinstance(c, str))
            return result
        else:
            # For other types (Integer, Array elements), collect as list
            return chunks


def build_manifest() -> CapManifest:
    """Build manifest with all test capabilities."""

    # Build read_file_info cap with args structure
    read_file_info_cap = Cap(
        urn=CapUrnBuilder()
            .tag("op", "read_file_info")
            .in_spec("media:bytes")
            .out_spec("media:json")
            .build(),
        title="Read File Info",
        command="read_file_info",
    )
    read_file_info_cap.args = [
        CapArg(
            media_urn="media:file-path;textable;form=scalar",
            required=True,
            sources=[
                StdinSource("media:bytes"),
                PositionSource(0),
            ],
            arg_description="Path to file to read",
        )
    ]
    read_file_info_cap.output = CapOutput(
        media_urn="media:json",
        output_description="File size and SHA256 checksum",
    )

    caps = [
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "echo")
                .in_spec("media:string;textable;form=scalar")
                .out_spec("media:string;textable;form=scalar")
                .build(),
            title="Echo",
            command="echo",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "double")
                .in_spec("media:number;form=scalar")
                .out_spec("media:number;form=scalar")
                .build(),
            title="Double",
            command="double",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "stream_chunks")
                .in_spec("media:number;form=scalar")
                .out_spec("media:string;textable;streamable")
                .build(),
            title="Stream Chunks",
            command="stream_chunks",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "binary_echo")
                .in_spec("media:bytes")
                .out_spec("media:bytes")
                .build(),
            title="Binary Echo",
            command="binary_echo",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "slow_response")
                .in_spec("media:number;form=scalar")
                .out_spec("media:string;textable;form=scalar")
                .build(),
            title="Slow Response",
            command="slow_response",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "generate_large")
                .in_spec("media:number;form=scalar")
                .out_spec("media:bytes")
                .build(),
            title="Generate Large",
            command="generate_large",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "with_status")
                .in_spec("media:number;form=scalar")
                .out_spec("media:string;textable;form=scalar")
                .build(),
            title="With Status",
            command="with_status",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "throw_error")
                .in_spec("media:string;textable;form=scalar")
                .out_spec("media:void")
                .build(),
            title="Throw Error",
            command="throw_error",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "peer_echo")
                .in_spec("media:string;textable;form=scalar")
                .out_spec("media:string;textable;form=scalar")
                .build(),
            title="Peer Echo",
            command="peer_echo",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "nested_call")
                .in_spec("media:number;form=scalar")
                .out_spec("media:string;textable;form=scalar")
                .build(),
            title="Nested Call",
            command="nested_call",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "heartbeat_stress")
                .in_spec("media:number;form=scalar")
                .out_spec("media:string;textable;form=scalar")
                .build(),
            title="Heartbeat Stress",
            command="heartbeat_stress",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "concurrent_stress")
                .in_spec("media:number;form=scalar")
                .out_spec("media:string;textable;form=scalar")
                .build(),
            title="Concurrent Stress",
            command="concurrent_stress",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "get_manifest")
                .in_spec("media:void")
                .out_spec("media:json")
                .build(),
            title="Get Manifest",
            command="get_manifest",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "process_large")
                .in_spec("media:bytes")
                .out_spec("media:json")
                .build(),
            title="Process Large",
            command="process_large",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "hash_incoming")
                .in_spec("media:bytes")
                .out_spec("media:string;textable;form=scalar")
                .build(),
            title="Hash Incoming",
            command="hash_incoming",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "verify_binary")
                .in_spec("media:bytes")
                .out_spec("media:string;textable;form=scalar")
                .build(),
            title="Verify Binary",
            command="verify_binary",
        ),
        read_file_info_cap,
    ]

    return CapManifest(
        name="InteropTestPlugin",
        version="1.0.0",
        description="Interoperability testing plugin (Python)",
        caps=caps,
    )


def handle_echo(frames: queue.Queue, emitter, peer):
    """Echo - returns input as-is."""
    payload = collect_payload(frames)
    emitter.emit_cbor(payload)


def handle_double(frames: queue.Queue, emitter, peer):
    """Double - doubles a number."""
    payload = collect_payload(frames)
    data = json.loads(payload)
    value = data["value"]
    result = value * 2
    result_bytes = json.dumps(result).encode('utf-8')
    emitter.emit_cbor(result_bytes)


def handle_stream_chunks(frames: queue.Queue, emitter, peer):
    """Stream chunks - emits N chunks."""
    payload = collect_payload(frames)
    data = json.loads(payload)
    count = data["value"]

    for i in range(count):
        chunk_data = f"chunk-{i}".encode('utf-8')
        emitter.emit_cbor(chunk_data)

    emitter.emit_cbor(b"done")


def handle_binary_echo(frames: queue.Queue, emitter, peer):
    """Binary echo - echoes binary data."""
    payload = collect_payload(frames)
    emitter.emit_cbor(payload)


def handle_slow_response(frames: queue.Queue, emitter, peer):
    """Slow response - sleeps before responding."""
    payload = collect_payload(frames)
    data = json.loads(payload)
    sleep_ms = data["value"]

    time.sleep(sleep_ms / 1000.0)

    response = f"slept-{sleep_ms}ms".encode('utf-8')
    emitter.emit_cbor(response)


def handle_generate_large(frames: queue.Queue, emitter, peer):
    """Generate large - generates large payload."""
    payload = collect_payload(frames)
    data = json.loads(payload)
    size = data["value"]

    # Generate repeating pattern
    pattern = b"ABCDEFGH"
    result = bytearray()
    for i in range(size):
        result.append(pattern[i % len(pattern)])

    emitter.emit_cbor(bytes(result))


def handle_with_status(frames: queue.Queue, emitter, peer):
    """With status - emits status messages during processing."""
    payload = collect_payload(frames)
    data = json.loads(payload)
    steps = data["value"]

    for i in range(steps):
        status = f"step {i}"
        emitter.emit_log(status)
        time.sleep(0.01)

    emitter.emit_cbor(b"completed")


def handle_throw_error(frames: queue.Queue, emitter, peer):
    """Throw error - returns an error."""
    payload = collect_payload(frames)
    data = json.loads(payload)
    message = data["value"]
    raise RuntimeError(message)


def handle_peer_echo(frames: queue.Queue, emitter, peer):
    """Peer echo - calls host's echo via PeerInvoker."""
    payload = collect_payload(frames)

    # Call host's echo capability
    peer_frames = peer.invoke("cap:in=*;op=echo;out=*", [CapArgumentValue("media:bytes", payload)])

    # Collect and decode peer response
    cbor_value = collect_peer_response(peer_frames)

    # Re-emit (consumption → production)
    emitter.emit_cbor(cbor_value)


def handle_nested_call(frames: queue.Queue, emitter, peer):
    """Nested call - makes a peer call to double, then doubles again."""
    payload = collect_payload(frames)
    data = json.loads(payload)
    value = data["value"]

    # Call host's double capability
    input_data = json.dumps({"value": value}).encode('utf-8')
    peer_frames = peer.invoke("cap:in=*;op=double;out=*", [CapArgumentValue("media:json", input_data)])

    # Collect and decode peer response
    cbor_value = collect_peer_response(peer_frames)

    # Extract integer from response
    if isinstance(cbor_value, int):
        host_result = cbor_value
    elif isinstance(cbor_value, bytes):
        host_result = json.loads(cbor_value)
    else:
        host_result = cbor_value

    # Double again locally
    final_result = host_result * 2

    # Emit result as integer
    emitter.emit_cbor(final_result)


def handle_heartbeat_stress(frames: queue.Queue, emitter, peer):
    """Heartbeat stress - long operation to test heartbeats."""
    payload = collect_payload(frames)
    data = json.loads(payload)
    duration_ms = data["value"]

    # Sleep in small chunks to allow heartbeat processing
    chunks = duration_ms // 100
    for _ in range(chunks):
        time.sleep(0.1)
    time.sleep((duration_ms % 100) / 1000.0)

    response = f"stressed-{duration_ms}ms".encode('utf-8')
    emitter.emit_cbor(response)


def handle_concurrent_stress(frames: queue.Queue, emitter, peer):
    """Concurrent stress - simulates concurrent workload."""
    payload = collect_payload(frames)
    data = json.loads(payload)
    work_units = data["value"]

    # Simulate work
    total = 0
    for i in range(work_units * 1000):
        total = (total + i) & 0xFFFFFFFFFFFFFFFF  # Keep it in u64 range

    response = f"computed-{total}".encode('utf-8')
    emitter.emit_cbor(response)


def handle_get_manifest(frames: queue.Queue, emitter, peer):
    """Get manifest - returns the manifest as JSON."""
    collect_payload(frames)  # Consume frames (media:void)
    manifest = build_manifest()
    result_bytes = json.dumps(manifest.to_dict()).encode('utf-8')
    emitter.emit_cbor(result_bytes)


def handle_process_large(frames: queue.Queue, emitter, peer):
    """Process large - receives large bytes, returns size and checksum."""
    payload = collect_payload(frames)
    size = len(payload)
    checksum = hashlib.sha256(payload).hexdigest()

    result = {
        "size": size,
        "checksum": checksum
    }

    result_bytes = json.dumps(result).encode('utf-8')
    emitter.emit_cbor(result_bytes)


def handle_hash_incoming(frames: queue.Queue, emitter, peer):
    """Hash incoming - receives large bytes, returns SHA256 hash."""
    payload = collect_payload(frames)
    checksum = hashlib.sha256(payload).hexdigest()
    result_bytes = checksum.encode('utf-8')
    emitter.emit_cbor(result_bytes)


def handle_verify_binary(frames: queue.Queue, emitter, peer):
    """Verify binary - verifies all 256 byte values present."""
    payload = collect_payload(frames)

    # Count occurrences of each byte value
    byte_counts = [0] * 256
    for byte in payload:
        byte_counts[byte] += 1

    # Check all 256 values are present
    missing = []
    for i in range(256):
        if byte_counts[i] == 0:
            missing.append(i)

    if missing:
        error_msg = f"missing byte values: {missing[:10]}"  # Show first 10
        if len(missing) > 10:
            error_msg += f" and {len(missing) - 10} more"
        emitter.emit_cbor(error_msg.encode('utf-8'))
    else:
        emitter.emit_cbor(b"ok")


def handle_read_file_info(frames: queue.Queue, emitter, peer):
    """Read file info - receives file bytes (auto-converted by runtime), returns size and checksum."""
    payload = collect_payload(frames)
    size = len(payload)
    checksum = hashlib.sha256(payload).hexdigest()

    result = {
        "size": size,
        "checksum": checksum
    }

    result_bytes = json.dumps(result).encode('utf-8')
    emitter.emit_cbor(result_bytes)


def main():
    """Main entry point."""
    manifest = build_manifest()
    runtime = PluginRuntime.with_manifest(manifest)

    # Register all handlers
    runtime.register_raw("cap:in=*;op=echo;out=*", handle_echo)
    runtime.register_raw("cap:in=*;op=double;out=*", handle_double)
    runtime.register_raw("cap:in=*;op=stream_chunks;out=*", handle_stream_chunks)
    runtime.register_raw("cap:in=*;op=binary_echo;out=*", handle_binary_echo)
    runtime.register_raw("cap:in=*;op=slow_response;out=*", handle_slow_response)
    runtime.register_raw("cap:in=*;op=generate_large;out=*", handle_generate_large)
    runtime.register_raw("cap:in=*;op=with_status;out=*", handle_with_status)
    runtime.register_raw("cap:in=*;op=throw_error;out=*", handle_throw_error)
    runtime.register_raw("cap:in=*;op=peer_echo;out=*", handle_peer_echo)
    runtime.register_raw("cap:in=*;op=nested_call;out=*", handle_nested_call)
    runtime.register_raw("cap:in=*;op=heartbeat_stress;out=*", handle_heartbeat_stress)
    runtime.register_raw("cap:in=*;op=concurrent_stress;out=*", handle_concurrent_stress)
    runtime.register_raw("cap:in=*;op=get_manifest;out=*", handle_get_manifest)
    runtime.register_raw("cap:in=*;op=process_large;out=*", handle_process_large)
    runtime.register_raw("cap:in=*;op=hash_incoming;out=*", handle_hash_incoming)
    runtime.register_raw("cap:in=*;op=verify_binary;out=*", handle_verify_binary)
    runtime.register_raw("cap:in=*;op=read_file_info;out=*", handle_read_file_info)

    runtime.run()


if __name__ == "__main__":
    main()
