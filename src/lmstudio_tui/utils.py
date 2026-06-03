"""Shared utility functions for LM Studio TUI."""

from __future__ import annotations

import re


def format_context_length(tokens: int) -> str:
    """Format a token count as a compact human-readable string (e.g. 65536 → '64K')."""
    if tokens <= 0:
        return "-"
    if tokens >= 1024:
        return f"{tokens // 1024}K"
    return str(tokens)


def format_size(size_bytes: int) -> str:
    """Format a byte count into a human-readable string.

    Args:
        size_bytes: Size in bytes.

    Returns:
        Human-readable size string (e.g. "4.2 GB", "512 MB").
    """
    if size_bytes >= 1024 ** 3:
        return f"{size_bytes / (1024 ** 3):.1f} GB"
    elif size_bytes >= 1024 ** 2:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.1f} KB"
    else:
        return f"{size_bytes} B"


def extract_quantization(model_name: str) -> str:
    """Extract quantization string from a model filename or ID.

    Args:
        model_name: Model filename or identifier.

    Returns:
        Quantization label (e.g. "Q4_K_M", "FP16") or "-" if not found.
    """
    patterns = [
        r'-(Q\d+_[KMS]_[ML]?)',
        r'-(Q\d+_[KMS])',
        r'-(Q\d+[A-Z]?)',
        r'-(FP16)',
        r'-(FP32)',
    ]
    for pattern in patterns:
        match = re.search(pattern, model_name, re.IGNORECASE)
        if match:
            return match.group(1).upper()
    return "-"
