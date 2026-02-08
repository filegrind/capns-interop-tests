"""CLI mode plugin invocation for file-path conversion testing.

Provides utilities to:
1. Invoke plugins in CLI mode (not CBOR stdin/stdout mode)
2. Parse CBOR responses
3. Validate file-path auto-conversion behavior
"""

import subprocess
import json
from pathlib import Path
from typing import Dict, Any, Optional


def invoke_plugin_cli(
    plugin_binary: Path,
    cap_urn: str,
    args: Dict[str, str],
    timeout: int = 30
) -> Dict[str, Any]:
    """Invoke plugin in CLI mode with arguments.

    Args:
        plugin_binary: Path to plugin executable
        cap_urn: Capability URN to invoke
        args: Dictionary of argument name -> value
        timeout: Timeout in seconds

    Returns:
        Parsed response as dictionary

    Raises:
        subprocess.CalledProcessError: If plugin exits with non-zero code
        json.JSONDecodeError: If response is not valid JSON
    """
    # Build command line arguments
    cmd = [str(plugin_binary)]

    # Add capability URN (typically as first positional arg or via flag)
    # For now, assume plugins accept cap URN as first arg
    cmd.append(cap_urn)

    # Add named arguments as CLI flags
    for arg_name, arg_value in args.items():
        # Convert arg_name to CLI flag format (e.g., "input_file" -> "--input-file")
        flag_name = "--" + arg_name.replace("_", "-")
        cmd.extend([flag_name, arg_value])

    # Run plugin and capture output
    result = subprocess.run(
        cmd,
        capture_output=True,
        timeout=timeout,
        check=True  # Raise exception on non-zero exit
    )

    # Parse JSON output (plugins in CLI mode should output JSON to stdout)
    # Note: If output is CBOR, we'd need a CBOR parser here
    try:
        return json.loads(result.stdout.decode('utf-8'))
    except json.JSONDecodeError:
        # If not JSON, try parsing as CBOR
        # For now, just re-raise the JSON error
        raise


def invoke_plugin_cli_raw(
    plugin_binary: Path,
    args: list[str],
    timeout: int = 30
) -> bytes:
    """Invoke plugin with raw CLI arguments, return raw output.

    Args:
        plugin_binary: Path to plugin executable
        args: List of command-line arguments
        timeout: Timeout in seconds

    Returns:
        Raw stdout bytes
    """
    cmd = [str(plugin_binary)] + args

    result = subprocess.run(
        cmd,
        capture_output=True,
        timeout=timeout,
        check=True
    )

    return result.stdout


def parse_cbor_response(data: bytes) -> Any:
    """Parse CBOR response from plugin.

    Args:
        data: Raw CBOR bytes

    Returns:
        Parsed Python object
    """
    # This would require a CBOR library (e.g., cbor2)
    # For now, assume JSON output
    import cbor2
    return cbor2.loads(data)
