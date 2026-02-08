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


def handle_echo(payload: bytes, emitter, peer) -> bytes:
    """Echo - returns input as-is."""
    return payload


def handle_double(payload: bytes, emitter, peer) -> bytes:
    """Double - doubles a number."""
    data = json.loads(payload)
    value = data["value"]
    result = value * 2
    return json.dumps(result).encode()


def handle_stream_chunks(payload: bytes, emitter, peer) -> bytes:
    """Stream chunks - emits N chunks."""
    data = json.loads(payload)
    count = data["value"]

    for i in range(count):
        chunk = f"chunk-{i}"
        emitter.emit_bytes(chunk.encode())

    return b"done"


def handle_binary_echo(payload: bytes, emitter, peer) -> bytes:
    """Binary echo - echoes binary data."""
    return payload


def handle_slow_response(payload: bytes, emitter, peer) -> bytes:
    """Slow response - sleeps before responding."""
    data = json.loads(payload)
    sleep_ms = data["value"]

    time.sleep(sleep_ms / 1000.0)

    response = f"slept-{sleep_ms}ms"
    return response.encode()


def handle_generate_large(payload: bytes, emitter, peer) -> bytes:
    """Generate large - generates large payload."""
    data = json.loads(payload)
    size = data["value"]

    # Generate repeating pattern
    pattern = b"ABCDEFGH"
    result = bytearray()
    for i in range(size):
        result.append(pattern[i % len(pattern)])

    return bytes(result)


def handle_with_status(payload: bytes, emitter, peer) -> bytes:
    """With status - emits status messages during processing."""
    data = json.loads(payload)
    steps = data["value"]

    for i in range(steps):
        status = f"step {i}"
        emitter.emit_status("processing", status)
        time.sleep(0.01)

    return b"completed"


def handle_throw_error(payload: bytes, emitter, peer) -> bytes:
    """Throw error - returns an error."""
    data = json.loads(payload)
    message = data["value"]
    raise RuntimeError(message)


def handle_peer_echo(payload: bytes, emitter, peer) -> bytes:
    """Peer echo - calls host's echo via PeerInvoker."""
    # Call host's echo capability
    result_chunks = peer.invoke("cap:in=*;op=echo;out=*", [CapArgumentValue("media:bytes", payload)])

    # Collect response
    result = b""
    for chunk in result_chunks:
        result += chunk

    return result


def handle_nested_call(payload: bytes, emitter, peer) -> bytes:
    """Nested call - makes a peer call to double, then doubles again."""
    data = json.loads(payload)
    value = data["value"]

    # Call host's double capability
    input_data = json.dumps({"value": value}).encode()
    result_chunks = peer.invoke("cap:in=*;op=double;out=*", [CapArgumentValue("media:json", input_data)])

    # Collect response
    result_bytes = b""
    for chunk in result_chunks:
        result_bytes += chunk

    host_result = json.loads(result_bytes)

    # Double again locally
    final_result = host_result * 2

    return json.dumps(final_result).encode()


def handle_heartbeat_stress(payload: bytes, emitter, peer) -> bytes:
    """Heartbeat stress - long operation to test heartbeats."""
    data = json.loads(payload)
    duration_ms = data["value"]

    # Sleep in small chunks to allow heartbeat processing
    chunks = duration_ms // 100
    for _ in range(chunks):
        time.sleep(0.1)
    time.sleep((duration_ms % 100) / 1000.0)

    response = f"stressed-{duration_ms}ms"
    return response.encode()


def handle_concurrent_stress(payload: bytes, emitter, peer) -> bytes:
    """Concurrent stress - simulates concurrent workload."""
    data = json.loads(payload)
    work_units = data["value"]

    # Simulate work
    total = 0
    for i in range(work_units * 1000):
        total = (total + i) & 0xFFFFFFFFFFFFFFFF  # Keep it in u64 range

    response = f"computed-{total}"
    return response.encode()


def handle_get_manifest(payload: bytes, emitter, peer) -> bytes:
    """Get manifest - returns the manifest as JSON."""
    manifest = build_manifest()
    return json.dumps(manifest.to_dict()).encode()


def handle_process_large(payload: bytes, emitter, peer) -> bytes:
    """Process large - receives large bytes, returns size and checksum."""
    size = len(payload)
    checksum = hashlib.sha256(payload).hexdigest()

    result = {
        "size": size,
        "checksum": checksum
    }

    return json.dumps(result).encode()


def handle_hash_incoming(payload: bytes, emitter, peer) -> bytes:
    """Hash incoming - receives large bytes, returns SHA256 hash."""
    checksum = hashlib.sha256(payload).hexdigest()
    return checksum.encode()


def handle_verify_binary(payload: bytes, emitter, peer) -> bytes:
    """Verify binary - verifies all 256 byte values present."""
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
        return error_msg.encode()

    return b"ok"


def handle_read_file_info(payload: bytes, emitter, peer) -> bytes:
    """Read file info - receives file bytes (auto-converted by runtime), returns size and checksum."""
    size = len(payload)
    checksum = hashlib.sha256(payload).hexdigest()

    result = {
        "size": size,
        "checksum": checksum
    }

    return json.dumps(result).encode()


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
