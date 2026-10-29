"""Network security validation and SSRF prevention for AIRA tools."""

import socket
import ipaddress
from urllib.parse import urlparse
from typing import Tuple

BLOCKED_IP_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),      # Loopback
    ipaddress.ip_network("10.0.0.0/8"),       # RFC1918 Private
    ipaddress.ip_network("172.16.0.0/12"),    # RFC1918 Private
    ipaddress.ip_network("192.168.0.0/16"),   # RFC1918 Private
    ipaddress.ip_network("169.254.0.0/16"),   # Link-Local / Cloud Metadata
    ipaddress.ip_network("0.0.0.0/8"),        # Current network
    ipaddress.ip_network("100.64.0.0/10"),    # Carrier-grade NAT
    ipaddress.ip_network("192.0.0.0/24"),     # IETF Protocol Assignments
    ipaddress.ip_network("192.0.2.0/24"),     # TEST-NET-1
    ipaddress.ip_network("198.51.100.0/24"),  # TEST-NET-2
    ipaddress.ip_network("203.0.113.0/24"),   # TEST-NET-3
    ipaddress.ip_network("224.0.0.0/4"),      # Multicast
    ipaddress.ip_network("240.0.0.0/4"),      # Reserved
    # IPv6
    ipaddress.ip_network("::1/128"),          # Loopback
    ipaddress.ip_network("fc00::/7"),         # Unique local
    ipaddress.ip_network("fe80::/10"),        # Link-local
    ipaddress.ip_network("ff00::/8"),         # Multicast
]

def validate_url_security(url: str) -> Tuple[bool, str]:
    """Validates that a URL uses safe protocols and does not resolve to

    prohibited internal addresses or cloud metadata endpoints (SSRF prevention).
    Returns (is_safe, error_message).
    """
    try:
        parsed = urlparse(url)
        if parsed.scheme.lower() not in ("http", "https"):
            return False, f"Unsupported URL scheme '{parsed.scheme}'. Only http and https are permitted."

        hostname = parsed.hostname
        if not hostname:
            return False, "URL does not contain a valid hostname."

        # Block localhost variants explicitly
        if hostname.lower() in ("localhost", "127.0.0.1", "::1", "metadata.google.internal"):
            return False, f"Access to '{hostname}' is prohibited by safety policy."

        # Resolve IP addresses for the hostname
        try:
            addr_info = socket.getaddrinfo(hostname, None)
        except socket.gaierror as e:
            return False, f"DNS resolution failed for '{hostname}': {e}"

        resolved_ips = {item[4][0] for item in addr_info}
        for ip_str in resolved_ips:
            ip_obj = ipaddress.ip_address(ip_str)
            for blocked_net in BLOCKED_IP_NETWORKS:
                if ip_obj in blocked_net:
                    return False, f"URL resolves to prohibited internal/private address {ip_str}."

        return True, ""
    except Exception as e:
        return False, f"URL validation error: {str(e)}"
