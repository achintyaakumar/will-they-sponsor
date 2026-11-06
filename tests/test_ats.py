from datetime import date

from vjb import ats
from vjb.discover import slugs
from vjb.llm import parse_result
from vjb.roles import is_us


def test_norm_smartrecruiters():
    j = {
        "id": "744000159991510", "name": " Software Engineer ", "releasedDate": "2026-11-05T23:49:49.338Z",
        "location": {"city": "Mountain View", "region": "California", "country": "us", "remote": False,
                     "fullLocation": "Mountain View, California, United States"},
        "department": {"label": "Engineering"},
        "postingUrl": "https://jobs.smartrecruiters.com/ServiceNow/744000159991510-software-engineer",
        "jobAd": {"sections": {
            "jobDescription": {"title": "Job Description", "text": "<p>Build things.</p>"},
            "additionalInformation": {"title": "Additional Information", "text": "<p>We are unable to sponsor visas for this role.</p>"},
        }},
    }
    p = ats._norm_sr("ServiceNow", "servicenow", j)
    assert p["title"] == "Software Engineer"
    assert p["job_id"] == "744000159991510"
    assert p["location"] == "Mountain View, California, United States"
    assert is_us(p["locations"], p["countries"])
    assert "Additional Information:\nWe are unable to sponsor visas" in p["text"]
    assert p["published"].startswith("2026-11-05")


def test_norm_workable():
    j = {"title": "ML Engineer", "shortcode": "81B46579FE", "telecommuting": True, "department": "Open Source",
         "url": "https://apply.workable.com/j/81B46579FE", "published_on": "2026-05-29",
         "locations": [{"country": "United States", "countryCode": "US", "city": "New York", "region": "New York", "hidden": False}],
         "description": "<p>You must be authorized to work in the US.</p>"}
    p = ats._norm_workable("Hugging Face", "huggingface", j)
    assert p["location"] == "Remote - New York, New York, United States"
    assert p["countries"] == ["US"]
    assert is_us(p["locations"], p["countries"])
    assert "authorized to work" in p["text"]


def test_norm_recruitee():
    j = {"id": 2804401, "title": "Backend Engineer", "careers_url": "https://x.recruitee.com/o/backend",
         "published_at": "2026-10-30 16:32:58 UTC", "department": "Tech", "remote": False, "country_code": "US",
         "locations": [{"name": "Austin", "city": "Austin", "state": "Texas", "country": "United States", "country_code": "US"}],
         "salary": {"min": "120000", "max": "150000", "period": "year", "currency": "USD"},
         "description": "<p>About us</p>", "requirements": "<ul><li>Visa sponsorship is available.</li></ul>"}
    p = ats._norm_recruitee("Acme", "acme", j)
    assert p["location"] == "Austin, Texas, United States"
    assert p["salary"] == "USD 120000-150000 year"
    assert "Requirements:\nVisa sponsorship is available." in p["text"]


def test_name_ok():
    assert ats.name_ok("Hugging Face", "Hugging Face")
    assert ats.name_ok("WESTERN DIGITAL TECHNOLOGIES", "Western Digital")
    assert ats.name_ok("ServiceNow", "Service Now")
    assert ats.name_ok("Kraken", "Kraken Digital Asset Exchange")
    assert not ats.name_ok("Box", "Boxed Inc")
    assert not ats.name_ok("Atlassian", "AT")
    assert not ats.name_ok("Atlassian", None)
    assert ats.name_ok("INTUITIVE SURGICAL OPERATIONS", "Intuitive")
    assert ats.name_ok("HP", "HP")
    assert not ats.name_ok("SYSTEM SOFT TECHNOLOGIES", "System")


def test_slugs():
    assert slugs("SERVICENOW") == ["servicenow"]
    assert slugs("WESTERN DIGITAL TECHNOLOGIES") == ["westerndigital", "western", "western-digital"]
    assert slugs("DATA SYSTEMS") == ["datasystems", "data-systems"]


def _stub(monkeypatch, boards):
    """boards: {(ats, token): raw}. Records which (ats, token) pairs were requested."""
    calls = []

    def fetch_board(a, token, cache_dir, name=None, strict=False):
        calls.append((a, token))
        return boards.get((a, token))

    monkeypatch.setattr(ats, "fetch_board", fetch_board)
    monkeypatch.setattr(ats, "normalize", lambda a, c, t, raw: [{"company": c, "ats": a}] * len(raw))
    return calls


TODAY = date(2026, 11, 5)


def test_refresh_known_board_is_fetched_directly(monkeypatch):
    calls = _stub(monkeypatch, {("lever", "acme"): [{}, {}]})
    prev = {"company": "Acme", "tokens": ["acme"], "ats": "lever", "token": "acme", "checked": "2026-11-04"}
    board, posts = ats.refresh("Acme", ["acme"], prev, None, TODAY)
    assert calls == [("lever", "acme")]
    assert len(posts) == 2 and board["last_hit"] == "2026-11-05" and board["fails"] == 0


def test_refresh_survives_a_blip_then_reprobes(monkeypatch):
    calls = _stub(monkeypatch, {("ashby", "acme"): [{}]})
    prev = {"company": "Acme", "tokens": ["acme"], "ats": "lever", "token": "acme", "fails": 0}
    board, posts = ats.refresh("Acme", ["acme"], prev, None, TODAY)
    assert posts == [] and board["ats"] == "lever" and board["fails"] == 1
    board, posts = ats.refresh("Acme", ["acme"], {**prev, "fails": ats.MAX_FAILS - 1}, None, TODAY)
    assert board["ats"] == "ashby" and len(posts) == 1  # moved boards


def test_refresh_miss_probes_only_new_ats(monkeypatch):
    calls = _stub(monkeypatch, {})
    probed = ["greenhouse", "ashby", "lever"]
    prev = {"company": "Acme", "tokens": ["acme"], "ats": None, "checked": "2026-11-04", "probed": probed}
    board, _ = ats.refresh("Acme", ["acme"], prev, None, TODAY)
    assert {a for a, _ in calls} == {"smartrecruiters", "workable", "recruitee"}
    assert set(board["probed"]) == set(ats.ATS) and board["checked"] == "2026-11-04"
    calls.clear()
    ats.refresh("Acme", ["acme"], board, None, TODAY)
    assert calls == []  # nothing due until a week has passed
    ats.refresh("Acme", ["acme"], board, None, date(2026, 11, 12))
    assert {a for a, _ in calls} == set(ats.ATS)


def test_refresh_new_tokens_reprobe(monkeypatch):
    calls = _stub(monkeypatch, {("greenhouse", "acmeinc"): [{}]})
    prev = {"company": "Acme", "tokens": ["acme"], "ats": None, "checked": "2026-11-05", "probed": list(ats.ATS)}
    board, posts = ats.refresh("Acme", ["acmeinc"], prev, None, TODAY)
    assert board["token"] == "acmeinc" and len(posts) == 1


def test_parse_result():
    reply = 'Here you go:\n[{"id": 2, "stance": "sponsors"}, {"id": 1, "stance": "none"}]'
    assert [r["stance"] for r in parse_result(reply, 2)] == ["none", "sponsors"]
    assert parse_result(reply, 3)[2] is None
    assert parse_result("no json here", 1) is None


def test_probe_skips_rate_limited_ats(monkeypatch):
    def fetch_board(a, token, cache_dir, name=None, strict=False):
        if a == "workable":
            raise ats.RateLimited("apply.workable.com")
        return None

    monkeypatch.setattr(ats, "fetch_board", fetch_board)
    prev = {"company": "Acme", "tokens": ["acme"], "ats": None, "checked": "2026-11-04", "probed": ["greenhouse", "ashby", "lever"]}
    board, _ = ats.refresh("Acme", ["acme"], prev, None, TODAY)
    assert "workable" not in board["probed"] and "smartrecruiters" in board["probed"]


def test_probe_pinned_token(monkeypatch):
    calls = _stub(monkeypatch, {("smartrecruiters", "servicenow"): [{}]})
    ats_, token, raw, _ = ats.probe("ServiceNow", ["smartrecruiters:servicenow"], None)
    assert (ats_, token) == ("smartrecruiters", "servicenow") and calls == [("smartrecruiters", "servicenow")]
