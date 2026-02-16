"""Helper for tests that communicate via raw CBOR frames.

Provides utilities for sending requests and reading responses through
PluginHost or RelaySlave interfaces (stdin/stdout of test binaries).
"""

import hashlib
import os
import subprocess
import sys
import threading
from pathlib import Path
from typing import List, Optional, Tuple

# Add capns-py to path
_project_root = Path(__file__).parent.parent.parent.parent.parent
sys.path.insert(0, str(_project_root / "capns-py" / "src"))
sys.path.insert(0, str(_project_root / "tagged-urn-py" / "src"))

from capns.bifaci.frame import Frame, FrameType, Limits, MessageId, compute_checksum
from capns.bifaci.io import FrameReader, FrameWriter


def make_req_id() -> MessageId:
    """Generate a random UUID message ID."""
    return MessageId.new_uuid()


def send_request(
    writer: FrameWriter,
    req_id: MessageId,
    cap_urn: str,
    payload: bytes,
    content_type: str = "application/octet-stream",
    media_urn: str = "media:bytes",
) -> None:
    """Send a complete request: REQ(empty) + STREAM_START + CHUNK(s) + STREAM_END + END.

    REQ must have empty payload per protocol v2. Arguments go via streaming.
    Large payloads are automatically chunked according to protocol limits.

    PROTOCOL: Each CHUNK payload MUST be a complete, independently decodable CBOR value.
    Raw bytes are CBOR-encoded as byte strings before being sent in CHUNK frames.
    """
    import cbor2

    # Use negotiated max_chunk from default limits (256KB)
    max_chunk = Limits.default().max_chunk

    writer.write(Frame.req(req_id, cap_urn, b"", content_type))
    stream_id = "arg-0"
    writer.write(Frame.stream_start(req_id, stream_id, media_urn))

    # Chunk large payloads and CBOR-encode each chunk
    offset = 0
    seq = 0
    chunk_index = 0
    while offset < len(payload):
        chunk_size = min(max_chunk, len(payload) - offset)
        chunk_bytes = payload[offset:offset + chunk_size]

        # CBOR-encode chunk as byte string - independently decodable
        cbor_payload = cbor2.dumps(chunk_bytes)
        checksum = compute_checksum(cbor_payload)

        writer.write(Frame.chunk(req_id, stream_id, seq, cbor_payload, chunk_index, checksum))
        offset += chunk_size
        seq += 1
        chunk_index += 1

    # Send at least one CHUNK even for empty payload (to match protocol)
    if len(payload) == 0:
        cbor_payload = cbor2.dumps(b"")
        checksum = compute_checksum(cbor_payload)
        writer.write(Frame.chunk(req_id, stream_id, 0, cbor_payload, 0, checksum))
        chunk_index = 1

    chunk_count = chunk_index
    writer.write(Frame.stream_end(req_id, stream_id, chunk_count))
    writer.write(Frame.end(req_id))


def send_simple_request(
    writer: FrameWriter,
    req_id: MessageId,
    cap_urn: str,
    content_type: str = "application/octet-stream",
) -> None:
    """Send a request with no payload: REQ(empty) + END."""
    writer.write(Frame.req(req_id, cap_urn, b"", content_type))
    writer.write(Frame.end(req_id))


def read_response(reader: FrameReader, timeout_frames: int = 100):
    """Read a complete response, collecting all frames until END or ERR.

    Each CHUNK payload MUST be a complete, independently decodable CBOR value.
    This decodes each chunk and reconstructs the final value according to protocol:
    - Bytes/Text: multiple chunks concatenated
    - Int/Float/Bool/Null: single chunk, return value
    - Array: multiple chunks (each is element), collect to list
    - Map: multiple chunks (each is [key, value]), collect to dict

    FAILS HARD if any chunk is not valid CBOR - no fallbacks.

    Returns:
        (reconstructed_value, all_frames) where value can be any CBOR type
    """
    import cbor2
    chunks = []
    frames = []

    for _ in range(timeout_frames):
        frame = reader.read()
        if frame is None:
            break

        frames.append(frame)
        if frame.frame_type == FrameType.CHUNK and frame.payload:
            # Each CHUNK MUST be independently decodable - fail hard if not
            decoded = cbor2.loads(frame.payload)  # No try/except - fail on invalid CBOR
            chunks.append(decoded)
        if frame.frame_type in (FrameType.END, FrameType.ERR):
            break

    # Reconstruct value from chunks according to protocol
    if not chunks:
        return b'', frames
    elif len(chunks) == 1:
        # Single chunk: return value as-is (int/float/bool/null/bytes/text/etc)
        return chunks[0], frames
    else:
        # Multiple chunks: reconstruct based on type
        first = chunks[0]
        if isinstance(first, bytes):
            # Bytes: concatenate all chunks
            result = b''.join(c for c in chunks if isinstance(c, bytes))
            return result, frames
        elif isinstance(first, str):
            # Text: concatenate all chunks
            result = ''.join(c for c in chunks if isinstance(c, str))
            return result, frames
        elif isinstance(first, list) and len(first) == 2:
            # Map chunks: each chunk is [key, value] pair
            result = {}
            for chunk in chunks:
                if isinstance(chunk, list) and len(chunk) == 2:
                    result[chunk[0]] = chunk[1]
            return result, frames
        else:
            # Array chunks: each chunk is an element
            return chunks, frames


def read_until_frame_type(reader: FrameReader, target: FrameType, max_frames: int = 50) -> Optional[Frame]:
    """Read frames until we find one of the given type."""
    for _ in range(max_frames):
        frame = reader.read()
        if frame is None:
            return None
        if frame.frame_type == target:
            return frame
    return None


def decode_cbor_response(raw_chunks: bytes) -> bytes:
    """Decode CBOR value from response chunks.

    With new protocol, this is rarely needed since read_response() decodes chunks.
    FAILS HARD if not valid CBOR - no fallbacks.
    """
    import cbor2
    return cbor2.loads(raw_chunks)  # No try/except - fail on invalid CBOR


class HostProcess:
    """Manages a relay host binary subprocess with CBOR frame I/O."""

    def __init__(self, binary_path: str, plugin_paths: List[str], relay: bool = False):
        self.binary_path = binary_path
        self.plugin_paths = plugin_paths
        self.relay = relay
        self.proc: Optional[subprocess.Popen] = None
        self.reader: Optional[FrameReader] = None
        self.writer: Optional[FrameWriter] = None

    def start(self) -> Tuple[FrameReader, FrameWriter]:
        """Start the host binary and return (reader, writer) for frame I/O."""
        cmd = self._build_command()
        env = self._build_env()

        self.proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
        )

        # Drain stderr in background
        self._drain_stderr()

        self.reader = FrameReader(self.proc.stdout)
        self.writer = FrameWriter(self.proc.stdin)
        return self.reader, self.writer

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the host binary."""
        if self.proc is None:
            return
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=2)

    def _build_command(self) -> List[str]:
        cmd = []
        if self.binary_path.endswith(".py"):
            cmd = [sys.executable, self.binary_path]
        else:
            cmd = [self.binary_path]

        if self.relay:
            cmd.append("--relay")

        for path in self.plugin_paths:
            cmd.extend(["--spawn", path])

        return cmd

    def _build_env(self):
        env = os.environ.copy()
        env["PYTHON_EXECUTABLE"] = sys.executable
        # Add capns-py and tagged-urn-py to PYTHONPATH
        python_paths = [
            str(_project_root / "capns-py" / "src"),
            str(_project_root / "tagged-urn-py" / "src"),
        ]
        if "PYTHONPATH" in env:
            python_paths.append(env["PYTHONPATH"])
        env["PYTHONPATH"] = ":".join(python_paths)
        return env

    def _drain_stderr(self):
        def _drain():
            try:
                while True:
                    chunk = self.proc.stderr.read(8192)
                    if not chunk:
                        break
                    sys.stderr.buffer.write(chunk)
                    sys.stderr.buffer.flush()
            except Exception:
                pass

        t = threading.Thread(target=_drain, daemon=True)
        t.start()
