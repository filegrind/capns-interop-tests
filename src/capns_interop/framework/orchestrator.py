"""Coordinates plugin spawning and scenario execution."""

import sys
import json
from pathlib import Path

# Add capns-py to path
capns_py_path = Path(__file__).parent.parent.parent.parent.parent / "capns-py" / "src"
sys.path.insert(0, str(capns_py_path))

from capns.async_plugin_host import AsyncPluginHost
from .process_manager import PluginProcess
from ..scenarios.base import Scenario, ScenarioResult, ScenarioStatus


class Orchestrator:
    """Coordinates plugin spawning and scenario execution."""

    async def run_scenario(
        self, plugin_binary: Path, scenario: Scenario
    ) -> ScenarioResult:
        """Run single scenario against a plugin."""

        # Spawn plugin
        plugin = PluginProcess(plugin_binary)

        try:
            stdin, stdout = await plugin.start()

            # Give plugin a moment to initialize
            import asyncio
            await asyncio.sleep(0.1)

            # Create host with plugin's streams
            host = await AsyncPluginHost.new(stdout, stdin)

            # Register host capabilities for bidirectional communication
            await self._register_host_capabilities(host)

            # Verify manifest received
            manifest = host.get_plugin_manifest()
            if not manifest:
                return ScenarioResult(
                    status=ScenarioStatus.ERROR,
                    duration_ms=0.0,
                    error_message="No manifest received from plugin",
                )

            # Execute scenario
            result = await scenario.execute(host, plugin)

            # Cleanup
            await host.shutdown()
            await plugin.stop()

            return result

        except Exception as e:
            import traceback
            tb = traceback.format_exc()

            # Try to get stderr for diagnostic
            stderr_output = await plugin.get_stderr()
            error_detail = f"Orchestrator error: {str(e)}\n{tb}"
            if stderr_output:
                error_detail += f"\n\nPlugin stderr:\n{stderr_output}"

            await plugin.kill()
            return ScenarioResult(
                status=ScenarioStatus.ERROR,
                duration_ms=0.0,
                error_message=error_detail,
            )

    async def _register_host_capabilities(self, host: AsyncPluginHost):
        """Register host-side capabilities for bidirectional testing.

        Plugins can invoke these capabilities via PeerInvoker.
        """
        # Echo capability - returns input as-is
        async def echo_handler(payload: bytes) -> bytes:
            return payload

        host.register_capability("cap:in=*;op=echo;out=*", echo_handler)

        # Double capability - doubles a number
        async def double_handler(payload: bytes) -> bytes:
            data = json.loads(payload)
            value = data["value"]
            result = value * 2
            return json.dumps(result).encode()

        host.register_capability("cap:in=*;op=double;out=*", double_handler)
