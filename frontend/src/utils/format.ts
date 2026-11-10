const STOP_WORDS = new Set([
  'a', 'an', 'and', 'are', 'as', 'at', 'be', 'been', 'being', 'by', 'can',
  'did', 'do', 'does', 'for', 'from', 'get', 'had', 'has', 'have', 'how',
  'in', 'into', 'is', 'it', 'its', 'make', 'me', 'my', 'of', 'on', 'or',
  'safe', 'should', 'so', 'some', 'that', 'the', 'their', 'them', 'then',
  'there', 'these', 'they', 'this', 'those', 'to', 'was', 'we', 'what',
  'when', 'where', 'which', 'who', 'why', 'will', 'with', 'would', 'you', 'your',
]);

// Keep "safe" highlightable if user explicitly searches for safety, only omit pure grammar stop words
STOP_WORDS.delete('safe');
STOP_WORDS.delete('make');

export function safeHttpUrl(rawUrl: string): string {
  try {
    const parsed = new URL(rawUrl);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:'
      ? parsed.href
      : '#';
  } catch {
    return '#';
  }
}

export function extractDomainAndPath(rawUrl: string): { domain: string; path: string } {
  try {
    const parsed = new URL(rawUrl);
    const domain = parsed.hostname.replace(/^www\./, '');
    const cleanPath = parsed.pathname === '/' ? '' : parsed.pathname;
    const truncatedPath =
      cleanPath.length > 36 ? `${cleanPath.slice(0, 34)}...` : cleanPath;
    return { domain, path: truncatedPath };
  } catch {
    return { domain: 'web', path: '' };
  }
}

export function formatRelativeTime(timestampStr?: string | null): string {
  if (!timestampStr) return 'Indexed';
  const normalized = timestampStr.includes('T')
    ? timestampStr
    : `${timestampStr.replace(' ', 'T')}${timestampStr.length > 10 ? 'Z' : 'T00:00:00Z'}`;
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) return timestampStr;
  const diffSec = Math.max(0, Math.floor((Date.now() - date.getTime()) / 1000));
  if (diffSec < 60) return 'Just now';
  const mins = Math.floor(diffSec / 60);
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  const days = Math.floor(hrs / 24);
  return `${days}d ago`;
}

export function extractHighlightTerms(query: string): string[] {
  const tokens = (query || '')
    .toLowerCase()
    .split(/\s+/)
    .map((t) => t.replace(/[^a-z0-9]/g, ''))
    .filter((t) => t.length > 2 && !STOP_WORDS.has(t));
  return Array.from(new Set(tokens)).slice(0, 6);
}

export function escapeRegex(str: string): string {
  return str.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
