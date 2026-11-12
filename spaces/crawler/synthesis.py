"""Query-focused excerpt extraction and extractive grounded answer synthesis."""

import re
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple
import urllib.parse

try:
    from .db_turso import (
        _term_matches_text,
        normalize_search_query,
        sanitize_fts_terms,
        score_document_relevance,
    )
    from .dedup import extract_domain_host
except ImportError:
    from db_turso import (
        _term_matches_text,
        normalize_search_query,
        sanitize_fts_terms,
        score_document_relevance,
    )
    from dedup import extract_domain_host

_PROTECT_WORDS_RE = re.compile(
    r"\b(?:Dr|Mr|Mrs|Ms|Prof|Sr|Jr|St|vs|etc|Fig|No|al|e\.g|i\.e|U\.S)\.",
    flags=re.IGNORECASE,
)
_INITIAL_DOT_RE = re.compile(r"(^|[\s(.\u0000])([A-Z])\.(?=\s*[A-Z])")
_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9\"'(\[])|\n+")
_INLINE_REF_RE = re.compile(
    r"\s*\[(?:\d+|citation needed|edit|update|clarification needed|note\s*\d+)\]",
    flags=re.IGNORECASE,
)
_IPA_PARENS_RE = re.compile(
    r"(?:(?<=\()|(?<=[;,]))\s*(?:(?:US|UK)\s*:\s*)?/[^/\n]{2,60}/(?:\s*(?:ⓘ|listen))?",
    flags=re.IGNORECASE,
)
_EMPTY_PAREN_SEP_RE = re.compile(r"\(\s*[;,:\s]+")
_PHOTO_AGENCIES = (
    r"(?:Getty Images|AP Photo|Reuters|AFP|Shutterstock|iStock|Alamy|Associated Press|Bloomberg)"
)
_PHOTO_CREDIT_PARENS_RE = re.compile(
    rf"\([^)]*\b{_PHOTO_AGENCIES}\b[^)]*\)",
    flags=re.IGNORECASE,
)
_PHOTO_CREDIT_PREFIX_RE = re.compile(
    rf"(?:^|(?<=[.!?]\s))[^.!?\n]{{0,120}}?(?:/\s*|photo\s+by\s+|credit:\s*){_PHOTO_AGENCIES}(?:\s+via\s+[A-Z][\w\s]{{0,30}})?[:.\s-]*",
    flags=re.IGNORECASE,
)
_SENTINEL = "\u0000"
_BOILERPLATE_PHRASES = (
    "accept cookies",
    "cookie policy",
    "privacy policy",
    "sign in to",
    "create account",
    "all rights reserved",
    "subscribe to our",
    "enable javascript",
    "click here",
)
_DEFINITION_CUE_RE = re.compile(
    r"\b(?:is a|is an|are a|refers to|known as|created by|written by|"
    r"authored by|founded by|uses a|works by)\b",
    flags=re.IGNORECASE,
)


def _sanitize_prose(text: str) -> str:
    """Remove markdown URLs, footnote brackets, Wikipedia IPA, and photo credits."""
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
    s = re.sub(r"(?:View image online\s*)?\(https?://[^)\s]+\)", "", s, flags=re.IGNORECASE)
    s = _INLINE_REF_RE.sub("", s)
    s = _PHOTO_CREDIT_PARENS_RE.sub("", s)
    s = _PHOTO_CREDIT_PREFIX_RE.sub("", s)
    s = _IPA_PARENS_RE.sub("", s)
    s = re.sub(r"\s*(?:\(\s*listen\s*\)|ⓘ)\s*", " ", s, flags=re.IGNORECASE)
    s = _EMPTY_PAREN_SEP_RE.sub("(", s)
    s = re.sub(r"\(\s*\(", "(", s)
    s = re.sub(r"\(\s*\)", "", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def _clean_sentences(raw_text: str) -> List[str]:
    """Split text/markdown into clean declarative prose sentences."""
    cleaned_lines: List[str] = []
    in_code = False
    for line in (raw_text or "").splitlines():
        s = line.strip()
        if s.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not s or s.startswith("#"):
            continue
        s = s.lstrip(">-*• ").strip()
        s = _sanitize_prose(s)
        if s:
            cleaned_lines.append(s)

    joined = " ".join(cleaned_lines)
    protected = _PROTECT_WORDS_RE.sub(lambda m: m.group(0)[:-1] + _SENTINEL, joined)
    for _ in range(3):
        protected = _INITIAL_DOT_RE.sub(
            lambda m: f"{m.group(1)}{m.group(2)}{_SENTINEL}", protected
        )
    parts = [
        p.replace(_SENTINEL, ".").strip()
        for p in _SENTENCE_SPLIT_RE.split(protected)
        if p.strip()
    ]
    return parts


def _token_jaccard(a: str, b: str) -> float:
    sa = set(re.findall(r"[a-z0-9]{3,}", a.lower()))
    sb = set(re.findall(r"[a-z0-9]{3,}", b.lower()))
    if not sa or not sb:
        return 0.0
    return len(sa & sb) / len(sa | sb)


def extract_query_focused_snippet(query: str, text: str, max_len: int = 320) -> str:
    """Return a concise excerpt centered on the highest query-matching sentences."""
    clean_full = _sanitize_prose(" ".join((text or "").split()))
    if not clean_full:
        return ""
    if len(clean_full) <= max_len:
        return clean_full

    terms = sanitize_fts_terms(query)
    if not terms:
        return clean_full[:max_len].rsplit(" ", 1)[0] + "..."

    sentences = [s for s in _clean_sentences(text) if len(s) >= 25]
    if not sentences:
        return clean_full[:max_len].rsplit(" ", 1)[0] + "..."

    best_idx = 0
    best_score = -1.0
    for idx, sent in enumerate(sentences[:30]):
        low = sent.lower()
        hits = sum(1 for t in terms if _term_matches_text(t, low))
        if hits == 0:
            continue
        # Favor multiple distinct terms + mild lead bias
        score = hits * 10.0 - idx * 0.25
        if score > best_score:
            best_score = score
            best_idx = idx

    if best_score <= 0:
        return clean_full[:max_len].rsplit(" ", 1)[0] + "..."

    excerpt_parts: List[str] = []
    total_len = 0
    for s in sentences[best_idx : best_idx + 3]:
        if total_len + len(s) + 1 > max_len and excerpt_parts:
            break
        excerpt_parts.append(s)
        total_len += len(s) + 1

    excerpt = " ".join(excerpt_parts).strip()
    if len(excerpt) > max_len:
        excerpt = excerpt[: max_len - 3].rsplit(" ", 1)[0] + "..."
    return excerpt


def synthesize_grounded_answer(
    query: str,
    docs: List[Dict[str, Any]],
    max_sentences: int = 4,
) -> Optional[Dict[str, Any]]:
    """Synthesize a cited extractive answer from top search hits and payloads."""
    terms = sanitize_fts_terms(query)
    if not terms or not docs:
        return None

    normalized_phrase = normalize_search_query(query).lower()
    candidates: List[Tuple[float, str, Dict[str, Any]]] = []

    for doc_idx, doc in enumerate(docs[:5]):
        raw_body = str(doc.get("full_text") or doc.get("raw_snippet") or doc.get("snippet") or "")
        sentences = _clean_sentences(raw_body)

        for sent_idx, sent in enumerate(sentences[:25]):
            if len(sent) < 30 or len(sent) > 320:
                continue
            low = sent.lower()
            if any(bp in low for bp in _BOILERPLATE_PHRASES):
                continue

            matched = sum(1 for t in terms if _term_matches_text(t, low))
            if matched == 0:
                continue
            if len(terms) >= 2 and matched < min(2, len(terms)) and sent_idx > 2:
                continue

            coverage = matched / len(terms)
            score = coverage * 20.0 + matched * 3.0
            if len(normalized_phrase) >= 4 and normalized_phrase in low:
                score += 6.0
            if _DEFINITION_CUE_RE.search(sent):
                score += 2.5
            score += max(0.0, 2.5 - doc_idx * 0.5)
            score += max(0.0, 1.5 - sent_idx * 0.2)

            candidates.append((score, sent, doc))

    if not candidates:
        return None

    candidates.sort(key=lambda item: item[0], reverse=True)

    selected: List[Tuple[str, Dict[str, Any]]] = []
    for _, sent, doc in candidates:
        if any(_token_jaccard(sent, prev_s) >= 0.55 for prev_s, _ in selected):
            continue
        selected.append((sent, doc))
        if len(selected) >= max_sentences:
            break

    if not selected:
        return None

    citation_map: Dict[str, int] = {}
    citations: List[Dict[str, Any]] = []
    summary_parts: List[str] = []

    for sent, doc in selected:
        url = str(doc.get("url") or "")
        if url not in citation_map:
            idx = len(citations) + 1
            citation_map[url] = idx
            host = urllib.parse.urlsplit(url).netloc.lower()
            domain = host[4:] if host.startswith("www.") else (host or "web")
            citations.append(
                {
                    "index": idx,
                    "title": str(doc.get("title") or domain),
                    "url": url,
                    "url_hash": str(doc.get("url_hash") or ""),
                    "domain": domain,
                }
            )
        cite_num = citation_map[url]
        summary_parts.append(f"{sent.rstrip()} [{cite_num}]")

    return {
        "summary": " ".join(summary_parts),
        "citations": citations,
        "mode": "extractive_grounded",
    }


MODE_DOMAINS: Dict[str, Tuple[str, ...]] = {
    "encyclopedia": ("wikipedia.org", "britannica.com", "stanford.edu"),
    "papers": (
        "arxiv.org",
        "acm.org",
        "ieee.org",
        "nature.com",
        "sciencedirect.com",
        "biorxiv.org",
    ),
    "code": (
        "github.com",
        "gitlab.com",
        "stackoverflow.com",
        "python.org",
        "rust-lang.org",
        "docs.",
    ),
    "discussions": ("reddit.com", "ycombinator.com", "lobste.rs", "dev.to"),
}


def filter_hits_by_mode(hits: List[Dict[str, Any]], mode: str) -> List[Dict[str, Any]]:
    """Optionally narrow indexed cache hits to vertical domains when a mode is active."""
    clean_mode = (mode or "all").lower()
    suffixes = MODE_DOMAINS.get(clean_mode)
    if not suffixes:
        return hits
    filtered: List[Dict[str, Any]] = []
    for item in hits:
        host = extract_domain_host(str(item.get("url") or ""))
        if any(s in host for s in suffixes):
            filtered.append(item)
    return filtered


_GEMINI_ENDPOINT_TMPL = (
    "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
)


def _clean_gemini_summary(raw_text: str) -> str:
    """Strip markdown styling or conversational preambles from Gemini output."""
    text = re.sub(r"\*\*([^*]+)\*\*", r"\1", (raw_text or "").strip())
    text = re.sub(r"^#+\s*", "", text, flags=re.MULTILINE)
    text = re.sub(
        r"^(?:here(?:'s| is)\s+(?:a|the)\s+summary[:\-\s]*|summary[:\-\s]*)",
        "",
        text,
        flags=re.IGNORECASE,
    )
    return re.sub(r"\s+", " ", text).strip()


async def synthesize_with_gemini(
    query: str,
    synthesis_inputs: List[Dict[str, Any]],
    *,
    api_key: str,
    model: str = "gemini-2.5-flash",
    timeout_seconds: float = 4.5,
) -> Optional[Dict[str, Any]]:
    """Generate a concise cited summary grounded strictly in retrieved sources via Gemini REST."""
    clean_key = (api_key or "").strip()
    if not clean_key or not query.strip() or not synthesis_inputs:
        return None

    source_rows: List[Dict[str, Any]] = []
    context_blocks: List[str] = []
    for doc in synthesis_inputs[:5]:
        url = str(doc.get("url") or "").strip()
        title = str(doc.get("title") or "").strip()
        body = str(
            doc.get("full_text")
            or doc.get("_full_text")
            or doc.get("raw_snippet")
            or doc.get("snippet")
            or ""
        ).strip()
        excerpt = _sanitize_prose(body)[:1200]
        if not url or not excerpt:
            continue
        source_rows.append(doc)
        context_blocks.append(f"[{len(source_rows)}] {title} ({url})\n{excerpt}")

    if not context_blocks:
        return None

    prompt = (
        "Answer the user query concisely in 2 to 4 plain factual sentences using ONLY the sources below.\n"
        "Cite supporting facts inline with [1], [2], etc. matching the numbered sources.\n"
        "Do not invent facts, do not use bullet points or markdown, and do not add intro phrases.\n\n"
        f"Query: {query.strip()}\n\n"
        "Sources:\n" + "\n\n".join(context_blocks)
    )
    endpoint = _GEMINI_ENDPOINT_TMPL.format(model=(model or "gemini-2.5-flash").strip())
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.15, "maxOutputTokens": 260},
    }

    try:
        import httpx

        async with httpx.AsyncClient(timeout=timeout_seconds) as client:
            resp = await client.post(
                endpoint,
                headers={"x-goog-api-key": clean_key, "Content-Type": "application/json"},
                json=payload,
            )
            if resp.status_code != 200:
                return None
            data = resp.json()
    except Exception:
        return None

    candidates = data.get("candidates") if isinstance(data, dict) else None
    if not candidates or not isinstance(candidates, list):
        return None
    parts = ((candidates[0] or {}).get("content") or {}).get("parts") or []
    raw_answer = " ".join(str(p.get("text") or "") for p in parts if isinstance(p, dict))
    summary = _clean_gemini_summary(raw_answer)
    if len(summary) < 25:
        return None

    all_citations = [
        {
            "index": idx,
            "url": str(doc.get("url") or ""),
            "url_hash": str(doc.get("url_hash") or ""),
            "title": str(doc.get("title") or extract_domain_host(str(doc.get("url") or ""))),
            "domain": extract_domain_host(str(doc.get("url") or "")),
        }
        for idx, doc in enumerate(source_rows, start=1)
        if doc.get("url")
    ]
    referenced = {int(m) for m in re.findall(r"\[(\d+)\]", summary)}
    citations = [c for c in all_citations if c["index"] in referenced] or all_citations[:3]

    return {
        "summary": summary,
        "citations": citations,
        "mode": "gemini_grounded",
    }


def sort_hits_by_relevance(
    clean_query: str, hits: List[Dict[str, Any]], *, mode: str = "all"
) -> List[Dict[str, Any]]:
    """Sort search hits descending by matched term count, relevance boost, then OPIC/BM25 score."""

    def _rank_key(h: Dict[str, Any]) -> Tuple[int, float, float]:
        matched, rel_score = score_document_relevance(
            clean_query,
            h.get("title", ""),
            h.get("snippet", ""),
            h.get("url", ""),
            mode=mode,
        )
        return (matched, rel_score, float(h.get("score") or 0.0))

    return sorted(hits, key=_rank_key, reverse=True)


async def attach_synthesis_and_excerpts(
    query: str,
    docs: List[Dict[str, Any]],
    *,
    include_markdown: bool = False,
    max_sources: int = 5,
    get_payloads_map: Optional[Callable[[List[int]], Awaitable[Dict[int, bytes]]]] = None,
    decompress_fn: Optional[Callable[[bytes], Optional[str]]] = None,
    gemini_api_key: str = "",
    gemini_model: str = "gemini-2.5-flash",
    gemini_timeout_seconds: float = 4.5,
) -> Tuple[List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """Hydrate top docs from payload storage if needed, synthesize answer, and format snippets."""
    top_docs = docs[:max_sources]
    missing_hashes: List[int] = []
    for doc in top_docs:
        if not doc.get("_full_text"):
            raw_hash = doc.get("url_hash")
            try:
                if raw_hash is not None and str(raw_hash).strip():
                    missing_hashes.append(int(raw_hash))
            except (TypeError, ValueError):
                continue

    payloads_map: Dict[int, bytes] = {}
    if missing_hashes and get_payloads_map is not None:
        payloads_map = await get_payloads_map(missing_hashes)

    synthesis_inputs: List[Dict[str, Any]] = []
    for doc in top_docs:
        full_txt = str(doc.get("_full_text") or "")
        if not full_txt and decompress_fn is not None:
            try:
                raw_bytes = payloads_map.get(int(doc.get("url_hash", 0)))
                if raw_bytes:
                    full_txt = decompress_fn(raw_bytes) or ""
            except (TypeError, ValueError):
                full_txt = ""
        synthesis_inputs.append(
            {
                "url_hash": str(doc.get("url_hash") or ""),
                "url": doc.get("url") or "",
                "title": doc.get("title") or "",
                "raw_snippet": doc.get("snippet") or "",
                "full_text": full_txt,
            }
        )

    answer = None
    if (gemini_api_key or "").strip():
        answer = await synthesize_with_gemini(
            query,
            synthesis_inputs,
            api_key=gemini_api_key,
            model=gemini_model,
            timeout_seconds=gemini_timeout_seconds,
        )
    if answer is None:
        answer = synthesize_grounded_answer(query, synthesis_inputs, max_sentences=4)

    formatted_docs: List[Dict[str, Any]] = []
    payload_lookup = {s["url"]: s["full_text"] for s in synthesis_inputs}
    for doc in docs:
        clean_doc = {k: v for k, v in doc.items() if k != "_full_text"}
        raw_snip = str(clean_doc.get("snippet") or "")
        body_for_excerpt = str(
            doc.get("_full_text")
            or payload_lookup.get(clean_doc.get("url", ""), "")
            or raw_snip
        )
        clean_doc["snippet"] = (
            extract_query_focused_snippet(query, body_for_excerpt, max_len=320)
            or _sanitize_prose(raw_snip)[:320]
        )
        if include_markdown:
            clean_doc["full_markdown"] = body_for_excerpt
        formatted_docs.append(clean_doc)

    return formatted_docs, answer
