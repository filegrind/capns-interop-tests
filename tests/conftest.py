"""Pytest fixtures for interoperability tests."""

import json
import subprocess
import pytest
from pathlib import Path


def _needs_build(binary: Path, source_dir: Path) -> bool:
    """Check if a binary needs (re)building based on source modification times."""
    if not binary.exists():
        return True
    bin_mtime = binary.stat().st_mtime
    for src in source_dir.rglob("*"):
        if src.is_file() and src.stat().st_mtime > bin_mtime:
            return True
    return False


def _run_make(project_root: Path, target: str):
    """Run a Makefile target, fail hard on error."""
    result = subprocess.run(
        ["make", target],
        cwd=str(project_root),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"make {target} failed (exit {result.returncode}):\n{result.stderr}"
        )


@pytest.fixture(scope="session")
def project_root():
    """Return the project root directory."""
    return Path(__file__).parent.parent


@pytest.fixture(scope="session")
def plugin_binaries(project_root):
    """Return paths to built plugin binaries, auto-building if needed."""
    artifacts = project_root / "artifacts" / "build"
    src = project_root / "src" / "capns_interop" / "plugins"

    binaries = {
        "rust": artifacts / "rust" / "capns-interop-plugin-rust",
        "python": artifacts / "python" / "plugin.py",
        "swift": artifacts / "swift" / "capns-interop-plugin-swift",
        "go": artifacts / "go" / "capns-interop-plugin-go",
    }

    targets = {
        "rust": ("build-rust", src / "rust"),
        "python": ("build-python", src / "python"),
        "swift": ("build-swift", src / "swift"),
        "go": ("build-go", src / "go"),
    }

    for lang, (target, source_dir) in targets.items():
        if _needs_build(binaries[lang], source_dir):
            print(f"\nAuto-building {lang} plugin...")
            _run_make(project_root, target)

    return binaries


@pytest.fixture(scope="session")
def host_binaries(project_root):
    """Return paths to built test host binaries, auto-building if needed."""
    artifacts = project_root / "artifacts" / "build"
    hosts_src = project_root / "src" / "capns_interop" / "hosts"

    binaries = {
        "rust": artifacts / "rust-host" / "capns-interop-host-rust",
        "python": hosts_src / "python" / "host.py",
        "swift": artifacts / "swift-host" / "capns-interop-host-swift",
        "go": artifacts / "go-host" / "capns-interop-host-go",
    }

    targets = {
        "rust": ("build-rust-host", hosts_src / "rust"),
        "swift": ("build-swift-host", hosts_src / "swift"),
        "go": ("build-go-host", hosts_src / "go"),
    }

    for lang, (target, source_dir) in targets.items():
        if _needs_build(binaries[lang], source_dir):
            print(f"\nAuto-building {lang} host...")
            _run_make(project_root, target)

    return binaries


def _print_throughput_matrix(results: dict):
    """Print throughput matrix table to stdout."""
    langs = ["rust", "go", "python", "swift"]
    print()
    print("━━━ THROUGHPUT MATRIX (MB/s)")
    print()
    header = "host ↓ \\ plugin →"
    print(f"  {header:>20}", end="")
    for p in langs:
        print(f"  {p:>8}", end="")
    print()
    print(f"  {'─' * 20}", end="")
    for _ in langs:
        print(f"  {'─' * 8}", end="")
    print()
    rows = []
    for h in langs:
        print(f"  {h:>20}", end="")
        for p in langs:
            cell = results.get(h, {}).get(p)
            if cell is None:
                print(f"  {'--':>8}", end="")
            elif cell.get("status") == "pass" and cell.get("mb_per_sec") is not None:
                print(f"  {cell['mb_per_sec']:>8.2f}", end="")
                rows.append((f"{h}-{p}", cell["mb_per_sec"]))
            else:
                print(f"  {'X':>8}", end="")
                rows.append((f"{h}-{p}", None))
        print()
    print()
    # Sorted ranking: passing combos descending by throughput, then failures
    rows.sort(key=lambda r: (r[1] is None, -(r[1] or 0)))
    for label, val in rows:
        if val is not None:
            print(f"  {label:<20} {val:>8.2f} MB/s")
        else:
            print(f"  {label:<20} {'X':>8}")
    print()


@pytest.fixture(scope="session")
def throughput_collector(project_root):
    """Collect throughput matrix results, write JSON, and print table at session end."""
    results = {}
    yield results
    if not results:
        return
    output_path = project_root / "artifacts" / "throughput_matrix.json"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w") as f:
        json.dump(results, f, indent=2)
    _print_throughput_matrix(results)


@pytest.fixture
def rust_plugin(plugin_binaries):
    """Return path to Rust plugin."""
    return plugin_binaries["rust"]


@pytest.fixture
def python_plugin(plugin_binaries):
    """Return path to Python plugin."""
    return plugin_binaries["python"]


@pytest.fixture
def swift_plugin(plugin_binaries):
    """Return path to Swift plugin."""
    return plugin_binaries["swift"]


@pytest.fixture
def go_plugin(plugin_binaries):
    """Return path to Go plugin."""
    return plugin_binaries["go"]
