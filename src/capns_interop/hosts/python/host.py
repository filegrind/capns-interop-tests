#!/usr/bin/env python3
"""Python test host binary for cross-language matrix tests.

Reads JSON-line commands from stdin, manages a plugin subprocess
via AsyncPluginHost, and writes JSON-line responses to stdout.

Commands:
    spawn   {plugin_path}                      → {ok, manifest_b64}
    call    {cap_urn, payload_b64, content_type} → {ok, payload_b64, is_streaming, chunks_b64[], duration_ns}
    send_heartbeat                              → {ok}
    get_manifest                                → {ok, manifest_b64}
    shutdown                                    → {ok}
"""

import asyncio
import base64
import json
import sys
import time
from pathlib import Path

# Add capns-py to path
capns_py_path = Path(__file__).parent.parent.parent.parent.parent / "capns-py" / "src"
sys.path.insert(0, str(capns_py_path))

from capns.async_plugin_host import AsyncPluginHost, cbor_decode_response
from capns.caller import CapArgumentValue


class PythonTestHost:
    """Test host wrapping Python AsyncPluginHost."""

    def __init__(self):
        self.host: AsyncPluginHost = None
        self.process: asyncio.subprocess.Process = None

    async def handle_spawn(self, cmd: dict) -> dict:
        plugin_path = cmd["plugin_path"]
        path = Path(plugin_path)

        if path.suffix == ".py":
            args = [sys.executable, str(path)]
        else:
            args = [str(path)]

        self.process = await asyncio.create_subprocess_exec(
            *args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        if not self.process.stdin or not self.process.stdout:
            return {"ok": False, "error": "Failed to create plugin pipes"}

        # Drain stderr in background
        asyncio.create_task(self._drain_stderr())

        # Give plugin a moment to initialize
        await asyncio.sleep(0.1)

        # Create AsyncPluginHost (does CBOR handshake)
        self.host = await AsyncPluginHost.new(self.process.stdout, self.process.stdin)

        # Register echo and double handlers for bidirectional tests
        async def echo_handler(payload: bytes) -> bytes:
            return payload

        self.host.register_capability("cap:in=*;op=echo;out=*", echo_handler)

        async def double_handler(payload: bytes) -> bytes:
            data = json.loads(payload)
            value = data["value"]
            result = value * 2
            return json.dumps(result).encode()

        self.host.register_capability("cap:in=*;op=double;out=*", double_handler)

        manifest = self.host.get_plugin_manifest()
        manifest_b64 = base64.b64encode(manifest).decode("ascii") if manifest else ""

        return {"ok": True, "manifest_b64": manifest_b64}

    async def handle_call(self, cmd: dict) -> dict:
        cap_urn = cmd["cap_urn"]
        args_json = cmd.get("arguments", [])

        args = []
        for arg_json in args_json:
            media_urn = arg_json["media_urn"]
            value_b64 = arg_json.get("value_b64", "")
            value = base64.b64decode(value_b64) if value_b64 else b""
            args.append(CapArgumentValue(media_urn, value))

        start_ns = time.perf_counter_ns()
        raw_response = await self.host.call_with_arguments(cap_urn, args)
        duration_ns = time.perf_counter_ns() - start_ns

        # CBOR-decode — matches Rust/Go/Swift host decode_cbor_values()
        response = cbor_decode_response(raw_response)

        if response.is_streaming():
            chunks_b64 = [
                base64.b64encode(c.payload).decode("ascii")
                for c in response.chunks
            ]
            return {
                "ok": True,
                "is_streaming": True,
                "chunks_b64": chunks_b64,
                "duration_ns": duration_ns,
            }
        else:
            final = response.final_payload() or b""
            return {
                "ok": True,
                "payload_b64": base64.b64encode(final).decode("ascii"),
                "is_streaming": False,
                "duration_ns": duration_ns,
            }

    async def handle_throughput(self, cmd: dict) -> dict:
        payload_mb = cmd.get("payload_mb", 5)
        payload_size = payload_mb * 1024 * 1024
        cap_urn = 'cap:in="media:number;form=scalar";op=generate_large;out="media:bytes"'

        input_json = json.dumps({"value": payload_size}).encode()
        args = [CapArgumentValue("media:json", input_json)]

        start = time.perf_counter()
        raw_response = await self.host.call_with_arguments(cap_urn, args)
        elapsed = time.perf_counter() - start

        # CBOR-decode to get exact payload bytes
        decoded = cbor_decode_response(raw_response)
        total_bytes = len(decoded.concatenated())

        if total_bytes != payload_size:
            return {"ok": False, "error": f"Expected {payload_size} bytes, got {total_bytes}"}

        mb_per_sec = payload_mb / elapsed

        return {
            "ok": True,
            "payload_mb": payload_mb,
            "duration_s": round(elapsed, 4),
            "mb_per_sec": round(mb_per_sec, 2),
        }

    async def handle_send_heartbeat(self) -> dict:
        await self.host.send_heartbeat()
        return {"ok": True}

    async def handle_get_manifest(self) -> dict:
        manifest = self.host.get_plugin_manifest()
        manifest_b64 = base64.b64encode(manifest).decode("ascii") if manifest else ""
        return {"ok": True, "manifest_b64": manifest_b64}

    async def handle_shutdown(self) -> dict:
        if self.host:
            await self.host.shutdown()
        if self.process:
            if self.process.stdin:
                self.process.stdin.close()
                try:
                    await self.process.stdin.wait_closed()
                except Exception:
                    pass
            try:
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.process.kill()
                await self.process.wait()
        return {"ok": True}

    async def _drain_stderr(self):
        if not self.process or not self.process.stderr:
            return
        try:
            while True:
                chunk = await self.process.stderr.read(8192)
                if not chunk:
                    break
                # Write plugin stderr to our stderr for debugging
                sys.stderr.buffer.write(chunk)
                sys.stderr.buffer.flush()
        except Exception:
            pass

    async def run(self):
        """Main loop: read JSON-line commands from stdin, dispatch, write responses."""
        # 64MB limit for large base64-encoded payloads in JSON lines
        reader = asyncio.StreamReader(limit=64 * 1024 * 1024)
        protocol = await asyncio.get_event_loop().connect_read_pipe(
            lambda: asyncio.StreamReaderProtocol(reader), sys.stdin
        )

        while True:
            line = await reader.readline()
            if not line:
                break

            try:
                cmd = json.loads(line.decode("utf-8"))
            except json.JSONDecodeError as e:
                response = {"ok": False, "error": f"Invalid JSON: {e}"}
                sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
                sys.stdout.flush()
                continue

            try:
                cmd_type = cmd.get("cmd", "")
                if cmd_type == "spawn":
                    response = await self.handle_spawn(cmd)
                elif cmd_type == "call":
                    response = await self.handle_call(cmd)
                elif cmd_type == "throughput":
                    response = await self.handle_throughput(cmd)
                elif cmd_type == "send_heartbeat":
                    response = await self.handle_send_heartbeat()
                elif cmd_type == "get_manifest":
                    response = await self.handle_get_manifest()
                elif cmd_type == "shutdown":
                    response = await self.handle_shutdown()
                    sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
                    sys.stdout.flush()
                    break
                else:
                    response = {"ok": False, "error": f"Unknown command: {cmd_type}"}
            except Exception as e:
                response = {"ok": False, "error": f"{type(e).__name__}: {str(e)}"}

            sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
            sys.stdout.flush()


async def main():
    host = PythonTestHost()
    await host.run()


if __name__ == "__main__":
    asyncio.run(main())
