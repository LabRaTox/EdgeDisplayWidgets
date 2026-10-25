#!/bin/sh
# The backend, as the package installs it: the code lives under
# /usr/share/edge-dashboard and runs on the system Python with the system's
# packages. In a checkout, `uv run python -m backend.main` does the same.
export PYTHONPATH="/usr/share/edge-dashboard${PYTHONPATH:+:$PYTHONPATH}"
exec /usr/bin/python3 -m backend.main "$@"
