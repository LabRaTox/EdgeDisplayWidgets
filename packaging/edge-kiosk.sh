#!/bin/sh
# The kiosk window on the Xeneon Edge. `--help` lists the overrides
# (--output, --width/--height, --windowed, --url, --show-cursor).
export PYTHONPATH="/usr/share/edge-dashboard/shell${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 -m qml_kiosk.main "$@"
