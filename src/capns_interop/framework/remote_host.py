"""Remote host adapter — wraps a HostProcess to provide the same interface
that test scenarios expect from AsyncPluginHost.

The RemoteHost sends JSON-line commands to a test host binary,
which internally manages the CBOR protocol with the plugin.
Scenarios use RemoteHost interchangeably with the direct Python
AsyncPluginHost.
"""

import base64
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, List

from .host_process import HostProcess, HostProcessError


@dataclass
class ResponseChunk:
    """A response chunk from a plugin (via remote host)."""
    payload: bytes
    seq: int
    offset: Optional[int]
    len: Optional[int]
    is_eof: bool


class PluginResponse:
    """A complete response from a plugin, which may be single or streaming.

    Mirrors the capns.async_plugin_host.PluginResponse interface so that
    test scenarios can use RemoteHost and AsyncPluginHost interchangeably.
    """

    def __init__(self, chunks: List[ResponseChunk]):
        self.chunks = chunks

    @staticmethod
    def single(data: bytes) -> "PluginResponse":
        chunk = ResponseChunk(payload=data, seq=0, offset=None, len=None, is_eof=True)
        return PluginResponse([chunk])

    @staticmethod
    def streaming(chunks: List[ResponseChunk]) -> "PluginResponse":
        return PluginResponse(chunks)

    def is_single(self) -> bool:
        return len(self.chunks) == 1 and self.chunks[0].seq == 0

    def is_streaming(self) -> bool:
        return not self.is_single()

    def final_payload(self) -> Optional[bytes]:
        if not self.chunks:
            return None
        return self.chunks[-1].payload

    def concatenated(self) -> bytes:
        if self.is_single():
            return self.chunks[0].payload
        result = bytearray()
        for chunk in self.chunks:
            result.extend(chunk.payload)
        return bytes(result)


class RemoteHost:
    """Adapter wrapping a HostProcess to provide a host-like interface.

    Test scenarios call RemoteHost.call() etc., and RemoteHost
    translates these into JSON-line commands sent to the test host binary.
    """

    def __init__(self, host_process: HostProcess):
        self._host = host_process
        self._manifest: Optional[bytes] = None

    async def spawn_plugin(self, plugin_path: Path):
        """Send spawn command to have the test host launch a plugin.

        Args:
            plugin_path: Path to plugin binary

        Raises:
            HostProcessError: If spawn fails
        """
        response = await self._host.send_command({
            "cmd": "spawn",
            "plugin_path": str(plugin_path),
        })

        if not response.get("ok"):
            raise HostProcessError(
                f"Host failed to spawn plugin: {response.get('error', 'unknown error')}"
            )

        manifest_b64 = response.get("manifest_b64")
        if manifest_b64:
            self._manifest = base64.b64decode(manifest_b64)

    async def call_with_arguments(
        self,
        cap_urn: str,
        arguments: list,
    ) -> PluginResponse:
        """Send a cap request with typed arguments via the remote host.

        Each argument is a CapArgumentValue (media_urn + value bytes).
        The test host binary handles all CBOR protocol details internally.

        Args:
            cap_urn: Cap URN to invoke
            arguments: List of CapArgumentValue (media_urn + value bytes)

        Returns:
            PluginResponse with decoded payload
        """
        args_json = [
            {
                "media_urn": arg.media_urn,
                "value_b64": base64.b64encode(arg.value).decode("ascii"),
            }
            for arg in arguments
        ]
        response = await self._host.send_command({
            "cmd": "call",
            "cap_urn": cap_urn,
            "arguments": args_json,
        })

        if not response.get("ok"):
            raise HostProcessError(
                f"Host call failed: {response.get('error', 'unknown error')}"
            )

        # Reconstruct PluginResponse from the JSON response
        is_streaming = response.get("is_streaming", False)

        if is_streaming and "chunks_b64" in response:
            chunks = []
            chunks_b64 = response["chunks_b64"]
            for i, chunk_b64 in enumerate(chunks_b64):
                chunk_data = base64.b64decode(chunk_b64)
                chunks.append(ResponseChunk(
                    payload=chunk_data,
                    seq=i,
                    offset=None,
                    len=None,
                    is_eof=(i == len(chunks_b64) - 1),
                ))
            return PluginResponse.streaming(chunks)
        else:
            payload_b64 = response.get("payload_b64", "")
            payload_bytes = base64.b64decode(payload_b64) if payload_b64 else b""
            return PluginResponse.single(payload_bytes)

    async def run_throughput(self, payload_mb: int = 5) -> dict:
        """Run a throughput benchmark inside the host binary.

        The host calls generate_large internally via CBOR (chunked),
        measures wall-clock time, and returns only the metric.
        No payload crosses the JSON-line boundary.

        Returns:
            Dict with keys: ok, payload_mb, duration_s, mb_per_sec
        """
        response = await self._host.send_command({
            "cmd": "throughput",
            "payload_mb": payload_mb,
        })

        if not response.get("ok"):
            raise HostProcessError(
                f"Throughput failed: {response.get('error', 'unknown error')}"
            )

        return response

    async def send_heartbeat(self):
        """Send heartbeat via the remote host."""
        response = await self._host.send_command({"cmd": "send_heartbeat"})
        if not response.get("ok"):
            raise HostProcessError(
                f"Heartbeat failed: {response.get('error', 'unknown error')}"
            )

    def get_plugin_manifest(self) -> Optional[bytes]:
        """Return the plugin manifest received during spawn."""
        return self._manifest

    async def get_manifest(self) -> Optional[bytes]:
        """Fetch manifest from the remote host."""
        response = await self._host.send_command({"cmd": "get_manifest"})
        if not response.get("ok"):
            raise HostProcessError(
                f"get_manifest failed: {response.get('error', 'unknown error')}"
            )
        manifest_b64 = response.get("manifest_b64")
        if manifest_b64:
            self._manifest = base64.b64decode(manifest_b64)
        return self._manifest

    async def shutdown(self):
        """Send shutdown command to the remote host."""
        try:
            response = await self._host.send_command({"cmd": "shutdown"})
            if not response.get("ok"):
                pass  # Best effort
        except Exception:
            pass  # Best effort on shutdown
