"""Core orchestration framework."""

from .process_manager import PluginProcess
from .orchestrator import Orchestrator
from .host_process import HostProcess
from .remote_host import RemoteHost
from .matrix_orchestrator import MatrixOrchestrator

__all__ = [
    "PluginProcess",
    "Orchestrator",
    "HostProcess",
    "RemoteHost",
    "MatrixOrchestrator",
]
