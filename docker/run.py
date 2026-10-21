"""PokéDrop NZ home scanner, for a plain python:3.12-slim container (Dockge,
TrueNAS, Portainer or `docker compose`). No image to build and no git needed:
it downloads the scanner from GitHub, keeps it up to date about once an hour
and scans every SCAN_MINUTES (default 10).

The compose file starts it with a one-line Python command that fetches this
file from the repo, so updating this file on GitHub updates every home scanner
on its next restart.
"""
import io
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request

REPO = os.environ.get("REPO", "kreyastus/pokemon-drop-alerts-nz")
BRANCH = os.environ.get("BRANCH", "main")
CONFIG = os.environ.get("CONFIG", "stores-home.yaml")
MINUTES = float(os.environ.get("SCAN_MINUTES", "10"))
UPDATE_HOURS = float(os.environ.get("UPDATE_HOURS", "1"))
APP = os.environ.get("APP_DIR", "/app")
SRC = os.path.join(APP, "src")
DATA = os.path.join(APP, "data")


def say(msg):
    print(time.strftime("%H:%M:%S"), msg, flush=True)


def update():
    """Downloads the latest code and swaps it in. Keeps the old copy if anything fails."""
    url = os.environ.get("CODE_URL") or f"https://codeload.github.com/{REPO}/tar.gz/refs/heads/{BRANCH}"
    try:
        with urllib.request.urlopen(url, timeout=60) as r:
            blob = r.read()
        new = SRC + ".new"
        shutil.rmtree(new, ignore_errors=True)
        os.makedirs(new)
        with tarfile.open(fileobj=io.BytesIO(blob), mode="r:gz") as tar:
            tar.extractall(new, filter="data")
        top = os.path.join(new, os.listdir(new)[0])   # the archive has one folder: repo-branch
        subprocess.run([sys.executable, "-m", "pip", "install", "-q", "--no-cache-dir",
                        "--disable-pip-version-check", "--root-user-action=ignore",
                        "-r", os.path.join(top, "requirements.txt")], check=True)
        old = SRC + ".old"
        shutil.rmtree(old, ignore_errors=True)
        if os.path.isdir(SRC):
            os.rename(SRC, old)
        os.rename(top, SRC)
        shutil.rmtree(new, ignore_errors=True)
        shutil.rmtree(old, ignore_errors=True)
        say("Scanner code is up to date.")
        return True
    except Exception as exc:  # noqa: BLE001
        say(f"Couldn't update the scanner code ({exc}); using the copy we have.")
        return os.path.isdir(SRC)


def main():
    os.makedirs(DATA, exist_ok=True)
    while not update():
        say("No scanner code yet; trying again in 5 minutes.")
        time.sleep(300)
    last_update = time.monotonic()
    while True:
        if time.monotonic() - last_update >= UPDATE_HOURS * 3600:
            update()
            last_update = time.monotonic()
        started = time.monotonic()
        result = subprocess.run([sys.executable, "-m", "pokedrop", "-c", CONFIG,
                                 "-s", os.path.join(DATA, "state-home.json"), "scan"], cwd=SRC)
        if result.returncode:
            say("Scan failed; trying again next round.")
        time.sleep(max(30, MINUTES * 60 - (time.monotonic() - started)))


main()
