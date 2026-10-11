"""Regression: outbound HTTP must not trigger the macOS system proxy lookup (crashes forked gunicorn workers)."""

import urllib.request

from app.utils import http


def test_session_skips_platform_proxy_lookup(monkeypatch):
    def boom():  # stands in for the macOS _scproxy lookup that aborts in a forked child
        raise AssertionError("system proxy lookup must not be called")

    monkeypatch.setattr(urllib.request, "getproxies", boom)
    monkeypatch.setattr(urllib.request, "getproxies_macosx_sysconf", boom, raising=False)
    monkeypatch.setenv("HTTPS_PROXY", "http://proxy.example:3128")
    s = http.session()
    assert s.trust_env is False
    assert s.proxies.get("https") == "http://proxy.example:3128"  # env proxies still honored
    # Building a request must not consult the platform proxy settings.
    prepared = s.prepare_request(__import__("requests").Request("GET", "http://127.0.0.1:8300/health"))
    s.merge_environment_settings(prepared.url, {}, None, None, None)
