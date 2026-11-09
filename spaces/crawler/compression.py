"""Zstandard compression and decompression for web pages and markdown."""

import zstandard as zstd

_COMPRESSOR = zstd.ZstdCompressor(level=3)
_DECOMPRESSOR = zstd.ZstdDecompressor()


def compress_text(text: str) -> bytes:
    """Compress a text string into Zstandard binary bytes.

    Args:
        text: Plain text or markdown string.

    Returns:
        Zstandard compressed bytes.
    """
    if not text:
        return b""
    return _COMPRESSOR.compress(text.encode("utf-8"))


def decompress_text(compressed_bytes: bytes) -> str:
    """Decompress Zstandard compressed bytes back into a text string.

    Args:
        compressed_bytes: Raw Zstandard bytes.

    Returns:
        Decompressed UTF-8 string.
    """
    if not compressed_bytes:
        return ""
    try:
        return _DECOMPRESSOR.decompress(compressed_bytes).decode("utf-8")
    except Exception:
        return ""
