"""Snow Watch: forecast pipeline, analysis and API."""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("snowwatch")  # from pyproject.toml, the one place it is set
except PackageNotFoundError:  # running from a source tree that was never installed
    __version__ = "0.0.0+unknown"
