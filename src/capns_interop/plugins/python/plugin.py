#!/usr/bin/env python3
"""
Interoperability test plugin (Python)

Implements all 13 standard test capabilities for cross-language protocol testing.
"""

import sys
import json
import time
from pathlib import Path

# Add capns-py to path
capns_py_path = Path(__file__).parent.parent.parent.parent.parent.parent / "capns-py" / "src"
sys.path.insert(0, str(capns_py_path))

from capns.plugin_runtime import PluginRuntime
from capns.manifest import CapManifest, Cap
from capns.cap_urn import CapUrn, CapUrnBuilder
from capns.caller import CapArgumentValue


def build_manifest() -> CapManifest:
    """Build manifest with all 13 test capabilities."""
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

    runtime.run()


if __name__ == "__main__":
    main()
