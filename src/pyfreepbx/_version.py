"""Version fallback for editable installs without VCS."""

try:
    from importlib.metadata import version

    __version__ = version("pyfreepbx")
except Exception:
    __version__ = "0.0.0-dev"
