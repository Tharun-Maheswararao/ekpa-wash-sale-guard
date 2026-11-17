"""One converter per broker format, all producing the common Transaction format."""
from __future__ import annotations

from . import common, fidelity, schwab
from .base import ConversionResult

CONVERTERS = {m.FORMAT_ID: m for m in (schwab, fidelity, common)}


def formats() -> list[dict]:
    return [{"id": m.FORMAT_ID, "label": m.LABEL} for m in CONVERTERS.values()]


def detect(text: str) -> str:
    for format_id, module in CONVERTERS.items():
        if module.sniff(text):
            return format_id
    raise ValueError("Couldn't recognize this file. Pick the broker format by hand.")


def convert(text: str, account_id: str, format_id: str = "auto") -> tuple[str, ConversionResult]:
    if format_id == "auto":
        format_id = detect(text)
    if format_id not in CONVERTERS:
        raise ValueError(f"Unknown format {format_id!r}")
    return format_id, CONVERTERS[format_id].parse(text, account_id)


__all__ = ["CONVERTERS", "ConversionResult", "convert", "detect", "formats"]
