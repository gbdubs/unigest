import hashlib
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode


def content_hash(data: bytes) -> str:
    """SHA-256 hex digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def url_hash(url: str) -> str:
    """Normalize URL then SHA-256."""
    parsed = urlparse(url)
    # Normalize: lowercase scheme and host, sort query params, strip fragment
    normalized = urlunparse((
        parsed.scheme.lower(),
        parsed.netloc.lower(),
        parsed.path.rstrip("/") or "/",
        parsed.params,
        urlencode(sorted(parse_qs(parsed.query, keep_blank_values=True).items()), doseq=True),
        "",  # strip fragment
    ))
    return hashlib.sha256(normalized.encode()).hexdigest()
