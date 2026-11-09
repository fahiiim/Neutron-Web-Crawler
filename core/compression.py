import json
import zstandard as zstd
from typing import Dict, Any

# Pre-initialized reusable compressor and decompressor
# Using compression level 3 gives an optimal ratio-to-speed tradeoff (<0.3ms per payload)
_cctx = zstd.ZstdCompressor(level=3)
_dctx = zstd.ZstdDecompressor()

def compress_metadata(meta: Dict[str, Any]) -> bytes:
    """Compress a document metadata dictionary (url, title, snippet) using Zstandard."""
    raw_json = json.dumps(meta, ensure_ascii=False, separators=(',', ':')).encode('utf-8')
    return _cctx.compress(raw_json)

def decompress_metadata(compressed_bytes: bytes) -> Dict[str, Any]:
    """Decompress Zstandard bytes back into a metadata dictionary."""
    if not compressed_bytes:
        return {}
    decompressed_json = _dctx.decompress(compressed_bytes).decode('utf-8')
    return json.loads(decompressed_json)

def compress_text(text: str) -> bytes:
    """Compress arbitrary text or markdown string."""
    return _cctx.compress(text.encode('utf-8'))

def decompress_text(compressed_bytes: bytes) -> str:
    """Decompress arbitrary bytes back into text string."""
    if not compressed_bytes:
        return ""
    return _dctx.decompress(compressed_bytes).decode('utf-8')

