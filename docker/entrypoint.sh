#!/bin/sh
# Keeps the scanner up to date from GitHub and scans every SCAN_MINUTES.
set -u
REPO="${REPO:-https://github.com/kreyastus/pokemon-drop-alerts-nz.git}"
CONFIG="${CONFIG:-stores-home.yaml}"
MINUTES="${SCAN_MINUTES:-10}"
cd /app
if [ ! -d src/.git ]; then
	git clone --depth 1 "$REPO" src || exit 1
fi
n=0
while true; do
	# Update the code about once an hour.
	if [ $((n % 6)) -eq 0 ]; then
		(cd src && git pull --ff-only -q) || echo "Couldn't update the code; using the copy we have."
		pip install -q --no-cache-dir -r src/requirements.txt || echo "Couldn't install requirements."
	fi
	(cd src && python -m pokedrop -c "$CONFIG" -s /app/data/state-home.json scan "$@") || echo "Scan failed; trying again next round."
	n=$((n + 1))
	sleep $((MINUTES * 60))
done
