"""Static validation for the Git-backed Colab launcher."""

from __future__ import annotations

import json
from pathlib import Path

NOTEBOOK = Path("dist/CNC_Part_Analyzer_Colab.ipynb")
EXPECTED_REPOSITORY = "https://github.com/MrZeeshan6009/CNC.git"

document = json.loads(NOTEBOOK.read_text(encoding="utf-8"))
code_cells = [cell for cell in document["cells"] if cell["cell_type"] == "code"]
assert len(code_cells) == 3, f"expected three code cells, found {len(code_cells)}"

source = "\n".join("".join(cell["source"]) for cell in code_cells)
for index, cell in enumerate(code_cells, start=1):
    compile("".join(cell["source"]), f"colab_cell_{index}", "exec")

assert EXPECTED_REPOSITORY in source
assert '"git", "clone"' in source
assert "DEEPSEEK_API_KEY" in source
assert "cnc_stretch_dataset.zip" in source
assert "trycloudflare" in source
assert "base64" not in source.lower(), "notebook must not contain an embedded Base64 project"
assert 'Path(".env")' not in source and "dotenv" not in source, "notebook must not load a local secret file"

print(f"Notebook cells: {len(document['cells'])} total, {len(code_cells)} code")
print(f"Repository: {EXPECTED_REPOSITORY}")
print("No embedded application or secret found")
print("COLAB NOTEBOOK VALIDATION PASSED")
