from __future__ import annotations

import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

_NON_ALNUM_PATTERN = re.compile(r"[^a-z0-9]+")
_TRACKING_QUERY_PREFIXES = ("utm_",)
_TRACKING_QUERY_KEYS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "ref_src",
}


def normalize_fingerprint_part(value: str) -> str:
    collapsed = _NON_ALNUM_PATTERN.sub(" ", value.casefold())
    return " ".join(collapsed.split())


def canonicalize_source_url(url: str) -> str:
    split = urlsplit(url.strip())
    scheme = split.scheme.casefold() or "https"
    hostname = split.hostname.casefold() if split.hostname else ""
    port = split.port
    include_port = port is not None and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    )
    netloc = f"{hostname}:{port}" if include_port else hostname
    path = split.path or "/"
    if path != "/":
        path = path.rstrip("/")

    filtered_query = [
        (key, value)
        for key, value in parse_qsl(split.query, keep_blank_values=True)
        if key.casefold() not in _TRACKING_QUERY_KEYS
        and not any(key.casefold().startswith(prefix) for prefix in _TRACKING_QUERY_PREFIXES)
    ]
    query = urlencode(sorted(filtered_query))

    return urlunsplit((scheme, netloc, path, query, ""))


def arena_fingerprint(domain: str, icp_user_role: str) -> str:
    normalized_domain = normalize_fingerprint_part(domain)
    normalized_role = normalize_fingerprint_part(icp_user_role)
    return f"{normalized_domain}::{normalized_role}"
