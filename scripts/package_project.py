"""Create a source/notebook bundle without secrets, virtual environments or user data."""

import argparse
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, default=Path("/tmp/local-ai-sales-intelligence.zip"))
arguments = parser.parse_args()
files = []
for directory in [
    "sales_intelligence",
    "scripts",
    "tests",
    "notebooks",
    "workflows",
    "docs",
    "sample_data",
    "frontend",
]:
    for path in (ROOT / directory).rglob("*"):
        relative = path.relative_to(ROOT)
        if path.is_file() and not any(
            part in {"node_modules", "dist", "__pycache__", ".ipynb_checkpoints"} for part in relative.parts
        ):
            files.append(path)
for name in [
    "README.md",
    "pyproject.toml",
    "requirements.lock.txt",
    "requirements-dev.lock.txt",
    ".env.example",
    ".gitignore",
    ".dockerignore",
    "Dockerfile",
    "compose.yaml",
]:
    files.append(ROOT / name)
with zipfile.ZipFile(arguments.output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(files):
        archive.write(path, Path("local-ai-sales-intelligence") / path.relative_to(ROOT))
with zipfile.ZipFile(arguments.output) as archive:
    assert archive.testzip() is None
    assert all(Path(name).name != ".env" for name in archive.namelist())
print(f"Packaged {len(files)} files: {arguments.output.resolve()}")
