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
