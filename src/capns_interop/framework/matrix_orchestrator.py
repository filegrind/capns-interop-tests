"""Matrix orchestrator — coordinates host x plugin interop tests.

Starts a test host binary, tells it to spawn a plugin, runs a scenario
through the RemoteHost adapter, and shuts everything down.
"""

import traceback
from pathlib import Path

from .host_process import HostProcess
from .remote_host import RemoteHost
from ..scenarios.base import Scenario, ScenarioResult, ScenarioStatus


class MatrixOrchestrator:
    """Orchestrates cross-language host x plugin matrix tests.

    Uses the two-layer subprocess model:
        Python test (pytest) → test host binary → test plugin binary

    The test host binary speaks JSON-lines on its stdin/stdout
    and internally manages the CBOR protocol with the plugin.
    """

    def __init__(self, host_binary_path: Path):
        self.host_binary_path = host_binary_path

    async def run_scenario(
        self, plugin_path: Path, scenario: Scenario
    ) -> ScenarioResult:
        """Run a single scenario using the configured host against a plugin.

        Args:
            plugin_path: Path to plugin binary
            scenario: Test scenario to execute

        Returns:
            ScenarioResult with pass/fail status and timing
        """
        host_proc = HostProcess(self.host_binary_path)

        try:
            await host_proc.start()

            # Create RemoteHost adapter
            remote_host = RemoteHost(host_proc)

            # Tell the test host to spawn the plugin
            await remote_host.spawn_plugin(plugin_path)

            # Verify manifest received
            manifest = remote_host.get_plugin_manifest()
            if not manifest:
                return ScenarioResult(
                    status=ScenarioStatus.ERROR,
                    duration_ms=0.0,
                    error_message="No manifest received from plugin via remote host",
                )

            # Execute scenario using RemoteHost as the "host" interface
            # Scenarios expect an object with .call(), .send_heartbeat(), etc.
            result = await scenario.execute(remote_host, None)

            # Shutdown
            await remote_host.shutdown()
            await host_proc.stop()

            return result

        except Exception as e:
            tb = traceback.format_exc()
            stderr_output = await host_proc.get_stderr()
            error_detail = f"MatrixOrchestrator error: {str(e)}\n{tb}"
            if stderr_output:
                error_detail += f"\n\nHost stderr:\n{stderr_output}"

            await host_proc.kill()
            return ScenarioResult(
                status=ScenarioStatus.ERROR,
                duration_ms=0.0,
                error_message=error_detail,
            )
