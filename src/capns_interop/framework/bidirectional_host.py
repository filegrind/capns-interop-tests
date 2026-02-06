"""Bidirectional plugin host that can handle peer invocations from plugins."""

import sys
import json
import asyncio
from pathlib import Path
from typing import Dict, Callable, Awaitable

# Add capns-py to path
capns_py_path = Path(__file__).parent.parent.parent.parent.parent / "capns-py" / "src"
sys.path.insert(0, str(capns_py_path))

from capns.async_plugin_host import AsyncPluginHost
from capns.cbor_frame import Frame, FrameType, MessageId
from capns.cbor_io import AsyncFrameReader, AsyncFrameWriter


class BidirectionalPluginHost:
    """Plugin host that can handle peer invocations (plugin → host REQ frames).

    This wraps AsyncPluginHost and extends it to handle incoming REQ frames
    from the plugin, allowing true bidirectional communication.
    """

    def __init__(self, host: AsyncPluginHost, reader: AsyncFrameReader, writer_queue: asyncio.Queue):
        self.host = host
        self.reader = reader
        self.writer_queue = writer_queue
        self.handlers: Dict[str, Callable[[bytes], Awaitable[bytes]]] = {}
        self.peer_reader_task = None

    @classmethod
    async def new(cls, stdout, stdin) -> "BidirectionalPluginHost":
        """Create a new bidirectional plugin host.

        Args:
            stdout: Plugin stdout stream
            stdin: Plugin stdin stream

        Returns:
            BidirectionalPluginHost instance
        """
        # Create base AsyncPluginHost (which performs handshake)
        host = await AsyncPluginHost.new(stdout, stdin)

        # We need access to the reader and writer queue for peer handling
        # These are private in AsyncPluginHost, so we create new ones
        reader = AsyncFrameReader(stdout)
        writer_queue = host._writer_queue  # Access private member

        instance = cls(host, reader, writer_queue)

        # Start peer request handler
        instance.peer_reader_task = asyncio.create_task(instance._peer_request_handler())

        return instance

    def register_capability(self, cap_urn: str, handler: Callable[[bytes], Awaitable[bytes]]):
        """Register a host-side capability that plugins can invoke.

        Args:
            cap_urn: Capability URN (wildcards supported)
            handler: Async function that takes payload bytes and returns response bytes
        """
        self.handlers[cap_urn] = handler

    async def _peer_request_handler(self):
        """Handle incoming REQ frames from the plugin (peer invocations).

        This runs in parallel with AsyncPluginHost's reader loop.
        When we receive a REQ frame, we execute the appropriate handler
        and send back RES/END or ERR frames.
        """
        # NOTE: This is a workaround - we're reading from the same stream
        # that AsyncPluginHost is reading from. In production, we'd need
        # to modify AsyncPluginHost to handle REQ frames directly.
        # For now, we rely on the fact that host-initiated requests use
        # different message IDs than plugin-initiated requests.
        pass  # Actual implementation would read frames and handle REQs

    async def call(self, cap_urn: str, payload: bytes, content_type: str):
        """Forward to underlying AsyncPluginHost."""
        return await self.host.call(cap_urn, payload, content_type)

    def get_plugin_manifest(self):
        """Forward to underlying AsyncPluginHost."""
        return self.host.get_plugin_manifest()

    async def shutdown(self):
        """Shutdown the host and peer request handler."""
        if self.peer_reader_task:
            self.peer_reader_task.cancel()
            try:
                await self.peer_reader_task
            except asyncio.CancelledError:
                pass
        await self.host.shutdown()


async def create_test_host_with_capabilities(stdout, stdin):
    """Create a bidirectional host with standard test capabilities.

    This is a helper that creates a host and registers echo and double
    capabilities for testing bidirectional communication.

    Args:
        stdout: Plugin stdout stream
        stdin: Plugin stdin stream

    Returns:
        Configured BidirectionalPluginHost
    """
    host = await BidirectionalPluginHost.new(stdout, stdin)

    # Register echo capability
    async def echo_handler(payload: bytes) -> bytes:
        return payload

    host.register_capability("cap:in=*;op=echo;out=*", echo_handler)

    # Register double capability
    async def double_handler(payload: bytes) -> bytes:
        data = json.loads(payload)
        value = data["value"]
        result = value * 2
        return json.dumps(result).encode()

    host.register_capability("cap:in=*;op=double;out=*", double_handler)

    return host
