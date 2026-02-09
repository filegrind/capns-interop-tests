"""Plugin subprocess lifecycle management."""

import asyncio
import sys
from pathlib import Path
from typing import Tuple, Optional

# Ensure asyncio is available for subprocess operations
import asyncio.subprocess


class PluginProcess:
    """Manages lifecycle of a plugin subprocess."""

    def __init__(self, binary_path: Path):
        self.binary_path = binary_path
        self.process: Optional[asyncio.subprocess.Process] = None
        self._stderr_task: Optional[asyncio.Task] = None
        self._stderr_buffer = bytearray()

    async def start(self) -> Tuple[asyncio.StreamWriter, asyncio.StreamReader]:
        """Spawn plugin and return stdin/stdout streams."""
        # Handle Python scripts specially
        if self.binary_path.suffix == ".py":
            cmd = [sys.executable, str(self.binary_path)]
        else:
            cmd = [str(self.binary_path)]

        self.process = await asyncio.create_subprocess_exec(
            *cmd,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        if not self.process.stdin or not self.process.stdout:
            # Read stderr for diagnostic
            if self.process.stderr:
                stderr_data = await self.process.stderr.read()
                raise RuntimeError(f"Failed to create stdin/stdout pipes. Stderr: {stderr_data.decode()}")
            raise RuntimeError("Failed to create stdin/stdout pipes")

        # Continuously drain stderr to prevent pipe buffer deadlock.
        # Plugin runtimes write debug logs to stderr; if nobody reads,
        # the pipe buffer fills (~64KB on macOS) and blocks the plugin.
        self._stderr_task = asyncio.create_task(self._drain_stderr())

        return self.process.stdin, self.process.stdout

    async def _drain_stderr(self):
        """Continuously read stderr to prevent pipe buffer blocking."""
        if not self.process or not self.process.stderr:
            return
        try:
            while True:
                chunk = await self.process.stderr.read(8192)
                if not chunk:
                    break
                self._stderr_buffer.extend(chunk)
        except Exception:
            pass

    async def get_stderr(self) -> str:
        """Return accumulated stderr output."""
        return self._stderr_buffer.decode('utf-8', errors='replace')

    def _cancel_stderr_task(self):
        if self._stderr_task and not self._stderr_task.done():
            self._stderr_task.cancel()

    async def stop(self, timeout: float = 5.0):
        """Gracefully stop plugin (close stdin, wait for exit)."""
        if not self.process:
            return

        # Close stdin = graceful shutdown signal
        if self.process.stdin:
            self.process.stdin.close()
            try:
                await self.process.stdin.wait_closed()
            except Exception:
                pass

        try:
            await asyncio.wait_for(self.process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            self.process.kill()
            await self.process.wait()

        self._cancel_stderr_task()

    async def kill(self):
        """Force kill immediately."""
        self._cancel_stderr_task()
        if self.process:
            try:
                self.process.kill()
                await self.process.wait()
            except Exception:
                pass

    def is_running(self) -> bool:
        """Check if process is still running."""
        return self.process is not None and self.process.returncode is None
