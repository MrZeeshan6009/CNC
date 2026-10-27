"""Build the small Git-backed Colab launcher notebook."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST = ROOT / "dist"
DIST.mkdir(exist_ok=True)

REPOSITORY = "https://github.com/MrZeeshan6009/CNC.git"
BRANCH = "main"


def md(text: str) -> dict:
    return {"cell_type": "markdown", "metadata": {}, "source": text.splitlines(keepends=True)}


def code(text: str) -> dict:
    return {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "outputs": [],
        "source": text.strip("\n").splitlines(keepends=True),
    }


cells = [
    md(
        """# CNC Part Analyzer — Colab

Run the three cells in order using a **CPU runtime**. The final cell prints a public URL for the judges and must remain running.

Source: [github.com/MrZeeshan6009/CNC](https://github.com/MrZeeshan6009/CNC)
"""
    ),
    md("## 1. Install the application"),
    code(
        f'''import os, shutil, subprocess, sys, urllib.request
from pathlib import Path

REPOSITORY = "{REPOSITORY}"
BRANCH = "{BRANCH}"
PROJECT = Path("/content/CNC")

if PROJECT.exists():
    shutil.rmtree(PROJECT)

print("Downloading the application from GitHub...")
subprocess.run(
    ["git", "clone", "--depth", "1", "--branch", BRANCH, REPOSITORY, str(PROJECT)],
    check=True,
)
os.chdir(PROJECT)

print("Installing system libraries...")
subprocess.run(
    ["apt-get", "-qq", "update"],
    check=True,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.STDOUT,
)
subprocess.run(
    ["apt-get", "-qq", "install", "-y", "libgl1", "libglib2.0-0", "libgomp1"],
    check=True,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.STDOUT,
)

print("Installing Python packages...")
subprocess.run(
    [sys.executable, "-m", "pip", "install", "-q", "-r", "requirements.txt"],
    check=True,
)

cloudflared = Path("/usr/local/bin/cloudflared")
urllib.request.urlretrieve(
    "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64",
    cloudflared,
)
cloudflared.chmod(0o755)

import OCP, pymupdf  # noqa: F401
assert Path("app.py").is_file()
assert Path("outputs/stretch_dataset/cnc_stretch_dataset.zip").is_file()
print("Setup complete. CAD and PDF libraries are ready.")'''
    ),
    md("## 2. Add the DeepSeek key"),
    code(
        '''import os
from getpass import getpass

key = None
try:
    from google.colab import userdata
    key = userdata.get("DEEPSEEK_API_KEY")
except Exception:
    pass

if not key:
    key = getpass("DeepSeek API key: ")

os.environ["DEEPSEEK_API_KEY"] = key.strip()
os.environ["DEEPSEEK_MODEL"] = "deepseek-flash"
os.environ["DEEPSEEK_BASE_URL"] = "https://api.deepseek.com"
assert os.environ["DEEPSEEK_API_KEY"], "A DeepSeek key is required."
print("Key configured for this Colab session only.")'''
    ),
    md("## 3. Start the application"),
    code(
        '''import os, re, subprocess, time, urllib.request
from pathlib import Path

app_log = open("/content/cnc_streamlit.log", "w")
app = subprocess.Popen(
    [
        "streamlit", "run", "app.py",
        "--server.address=0.0.0.0",
        "--server.port=8501",
        "--server.headless=true",
        "--server.enableXsrfProtection=false",
        "--server.enableCORS=false",
    ],
    stdout=app_log,
    stderr=subprocess.STDOUT,
    env=os.environ.copy(),
)

for _ in range(60):
    try:
        health = urllib.request.urlopen(
            "http://127.0.0.1:8501/_stcore/health", timeout=5
        ).read().decode().strip()
        if health == "ok":
            break
    except Exception:
        pass
    time.sleep(2)
else:
    print(Path("/content/cnc_streamlit.log").read_text(errors="ignore")[-3000:])
    raise RuntimeError("The application did not start.")

tunnel_log = open("/content/cnc_tunnel.log", "w")
tunnel = subprocess.Popen(
    ["cloudflared", "tunnel", "--url", "http://127.0.0.1:8501", "--no-autoupdate"],
    stdout=tunnel_log,
    stderr=subprocess.STDOUT,
)

url = None
for _ in range(40):
    time.sleep(2)
    tunnel_output = Path("/content/cnc_tunnel.log").read_text(errors="ignore")
    match = re.search(r"https://[-a-z0-9]+\\.trycloudflare\\.com", tunnel_output)
    if match:
        url = match.group(0)
        break

if not url:
    print(Path("/content/cnc_tunnel.log").read_text(errors="ignore")[-3000:])
    raise RuntimeError("The public URL was not created.")

print("\\nCNC PART ANALYZER IS READY")
print("Judge URL:", url)
print("Demo URL: ", url + "/?dataset=demo")
print("\\nLeave this cell running during judging.\\n")

while True:
    time.sleep(300)
    try:
        state = urllib.request.urlopen(
            "http://127.0.0.1:8501/_stcore/health", timeout=10
        ).read().decode().strip()
    except Exception:
        state = "unavailable"
    print("heartbeat:", state, url, flush=True)'''
    ),
]

for index, cell in enumerate(cells):
    if cell["cell_type"] == "code":
        compile("".join(cell["source"]), f"cell_{index}", "exec")

notebook = {
    "cells": cells,
    "metadata": {
        "kernelspec": {"display_name": "Python 3", "name": "python3"},
        "language_info": {"name": "python"},
        "colab": {"provenance": [], "toc_visible": True},
    },
    "nbformat": 4,
    "nbformat_minor": 5,
}

target = DIST / "CNC_Part_Analyzer_Colab.ipynb"
target.write_text(json.dumps(notebook, indent=1), encoding="utf-8")
json.loads(target.read_text(encoding="utf-8"))
print(f"notebook: {target} ({target.stat().st_size / 1024:.0f} KB)")
