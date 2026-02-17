#!/opt/homebrew/Caskroom/miniforge/base/bin/python
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

from capns.bifaci.plugin_runtime import PluginRuntime
from capns.bifaci.manifest import CapManifest, Cap
from capns.urn.cap_urn import CapUrn, CapUrnBuilder
from capns.cap.caller import CapArgumentValue
from capns.cap.definition import CapArg, CapOutput, StdinSource, PositionSource
from capns.bifaci.frame import Frame, FrameType
import queue


def cbor_value_to_bytes(value) -> bytes:
    """Convert CBOR value to bytes for handlers expecting bytes."""
    if isinstance(value, bytes):
        return value
    elif isinstance(value, str):
        return value.encode('utf-8')
    else:
        raise ValueError(f"Expected bytes or str, got {type(value)}")


def collect_payload(frames: queue.Queue):
    """Collect all CHUNK frames, decode each as CBOR, and return the reconstructed value.
    PROTOCOL: Each CHUNK payload is a complete, independently decodable CBOR value.
    Returns the decoded CBOR value (bytes, str, dict, list, int, etc.).
    """
    import cbor2
    chunks = []
    while True:
        try:
            frame = frames.get(timeout=30)
            if frame.frame_type == FrameType.CHUNK:
                if frame.payload:
                    # Each CHUNK payload MUST be valid CBOR - decode it
                    value = cbor2.loads(frame.payload)
                    chunks.append(value)
            elif frame.frame_type == FrameType.END:
                break
        except queue.Empty:
            break

    # Reconstruct value from chunks
    if not chunks:
        return None
    elif len(chunks) == 1:
        return chunks[0]
    else:
        # Multiple chunks - concatenate bytes/strings or collect as list
        first = chunks[0]
        if isinstance(first, bytes):
            return b''.join(c for c in chunks if isinstance(c, bytes))
        elif isinstance(first, str):
            return ''.join(c for c in chunks if isinstance(c, str))
        else:
            # For other types (dict, int, etc.), return as list
            return chunks


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
            .in_spec("media:invoice;file-path;textable;form=scalar")
            .out_spec("media:invoice-metadata;json;textable;form=map")
            .build(),
        title="Read File Info",
        command="read_file_info",
    )
    read_file_info_cap.args = [
        CapArg(
            media_urn="media:invoice;file-path;textable;form=scalar",
            required=True,
            sources=[
                StdinSource("media:bytes"),
                PositionSource(0),
            ],
            arg_description="Path to invoice file to read",
        )
    ]
    read_file_info_cap.output = CapOutput(
        media_urn="media:invoice-metadata;json;textable;form=map",
        output_description="Invoice file size and SHA256 checksum",
    )

    caps = [
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "echo")
                .in_spec("media:bytes")
                .out_spec("media:bytes")
                .build(),
            title="Echo",
            command="echo",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "double")
                .in_spec("media:order-value;json;textable;form=map")
                .out_spec("media:loyalty-points;integer;textable;numeric;form=scalar")
                .build(),
            title="Double",
            command="double",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "stream_chunks")
                .in_spec("media:update-count;json;textable;form=map")
                .out_spec("media:order-updates;textable")
                .build(),
            title="Stream Chunks",
            command="stream_chunks",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "binary_echo")
                .in_spec("media:product-image;bytes")
                .out_spec("media:product-image;bytes")
                .build(),
            title="Binary Echo",
            command="binary_echo",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "slow_response")
                .in_spec("media:payment-delay-ms;json;textable;form=map")
                .out_spec("media:payment-result;textable;form=scalar")
                .build(),
            title="Slow Response",
            command="slow_response",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "generate_large")
                .in_spec("media:report-size;json;textable;form=map")
                .out_spec("media:sales-report;bytes")
                .build(),
            title="Generate Large",
            command="generate_large",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "with_status")
                .in_spec("media:fulfillment-steps;json;textable;form=map")
                .out_spec("media:fulfillment-status;textable;form=scalar")
                .build(),
            title="With Status",
            command="with_status",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "throw_error")
                .in_spec("media:payment-error;json;textable;form=map")
                .out_spec("media:void")
                .build(),
            title="Throw Error",
            command="throw_error",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "peer_echo")
                .in_spec("media:customer-message;textable;form=scalar")
                .out_spec("media:customer-message;textable;form=scalar")
                .build(),
            title="Peer Echo",
            command="peer_echo",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "nested_call")
                .in_spec("media:order-value;json;textable;form=map")
                .out_spec("media:final-price;integer;textable;numeric;form=scalar")
                .build(),
            title="Nested Call",
            command="nested_call",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "heartbeat_stress")
                .in_spec("media:monitoring-duration-ms;json;textable;form=map")
                .out_spec("media:health-status;textable;form=scalar")
                .build(),
            title="Heartbeat Stress",
            command="heartbeat_stress",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "concurrent_stress")
                .in_spec("media:order-batch-size;json;textable;form=map")
                .out_spec("media:batch-result;textable;form=scalar")
                .build(),
            title="Concurrent Stress",
            command="concurrent_stress",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "get_manifest")
                .in_spec("media:void")
                .out_spec("media:service-capabilities;json;textable;form=map")
                .build(),
            title="Get Manifest",
            command="get_manifest",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "process_large")
                .in_spec("media:uploaded-document;bytes")
                .out_spec("media:document-info;json;textable;form=map")
                .build(),
            title="Process Large",
            command="process_large",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "hash_incoming")
                .in_spec("media:uploaded-document;bytes")
                .out_spec("media:document-hash;textable;form=scalar")
                .build(),
            title="Hash Incoming",
            command="hash_incoming",
        ),
        Cap(
            urn=CapUrnBuilder()
                .tag("op", "verify_binary")
                .in_spec("media:package-data;bytes")
                .out_spec("media:verification-status;textable;form=scalar")
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
    payload_bytes = cbor_value_to_bytes(payload)
    emitter.emit_cbor(payload_bytes)


def handle_double(frames: queue.Queue, emitter, peer):
    """Double - doubles a number. Emits CBOR integer (mirrors Rust: emit_cbor(&Integer(result)))."""
    payload = collect_payload(frames)
    # collect_payload returns dict for CBOR Maps, bytes for CBOR Bytes
    data = payload if isinstance(payload, dict) else json.loads(payload)
    value = data["value"]
    result = value * 2
    # Emit as CBOR integer directly (mirrors Rust output.emit_cbor(&ciborium::Value::Integer(result.into())))
    emitter.emit_cbor(result)


def handle_stream_chunks(frames: queue.Queue, emitter, peer):
    """Stream chunks - emits N chunks."""
    payload = collect_payload(frames)
    # collect_payload returns dict for CBOR Maps, bytes for CBOR Bytes
    data = payload if isinstance(payload, dict) else json.loads(payload)
    count = data["value"]

    for i in range(count):
        chunk_data = f"chunk-{i}".encode('utf-8')
        emitter.emit_cbor(chunk_data)

    emitter.emit_cbor(b"done")


def handle_binary_echo(frames: queue.Queue, emitter, peer):
    """Binary echo - echoes binary data."""
    payload = collect_payload(frames)
    payload_bytes = cbor_value_to_bytes(payload)
    emitter.emit_cbor(payload_bytes)


def handle_slow_response(frames: queue.Queue, emitter, peer):
    """Slow response - sleeps before responding."""
    payload = collect_payload(frames)
    # collect_payload returns dict for CBOR Maps, bytes for CBOR Bytes
    data = payload if isinstance(payload, dict) else json.loads(payload)
    sleep_ms = data["value"]

    time.sleep(sleep_ms / 1000.0)

    response = f"slept-{sleep_ms}ms".encode('utf-8')
    emitter.emit_cbor(response)


def handle_generate_large(frames: queue.Queue, emitter, peer):
    """Generate large - generates large payload."""
    payload = collect_payload(frames)
    # collect_payload returns dict for CBOR Maps, bytes for CBOR Bytes
    data = payload if isinstance(payload, dict) else json.loads(payload)
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
    # collect_payload returns dict for CBOR Maps, bytes for CBOR Bytes
    data = payload if isinstance(payload, dict) else json.loads(payload)
    steps = data["value"]

    for i in range(steps):
        status = f"step {i}"
        emitter.emit_log("processing", status)
        time.sleep(0.01)

    emitter.emit_cbor(b"completed")


def handle_throw_error(frames: queue.Queue, emitter, peer):
    """Throw error - returns an error."""
    payload = collect_payload(frames)
    # collect_payload returns dict for CBOR Maps, bytes for CBOR Bytes
    data = payload if isinstance(payload, dict) else json.loads(payload)
    message = data["value"]
    raise RuntimeError(message)


def handle_peer_echo(frames: queue.Queue, emitter, peer):
    """Peer echo - calls host's echo via PeerInvoker."""
    payload = collect_payload(frames)
    payload_bytes = cbor_value_to_bytes(payload)

    # Call host's echo capability with semantic URN
    peer_frames = peer.invoke("cap:in=media:;out=media:", [CapArgumentValue("media:customer-message;textable;form=scalar", payload_bytes)])

    # Collect and decode peer response
    cbor_value = collect_peer_response(peer_frames)

    # Re-emit (consumption → production)
    emitter.emit_cbor(cbor_value)


def handle_nested_call(frames: queue.Queue, emitter, peer):
    """Nested call - makes a peer call to double, then doubles again."""
    payload = collect_payload(frames)
    # collect_payload returns dict for CBOR Maps, bytes for CBOR Bytes
    data = payload if isinstance(payload, dict) else json.loads(payload)
    value = data["value"]

    # Call host's double capability — use exact URN (mirrors Rust)
    input_data = json.dumps({"value": value}).encode('utf-8')
    peer_frames = peer.invoke('cap:in="media:order-value;json;textable;form=map";op=double;out="media:loyalty-points;integer;textable;numeric;form=scalar"', [CapArgumentValue("media:order-value;json;textable;form=map", input_data)])

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
    # collect_payload returns dict for CBOR Maps, bytes for CBOR Bytes
    data = payload if isinstance(payload, dict) else json.loads(payload)
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
    # collect_payload returns dict for CBOR Maps, bytes for CBOR Bytes
    data = payload if isinstance(payload, dict) else json.loads(payload)
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
    payload_bytes = cbor_value_to_bytes(payload)
    size = len(payload_bytes)
    checksum = hashlib.sha256(payload_bytes).hexdigest()

    result = {
        "size": size,
        "checksum": checksum
    }

    result_bytes = json.dumps(result).encode('utf-8')
    emitter.emit_cbor(result_bytes)


def handle_hash_incoming(frames: queue.Queue, emitter, peer):
    """Hash incoming - receives large bytes, returns SHA256 hash."""
    payload = collect_payload(frames)
    payload_bytes = cbor_value_to_bytes(payload)
    checksum = hashlib.sha256(payload_bytes).hexdigest()
    result_bytes = checksum.encode('utf-8')
    emitter.emit_cbor(result_bytes)


def handle_verify_binary(frames: queue.Queue, emitter, peer):
    """Verify binary - verifies all 256 byte values present."""
    payload = collect_payload(frames)
    payload_bytes = cbor_value_to_bytes(payload)

    # Count occurrences of each byte value
    byte_counts = [0] * 256
    for byte in payload_bytes:
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
    payload_bytes = cbor_value_to_bytes(payload)
    size = len(payload_bytes)
    checksum = hashlib.sha256(payload_bytes).hexdigest()

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

    # Register all handlers with exact URNs matching the manifest (mirrors Rust plugin)
    runtime.register_raw('cap:in="media:bytes";op=echo;out="media:bytes"', handle_echo)
    runtime.register_raw('cap:in="media:order-value;json;textable;form=map";op=double;out="media:loyalty-points;integer;textable;numeric;form=scalar"', handle_double)
    runtime.register_raw('cap:in="media:update-count;json;textable;form=map";op=stream_chunks;out="media:order-updates;textable"', handle_stream_chunks)
    runtime.register_raw('cap:in="media:product-image;bytes";op=binary_echo;out="media:product-image;bytes"', handle_binary_echo)
    runtime.register_raw('cap:in="media:payment-delay-ms;json;textable;form=map";op=slow_response;out="media:payment-result;textable;form=scalar"', handle_slow_response)
    runtime.register_raw('cap:in="media:report-size;json;textable;form=map";op=generate_large;out="media:sales-report;bytes"', handle_generate_large)
    runtime.register_raw('cap:in="media:fulfillment-steps;json;textable;form=map";op=with_status;out="media:fulfillment-status;textable;form=scalar"', handle_with_status)
    runtime.register_raw('cap:in="media:payment-error;json;textable;form=map";op=throw_error;out=media:void', handle_throw_error)
    runtime.register_raw('cap:in="media:customer-message;textable;form=scalar";op=peer_echo;out="media:customer-message;textable;form=scalar"', handle_peer_echo)
    runtime.register_raw('cap:in="media:order-value;json;textable;form=map";op=nested_call;out="media:final-price;integer;textable;numeric;form=scalar"', handle_nested_call)
    runtime.register_raw('cap:in="media:monitoring-duration-ms;json;textable;form=map";op=heartbeat_stress;out="media:health-status;textable;form=scalar"', handle_heartbeat_stress)
    runtime.register_raw('cap:in="media:order-batch-size;json;textable;form=map";op=concurrent_stress;out="media:batch-result;textable;form=scalar"', handle_concurrent_stress)
    runtime.register_raw('cap:in=media:void;op=get_manifest;out="media:service-capabilities;json;textable;form=map"', handle_get_manifest)
    runtime.register_raw('cap:in="media:uploaded-document;bytes";op=process_large;out="media:document-info;json;textable;form=map"', handle_process_large)
    runtime.register_raw('cap:in="media:uploaded-document;bytes";op=hash_incoming;out="media:document-hash;textable;form=scalar"', handle_hash_incoming)
    runtime.register_raw('cap:in="media:package-data;bytes";op=verify_binary;out="media:verification-status;textable;form=scalar"', handle_verify_binary)
    runtime.register_raw('cap:in="media:invoice;file-path;textable;form=scalar";op=read_file_info;out="media:invoice-metadata;json;textable;form=map"', handle_read_file_info)

    runtime.run()


if __name__ == "__main__":
    main()
