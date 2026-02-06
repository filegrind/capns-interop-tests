"""Pytest fixtures for interoperability tests."""

import pytest
from pathlib import Path


@pytest.fixture(scope="session")
def project_root():
    """Return the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def plugin_binaries(project_root):
    """Return paths to built plugin binaries."""
    artifacts = project_root / "artifacts" / "build"

    binaries = {
        "rust": artifacts / "rust" / "capns-interop-plugin-rust",
        "python": artifacts / "python" / "plugin.py",
        "swift": artifacts / "swift" / "capns-interop-plugin-swift",
    }

    # Verify at least rust exists for basic tests
    if not binaries["rust"].exists():
        pytest.skip("Rust plugin not built. Run 'make build-rust' first.")

    return binaries


@pytest.fixture
def rust_plugin(plugin_binaries):
    """Return path to Rust plugin."""
    return plugin_binaries["rust"]


@pytest.fixture
def python_plugin(plugin_binaries):
    """Return path to Python plugin."""
    if not plugin_binaries["python"].exists():
        pytest.skip("Python plugin not built. Run 'make build-python' first.")
    return plugin_binaries["python"]


@pytest.fixture
def swift_plugin(plugin_binaries):
    """Return path to Swift plugin."""
    if not plugin_binaries["swift"].exists():
        pytest.skip("Swift plugin not built. Run 'make build-swift' first.")
    return plugin_binaries["swift"]
