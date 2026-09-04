"""Deterministic URL normalization utilities."""

from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode

# Standard tracking and analytics parameters to safely discard
TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "fbclid",
    "gclid",
    "gclsrc",
    "igshid",
    "msclkid",
    "twclid",
    "ref",
    "ref_src",
    "source",
    "ocid",
    "ncid",
}

def normalize_url(raw_url: str) -> str:
    """
    Deterministically normalizes a URL:
    - Strips whitespace
    - Lowercases scheme and network location (hostname)
    - Strips default ports (:80, :443)
    - Removes standard tracking query parameters
    - Alphabetically sorts remaining query parameters
    - Removes empty query strings and fragments
    - Standardizes path (removes redundant trailing slashes except for root)
    """
    if not raw_url:
        return ""

    url_str = raw_url.strip()
    parsed = urlparse(url_str)

    scheme = parsed.scheme.lower()
    if not scheme:
        scheme = "https"

    # Hostname & Port
    netloc = parsed.netloc.lower()
    if netloc.endswith(":80") and scheme == "http":
        netloc = netloc[:-3]
    elif netloc.endswith(":443") and scheme == "https":
        netloc = netloc[:-4]

    # Path normalization
    path = parsed.path
    if not path:
        path = "/"
    elif len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    # Query params: filter tracking params and sort
    query_items = parse_qsl(parsed.query, keep_blank_values=False)
    filtered_query = [
        (k, v) for k, v in query_items if k.lower() not in TRACKING_PARAMS
    ]
    filtered_query.sort(key=lambda x: (x[0], x[1]))
    normalized_query = urlencode(filtered_query)

    # Reconstruct without fragment
    normalized = urlunparse((scheme, netloc, path, "", normalized_query, ""))
    return normalized

def extract_domain(url: str) -> str:
    """Extracts lowercase domain name from URL."""
    parsed = urlparse(url)
    domain = parsed.netloc.lower()
    if domain.startswith("www."):
        domain = domain[4:]
    # Strip port if present
    if ":" in domain:
        domain = domain.split(":")[0]
    return domain
