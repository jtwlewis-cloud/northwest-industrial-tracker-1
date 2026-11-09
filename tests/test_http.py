from nwtracker.http import Robots

JLL_STYLE = """
User-agent: Googlebot
Allow: */static/

User-agent: *
Disallow: */brochure
Disallow: */search
Disallow: /*?
Disallow: /en-gb/
"""


def test_robots_wildcards():
    r = Robots(JLL_STYLE)
    assert r.allowed("https://x.co.uk/rent-industrial-and-logistics/foo-wa5-0nd-197184")
    assert not r.allowed("https://x.co.uk/search")
    assert not r.allowed("https://x.co.uk/en/search?x=1")
    assert not r.allowed("https://x.co.uk/listing?ref=2")
    assert not r.allowed("https://x.co.uk/en-gb/page")
    assert r.allowed("https://x.co.uk/sitemap-properties.xml")


def test_robots_empty_allows_all():
    assert Robots(None).allowed("https://x/anything?y=1")
    assert Robots("User-agent: *\nDisallow:\n").allowed("https://x/a")


def test_robots_allow_beats_shorter_disallow():
    r = Robots("User-agent: *\nDisallow: /wp-admin/\nAllow: /wp-admin/admin-ajax.php\n")
    assert r.allowed("https://x/wp-admin/admin-ajax.php")
    assert not r.allowed("https://x/wp-admin/options.php")


def test_proxy_refusal_marks_host_dead(monkeypatch):
    import pytest
    import requests
    from nwtracker.http import AccessBlocked, Fetcher
    f = Fetcher(delay=0, respect_robots=False)
    calls = []

    def boom(*a, **k):
        calls.append(1)
        raise requests.exceptions.ProxyError("403 Forbidden")

    monkeypatch.setattr(f.session, "request", boom)
    with pytest.raises(AccessBlocked):
        f.get("https://blocked.example/a.pdf")
    with pytest.raises(AccessBlocked):
        f.get("https://blocked.example/b.pdf")
    assert len(calls) == 1  # second request short-circuits
