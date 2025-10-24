try:
    from ._version import version as __version__  # type: ignore[attr-defined]
except ImportError:
    __version__ = "0.0.0"  # or None as a safe fallback
