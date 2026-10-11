"""Outbound HTTP session that is safe inside forked gunicorn workers on macOS.

By default `requests` resolves proxies with urllib.request.getproxies(), which on macOS
falls through to the system proxy lookup (_scproxy -> SystemConfiguration/CoreFoundation).
That call is not fork-safe: in a gunicorn worker macOS aborts the process
("crashed on child side of fork pre-exec"), so the client sees an empty response.

This session ignores the platform lookup (trust_env=False) but still honors the standard
HTTP(S)_PROXY / NO_PROXY environment variables, which are plain env reads.
"""

import urllib.request

import requests


def session() -> requests.Session:
    s = requests.Session()
    s.trust_env = False
    s.proxies = urllib.request.getproxies_environment()
    return s


def get(url: str, **kwargs) -> requests.Response:
    with session() as s:
        return s.get(url, **kwargs)


def post(url: str, **kwargs) -> requests.Response:
    with session() as s:
        return s.post(url, **kwargs)
