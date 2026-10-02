import pytest

from vibeloader.urls import find_url_in_text, is_http_url, looks_like_supported_url


@pytest.mark.parametrize(
    "url, known",
    [
        ("https://www.youtube.com/watch?v=abc", True),
        ("https://youtu.be/abc", True),
        ("https://vm.tiktok.com/xyz/", True),
        ("https://x.com/user/status/1", True),
        ("https://www.netflix.com/title/1", False),  # antes pasaba por contener "x.com"
        ("https://www.dropbox.com/s/a", False),
        ("https://example.com/?u=youtube.com", False),  # el host manda, no la query
        ("ftp://youtube.com/a", False),
        ("youtube.com/watch?v=abc", False),
    ],
)
def test_looks_like_supported_url(url, known):
    assert looks_like_supported_url(url) is known


@pytest.mark.parametrize(
    "url, ok",
    [
        ("https://www.ted.com/talks/x", True),  # sitio no listado: se acepta igual
        ("http://archive.org/details/x", True),
        ("https://localhost/x", False),
        ("hola mundo", False),
        ("", False),
    ],
)
def test_is_http_url(url, ok):
    assert is_http_url(url) is ok


@pytest.mark.parametrize(
    "text, expected",
    [
        ("mira esto: https://youtu.be/abc.", "https://youtu.be/abc"),
        ("(https://youtu.be/abc)", "https://youtu.be/abc"),
        ("«https://youtu.be/abc»", "https://youtu.be/abc"),
        ("https://en.wikipedia.org/wiki/Foo_(bar)", "https://en.wikipedia.org/wiki/Foo_(bar)"),
        ('<a href="https://youtu.be/abc">', "https://youtu.be/abc"),
        ("sin enlaces", None),
    ],
)
def test_find_url_in_text(text, expected):
    assert find_url_in_text(text) == expected
