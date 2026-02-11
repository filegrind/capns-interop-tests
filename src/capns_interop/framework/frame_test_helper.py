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

from capns.cbor_frame import Frame, FrameType, Limits, MessageId
from capns.cbor_io import FrameReader, FrameWriter


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
    """Send a complete request: REQ(empty) + STREAM_START + CHUNK + STREAM_END + END.

    REQ must have empty payload per protocol v2. Arguments go via streaming.
    """
    writer.write(Frame.req(req_id, cap_urn, b"", content_type))
    stream_id = "arg-0"
    writer.write(Frame.stream_start(req_id, stream_id, media_urn))
    writer.write(Frame.chunk(req_id, stream_id, 0, payload))
    writer.write(Frame.stream_end(req_id, stream_id))
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


def read_response(reader: FrameReader, timeout_frames: int = 100) -> Tuple[bytes, List[Frame]]:
    """Read a complete response, collecting all frames until END or ERR.

    Returns:
        (concatenated_chunk_data, all_frames)
    """
    chunks = bytearray()
    frames = []
    for _ in range(timeout_frames):
        frame = reader.read()
        if frame is None:
            break
        frames.append(frame)
        if frame.frame_type == FrameType.CHUNK:
            chunks.extend(frame.payload or b"")
        if frame.frame_type in (FrameType.END, FrameType.ERR):
            break
    return bytes(chunks), frames


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
    """Decode CBOR byte string from response chunks.

    Plugin handlers emit CBOR-encoded byteStrings. This extracts the raw bytes.
    """
    import cbor2
    try:
        return cbor2.loads(raw_chunks)
    except Exception:
        return raw_chunks


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
