"""Single source of truth for package metadata. No imports here on purpose:
this module must be readable very early (pyproject.toml reads it by
attribute) without triggering the rest of the package."""

__version__ = "0.1.0"
__author__ = "Martial Aristide Barra"
__email__ = "martialaristideb02@gmail.com"
