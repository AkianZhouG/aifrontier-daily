from frontier_daily.content import canonicalize_url
from frontier_daily.dedup import content_fingerprint


def test_canonical_url_removes_tracking_and_fragment():
    assert canonicalize_url("HTTPS://Example.COM/path/?utm_source=x&b=2&a=1#part") == (
        "https://example.com/path?a=1&b=2"
    )


def test_content_fingerprint_ignores_case_and_whitespace():
    first = content_fingerprint("Title", "Hello   WORLD")
    second = content_fingerprint("Other", " hello world ")
    assert first == second
