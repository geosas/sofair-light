"""
Input resolver for OGC API Processes.

Handles resolution of inputs provided by reference (href) as specified in:
- OGC API Processes 1.0, Requirement /req/core/process-execute-inputs-B

When an input value contains an "href" field, the content is fetched from
that URL and used as the actual input value.

SSRF hardening (see SECURITY_AUDIT.md #1): before every fetch the target URL is
validated (``_assert_safe_url``): the scheme must be http/https, an optional host
allowlist is enforced, and *every* address the host resolves to (A **and** AAAA
records, via :func:`socket.getaddrinfo`) must be public. Redirects are not
followed automatically - each hop is re-validated so a public URL cannot bounce
us to an internal target.
"""
import ipaddress
import json
import socket
from typing import Any, Optional
from urllib.parse import urljoin, urlparse

import requests

# Max redirect hops we will follow manually (each one re-validated).
MAX_REDIRECTS = 5

# Default connect/read timeout for reference fetches (SECURITY_AUDIT.md #1/#4).
DEFAULT_TIMEOUT = (5, 10)

# Default cap on a single fetched reference body (SECURITY_AUDIT.md #2).
DEFAULT_MAX_REF_BYTES = 10 * 1024 * 1024  # 10 MiB

# Streaming read chunk size.
_CHUNK = 65536


class InputResolutionError(Exception):
    """Exception raised when an input reference cannot be resolved."""

    def __init__(self, input_name: str, href: str, reason: str):
        self.input_name = input_name
        self.href = href
        self.reason = reason
        super().__init__(f"Failed to resolve input '{input_name}' from '{href}': {reason}")


def _is_blocked_ip(ip_str: str) -> bool:
    """Return True if ``ip_str`` is a non-public address we must never fetch.

    Handles IPv4 and IPv6, including IPv4-mapped IPv6 (e.g. ``::ffff:169.254.169.254``),
    which is normalized to its IPv4 form before the checks - otherwise a mapped
    internal address would slip through.
    """
    ip = ipaddress.ip_address(ip_str)
    if ip.version == 6 and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _assert_safe_url(input_name: str, href: str, allowed_hosts: Optional[set] = None) -> None:
    """Validate a URL against SSRF before it is fetched.

    ``allowed_hosts`` semantics:
      * ``None``       -> no allowlist; any *public* host is fetchable.
      * non-empty set  -> only these hosts are fetchable.
      * **empty set**  -> inputs-by-reference are **disabled entirely** (every href rejected).

    Raises :class:`InputResolutionError` if references are disabled, the scheme is
    not http/https, the host is not allowlisted, or *any* address the host resolves
    to (IPv4 or IPv6) is non-public.

    Note: there is a residual DNS TOCTOU window (the OS re-resolves the name when
    the connection is actually opened). A configured host allowlist is the strong
    control against that; the IP check is defence-in-depth.
    """
    # Empty (but non-None) allowlist => the feature is turned off; reject any href
    # up front, before any DNS/network work.
    if allowed_hosts is not None and len(allowed_hosts) == 0:
        raise InputResolutionError(input_name, href, "inputs by reference are disabled")

    parsed = urlparse(href)
    if parsed.scheme not in ("http", "https"):
        raise InputResolutionError(input_name, href, "URL scheme not allowed (only http/https)")

    host = parsed.hostname
    if not host:
        raise InputResolutionError(input_name, href, "URL has no host")

    if allowed_hosts is not None and host.lower() not in allowed_hosts:
        raise InputResolutionError(input_name, href, "host not in allowlist")

    try:
        infos = socket.getaddrinfo(host, parsed.port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise InputResolutionError(input_name, href, "DNS resolution failed")

    for info in infos:
        ip_str = info[4][0]
        if _is_blocked_ip(ip_str):
            raise InputResolutionError(input_name, href, "host resolves to a non-public address")


def _normalize_allowed_hosts(allowed_hosts) -> Optional[set]:
    """Normalize a configured allowlist (list/tuple/set/None) to a lowercased set."""
    if allowed_hosts is None:
        return None
    return {h.lower() for h in allowed_hosts}


def is_input_by_reference(value: Any) -> bool:
    """
    Check if an input value is provided by reference.

    According to OGC standard, an input by reference is an object with an "href" field.

    Args:
        value: The input value to check

    Returns:
        True if the value is an input by reference, False otherwise
    """
    if not isinstance(value, dict):
        return False
    return "href" in value and isinstance(value["href"], str)


def _read_capped(input_name: str, href: str, response, max_bytes: int) -> bytes:
    """Stream a response body, aborting as soon as it exceeds ``max_bytes``.

    This never holds more than ``max_bytes`` (+ one chunk) in memory, so a huge
    ``href`` target cannot OOM the server (SECURITY_AUDIT.md #2).
    """
    chunks, total = [], 0
    for chunk in response.iter_content(_CHUNK):
        if not chunk:
            continue
        total += len(chunk)
        if total > max_bytes:
            response.close()
            raise InputResolutionError(input_name, href, "response too large")
        chunks.append(chunk)
    return b"".join(chunks)


def _fetch_validated(input_name: str, href: str, timeout, allowed_hosts: Optional[set],
                     max_bytes: int):
    """Fetch ``href`` with SSRF validation, following redirects manually.

    ``allow_redirects=False`` so we control every hop: each redirect target is
    re-validated with :func:`_assert_safe_url` before we follow it, closing the
    "public URL 302-redirects to an internal address" bypass. The final body is
    read with a hard size cap via :func:`_read_capped`.

    Returns ``(response, body_bytes)``.
    """
    current = href
    for _ in range(MAX_REDIRECTS + 1):
        _assert_safe_url(input_name, current, allowed_hosts)
        response = requests.get(current, timeout=timeout, allow_redirects=False, stream=True)
        if 300 <= response.status_code < 400 and "Location" in response.headers:
            location = response.headers["Location"]
            response.close()
            current = urljoin(current, location)
            continue
        try:
            response.raise_for_status()
            body = _read_capped(input_name, href, response, max_bytes)
        finally:
            response.close()
        return response, body
    raise InputResolutionError(input_name, href, "too many redirects")


def fetch_input_by_reference(input_name: str, reference: dict, timeout=DEFAULT_TIMEOUT,
                             allowed_hosts: Optional[set] = None,
                             max_bytes: int = DEFAULT_MAX_REF_BYTES) -> Any:
    """
    Fetch input data from a URL reference.

    Args:
        input_name: Name of the input (for error messages)
        reference: Dictionary containing at least "href", optionally "type"
        timeout: Request timeout - ``(connect, read)`` tuple or a single float
        allowed_hosts: Optional set of lowercased hostnames; when provided, only
            these hosts may be fetched (SSRF allowlist)
        max_bytes: Hard cap on the fetched body size

    Returns:
        The fetched and parsed content

    Raises:
        InputResolutionError: If the content cannot be fetched or parsed
    """
    href = reference.get("href")
    content_type_hint = reference.get("type")

    if not href:
        raise InputResolutionError(input_name, "", "Missing 'href' field")

    try:
        response, body = _fetch_validated(input_name, href, timeout, allowed_hosts, max_bytes)
    except requests.exceptions.Timeout:
        raise InputResolutionError(input_name, href, "Request timed out")
    except requests.exceptions.ConnectionError:
        raise InputResolutionError(input_name, href, "Connection error")
    except requests.exceptions.HTTPError as e:
        raise InputResolutionError(input_name, href, f"HTTP error: {e.response.status_code}")
    except requests.exceptions.RequestException as e:
        raise InputResolutionError(input_name, href, str(e))

    # Determine content type from response or hint
    content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
    if not content_type and content_type_hint:
        content_type = content_type_hint
    encoding = response.encoding or "utf-8"

    # Parse based on content type
    try:
        if content_type in ("application/json", "application/geo+json"):
            return json.loads(body)
        elif content_type.startswith("text/"):
            return body.decode(encoding, errors="replace")
        else:
            # Try JSON first, fall back to text
            try:
                return json.loads(body)
            except ValueError:
                return body.decode(encoding, errors="replace")
    except ValueError as e:
        raise InputResolutionError(input_name, href, f"Failed to parse response: {e}")


def resolve_inputs(inputs: dict, timeout=DEFAULT_TIMEOUT, allowed_hosts=None,
                   max_bytes: int = DEFAULT_MAX_REF_BYTES,
                   max_references: Optional[int] = None) -> dict:
    """
    Resolve all inputs, fetching any that are provided by reference.

    This function iterates through all input values and replaces any
    input by reference (containing "href") with the fetched content.

    Args:
        inputs: Dictionary of input name -> value
        timeout: Request timeout - ``(connect, read)`` tuple or a single float
        allowed_hosts: Optional iterable of allowed hostnames (SSRF allowlist);
            ``None`` disables the allowlist (IP-based blocking still applies)
        max_bytes: Hard cap on each fetched reference body (SECURITY_AUDIT.md #2)
        max_references: Max number of ``href`` inputs allowed in one request;
            ``None`` means unlimited (SECURITY_AUDIT.md #4)

    Returns:
        Dictionary with all references resolved to their actual values

    Raises:
        InputResolutionError: If any reference cannot be resolved, or if there are
            more references than ``max_references``
    """
    normalized_hosts = _normalize_allowed_hosts(allowed_hosts)

    if max_references is not None:
        ref_count = sum(1 for v in inputs.values() if is_input_by_reference(v))
        if ref_count > max_references:
            raise InputResolutionError(
                "(request)", "",
                f"too many inputs by reference: {ref_count} > {max_references}")

    resolved = {}
    for name, value in inputs.items():
        if is_input_by_reference(value):
            resolved[name] = fetch_input_by_reference(
                name, value, timeout, normalized_hosts, max_bytes)
        else:
            resolved[name] = value

    return resolved
