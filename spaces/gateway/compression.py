"""Zstandard decompression utility for extracting cached document bodies."""

import zstandard as zstd

_DECOMPRESSOR = zstd.ZstdDecompressor()


def decompress_text(compressed_bytes: bytes) -> str:
    """Decompress Zstandard compressed bytes into a UTF-8 markdown string.

    Args:
        compressed_bytes: Raw Zstandard compressed binary data.

    Returns:
        Decompressed text string. Returns empty string if input is empty.
    """
    if not compressed_bytes:
        return ""
    try:
        return _DECOMPRESSOR.decompress(compressed_bytes).decode("utf-8")
    except Exception:
        return ""

