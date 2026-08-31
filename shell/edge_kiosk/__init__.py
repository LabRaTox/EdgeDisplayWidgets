"""Native kiosk shell for the Edge Dashboard.

Runs on the *system* Python, not the project's virtualenv: it needs the
distribution's PySide6, which links against the system Qt WebEngine — the
build that carries the proprietary codecs the YouTube widget needs. The
backend keeps its own virtualenv; the two processes only meet over HTTP.
"""

__version__ = "1.0.0"
