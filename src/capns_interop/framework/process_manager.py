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

        return self.process.stdin, self.process.stdout

    async def get_stderr(self) -> str:
        """Read stderr output from process (non-blocking)."""
        if not self.process or not self.process.stderr:
            return ""

        try:
            # Try to read available stderr without blocking
            data = b""
            while True:
                try:
                    chunk = await asyncio.wait_for(
                        self.process.stderr.read(1024),
                        timeout=0.01
                    )
                    if not chunk:
                        break
                    data += chunk
                except asyncio.TimeoutError:
                    break
            return data.decode('utf-8', errors='replace')
        except Exception:
            return ""

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
                pass  # Already closed

        try:
            await asyncio.wait_for(self.process.wait(), timeout=timeout)
        except asyncio.TimeoutError:
            # Force kill if doesn't exit
            self.process.kill()
            await self.process.wait()

    async def kill(self):
        """Force kill immediately."""
        if self.process:
            try:
                self.process.kill()
                await self.process.wait()
            except Exception:
                pass  # Already dead

    def is_running(self) -> bool:
        """Check if process is still running."""
        return self.process is not None and self.process.returncode is None
