"""Validate every notebook and execute the master with a private project-local kernel."""

import json
import os
import sys
from pathlib import Path

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]
cache = ROOT / ".cache"
kernel = cache / "jupyter/kernels/sales-check"
kernel.mkdir(parents=True, exist_ok=True)
(kernel / "kernel.json").write_text(
    json.dumps(
        {
            "argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
            "display_name": "Sales verification",
            "language": "python",
        }
    )
)
for variable, suffix in [
    ("JUPYTER_PATH", "jupyter"),
    ("JUPYTER_RUNTIME_DIR", "runtime"),
    ("IPYTHONDIR", "ipython"),
    ("MPLCONFIGDIR", "matplotlib"),
]:
    directory = cache / suffix
    directory.mkdir(parents=True, exist_ok=True)
    os.environ[variable] = str(directory)
notebooks = sorted((ROOT / "notebooks").glob("*.ipynb"))
for path in notebooks:
    notebook = nbformat.read(path, as_version=4)
    nbformat.validate(notebook)
    assert any(cell.cell_type == "code" for cell in notebook.cells)
print(f"Validated {len(notebooks)} notebook schemas.", flush=True)
path = ROOT / "notebooks/00_Local_AI_Sales_Intelligence.ipynb"
notebook = nbformat.read(path, as_version=4)
client = NotebookClient(
    notebook, timeout=240, kernel_name="sales-check", resources={"metadata": {"path": str(ROOT)}}
)
client.execute()
executed = ROOT / ".cache/00_Local_AI_Sales_Intelligence.executed.ipynb"
nbformat.write(notebook, executed)
errors = [
    output
    for cell in notebook.cells
    if cell.cell_type == "code"
    for output in cell.get("outputs", [])
    if output.output_type == "error"
]
assert not errors, errors
print(
    f"Executed {sum(cell.cell_type == 'code' for cell in notebook.cells)} master notebook code cells without errors.",
    flush=True,
)
print(f"Executed copy: {executed}")
