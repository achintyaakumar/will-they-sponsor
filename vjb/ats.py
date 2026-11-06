"""Fetch public job boards (Greenhouse, Ashby, Lever, SmartRecruiters, Workable, Recruitee) and normalize postings."""
import html
import json
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import requests
from bs4 import BeautifulSoup

UA = "will-they-sponsor/0.2 (job board research; daily fetch)"
TIMEOUT = 20

_local = threading.local()


def _session() -> requests.Session:
    s = getattr(_local, "s", None)
    if s is None:
        s = requests.Session()
        s.headers["User-Agent"] = UA
        _local.s = s
    return s


class RateLimited(Exception):
    """The host kept answering 429; it is skipped for the rest of this run."""


MIN_GAP = {"apply.workable.com": 2.0}  # seconds between requests to hosts that rate-limit hard
_next_at = {}
_cooling = set()
_host_lock = threading.Lock()


def _throttle(host):
    gap = MIN_GAP.get(host)
    if not gap:
        return
    with _host_lock:
        now = time.monotonic()
        at = max(now, _next_at.get(host, 0.0))
        _next_at[host] = at + gap
    time.sleep(at - now)


def get_json(url: str, retries: int = 3):
    """GET a URL and return parsed JSON, or None on 404. Retries transient failures; raises RateLimited."""
    from urllib.parse import urlparse
    host = urlparse(url).hostname
    for attempt in range(retries):
        if host in _cooling:
            raise RateLimited(host)
        _throttle(host)
        try:
            r = _session().get(url, timeout=TIMEOUT)
        except requests.RequestException:
            time.sleep(1.5 * (attempt + 1))
            continue
        if r.status_code == 404:
            return None
        if r.status_code == 429:
            if attempt == retries - 1:
                with _host_lock:
                    if host not in _cooling:
                        print(f"rate limited by {host}; skipping it for the rest of this run", flush=True)
                    _cooling.add(host)
                raise RateLimited(host)
            try:
                wait = float(r.headers.get("retry-after") or 0)
            except ValueError:
                wait = 0
            time.sleep(min(60, max(wait, 15 * (attempt + 1))))
            continue
        if r.status_code in (500, 502, 503, 504):
            time.sleep(3 * (attempt + 1))
            continue
        if r.status_code != 200:
            return None
        try:
            return r.json()
        except ValueError:
            return None
    return None


def html_to_text(raw: str) -> str:
    if not raw:
        return ""
    soup = BeautifulSoup(raw, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    text = soup.get_text("\n")
    text = re.sub(r"[ \t\xa0]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n", text)
    return text.strip()


# ---------------------------------------------------------------- Greenhouse

def gh_board(token):
    return get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}")


def gh_job_questions(token, job_id):
    return get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs/{job_id}?questions=true")


def _norm_gh(company, token, j):
    content = html_to_text(html.unescape(j.get("content") or ""))
    locs = [(j.get("location") or {}).get("name") or ""]
    for o in j.get("offices") or []:
        if o.get("location"):
            locs.append(o["location"])
    return {
        "company": company,
        "ats": "greenhouse",
        "token": token,
        "job_id": str(j["id"]),
        "title": j.get("title", "").strip(),
        "location": (j.get("location") or {}).get("name") or "",
        "locations": [l for l in locs if l],
        "countries": [],
        "url": j.get("absolute_url"),
        "updated": j.get("updated_at"),
        "published": j.get("first_published"),
        "department": ", ".join(d.get("name", "") for d in j.get("departments") or []),
        "salary": None,
        "text": content,
    }


# ---------------------------------------------------------------- Ashby

def ashby_jobs(token):
    data = get_json(f"https://api.ashbyhq.com/posting-api/job-board/{token}?includeCompensation=true")
    if not data or "jobs" not in data:
        return None
    return data["jobs"]


def _ashby_country(addr):
    return (((addr or {}).get("postalAddress") or {}).get("addressCountry") or "").strip()


def _norm_ashby(company, token, j):
    locs = [j.get("location") or ""]
    countries = [_ashby_country(j.get("address"))]
    for sl in j.get("secondaryLocations") or []:
        locs.append(sl.get("location") or "")
        countries.append(_ashby_country(sl.get("address")))
    comp = j.get("compensation") or {}
    text = j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml") or "")
    return {
        "company": company,
        "ats": "ashby",
        "token": token,
        "job_id": j.get("id"),
        "title": (j.get("title") or "").strip(),
        "location": j.get("location") or "",
        "locations": [l for l in locs if l],
        "countries": [c for c in countries if c],
        "url": j.get("jobUrl"),
        "updated": j.get("publishedAt"),
        "published": j.get("publishedAt"),
        "department": j.get("department") or "",
        "salary": comp.get("compensationTierSummary") or comp.get("scrapeableCompensationSalarySummary"),
        "text": text,
        "remote": j.get("isRemote"),
    }


# ---------------------------------------------------------------- Lever

def lever_jobs(token):
    data = get_json(f"https://api.lever.co/v0/postings/{token}?mode=json")
    if not isinstance(data, list):
        return None
    return data


def _norm_lever(company, token, j):
    cats = j.get("categories") or {}
    parts = [j.get("descriptionPlain") or ""]
    for lst in j.get("lists") or []:
        parts.append(lst.get("text") or "")
        parts.append(html_to_text(lst.get("content") or ""))
    parts.append(j.get("additionalPlain") or "")
    locs = [cats.get("location") or ""] + list(cats.get("allLocations") or [])
    sal = j.get("salaryRange")
    salary = None
    if sal and sal.get("min"):
        salary = f"{sal.get('currency', '')} {sal.get('min'):,}-{sal.get('max', 0):,} {sal.get('interval', '')}".strip()
    return {
        "company": company,
        "ats": "lever",
        "token": token,
        "job_id": j.get("id"),
        "title": (j.get("text") or "").strip(),
        "location": cats.get("location") or "",
        "locations": list(dict.fromkeys(l for l in locs if l)),
        "countries": [j["country"]] if j.get("country") else [],
        "url": j.get("hostedUrl"),
        "updated": j.get("createdAt"),
        "published": j.get("createdAt"),
        "department": cats.get("team") or cats.get("department") or "",
        "salary": salary,
        "text": "\n".join(p for p in parts if p).strip(),
        "remote": j.get("workplaceType") == "remote",
    }


# ---------------------------------------------------------------- SmartRecruiters

SR = "https://api.smartrecruiters.com/v1/companies"
SR_MAX = 1500


def sr_jobs(token, prev=None):
    """US postings with full ad text. Detail calls are skipped for postings unchanged since `prev`."""
    items = []
    while len(items) < SR_MAX:
        page = get_json(f"{SR}/{token}/postings?limit=100&offset={len(items)}&country=us")
        if page is None:
            return items or None
        items += page.get("content") or []
        if not page.get("content") or len(items) >= page.get("totalFound", 0):
            break
    known = {p["id"]: p for p in prev or [] if p.get("jobAd")}

    def detail(it):
        old = known.get(it["id"])
        if old and old.get("releasedDate") == it.get("releasedDate"):
            return old
        return get_json(f"{SR}/{token}/postings/{it['id']}") or it

    with ThreadPoolExecutor(4) as ex:
        return list(ex.map(detail, items))


SR_SECTIONS = ("companyDescription", "jobDescription", "qualifications", "additionalInformation")


def _norm_sr(company, token, j):
    loc = j.get("location") or {}
    secs = (j.get("jobAd") or {}).get("sections") or {}
    parts = []
    for k in SR_SECTIONS:
        sec = secs.get(k) or {}
        if sec.get("text"):
            parts.append(f"{sec.get('title') or k}:\n{html_to_text(sec['text'])}")
    where = loc.get("fullLocation") or ", ".join(x for x in (loc.get("city"), loc.get("region"), (loc.get("country") or "").upper()) if x)
    if loc.get("remote"):
        where = f"Remote - {where}" if where else "Remote"
    return {
        "company": company,
        "ats": "smartrecruiters",
        "token": token,
        "job_id": str(j["id"]),
        "title": (j.get("name") or "").strip(),
        "location": where,
        "locations": [where] if where else [],
        "countries": [loc["country"]] if loc.get("country") else [],
        "url": j.get("postingUrl") or f"https://jobs.smartrecruiters.com/{token}/{j['id']}",
        "updated": j.get("releasedDate"),
        "published": j.get("releasedDate"),
        "department": (j.get("department") or {}).get("label") or "",
        "salary": None,
        "text": "\n".join(parts),
        "remote": loc.get("remote"),
    }


# ---------------------------------------------------------------- Workable

def workable_jobs(token):
    data = get_json(f"https://apply.workable.com/api/v1/widget/accounts/{token}?details=true")
    if not data or "jobs" not in data:
        return None
    for j in data["jobs"]:
        j["_account"] = data.get("name") or ""
    return data["jobs"]


def _norm_workable(company, token, j):
    locs, countries = [], []
    for l in j.get("locations") or []:
        if l.get("hidden"):
            continue
        locs.append(", ".join(x for x in (l.get("city"), l.get("region"), l.get("country")) if x))
        countries.append(l.get("countryCode") or l.get("country") or "")
    if not locs:
        locs = [", ".join(x for x in (j.get("city"), j.get("state"), j.get("country")) if x)]
        countries = [j.get("country") or ""]
    if j.get("telecommuting"):
        locs = [f"Remote - {l}" if l else "Remote" for l in locs]
    return {
        "company": company,
        "ats": "workable",
        "token": token,
        "job_id": j.get("shortcode"),
        "title": (j.get("title") or "").strip(),
        "location": locs[0] if locs else "",
        "locations": [l for l in locs if l],
        "countries": [c for c in countries if c],
        "url": j.get("url") or j.get("shortlink"),
        "updated": j.get("published_on"),
        "published": j.get("published_on") or j.get("created_at"),
        "department": j.get("department") or "",
        "salary": None,
        "text": html_to_text(j.get("description") or ""),
        "remote": j.get("telecommuting"),
    }


# ---------------------------------------------------------------- Recruitee

def recruitee_jobs(token):
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]{1,62}", token):
        return None
    data = get_json(f"https://{token}.recruitee.com/api/offers/")
    if not data or "offers" not in data:
        return None
    return data["offers"]


def _norm_recruitee(company, token, j):
    locs = [l.get("name") and ", ".join(x for x in (l.get("city") or l.get("name"), l.get("state"), l.get("country")) if x)
            for l in j.get("locations") or []]
    locs = [l for l in locs if l] or [j.get("location") or ""]
    countries = [l.get("country_code") for l in j.get("locations") or [] if l.get("country_code")] or [j.get("country_code") or ""]
    if j.get("remote"):
        locs = [f"Remote - {l}" if l else "Remote" for l in locs]
    sal = j.get("salary") or {}
    salary = None
    if sal.get("min"):
        salary = f"{sal.get('currency') or ''} {sal['min']}-{sal.get('max') or ''} {sal.get('period') or ''}".strip()
    text = html_to_text(j.get("description") or "")
    if j.get("requirements"):
        text += "\nRequirements:\n" + html_to_text(j["requirements"])
    return {
        "company": company,
        "ats": "recruitee",
        "token": token,
        "job_id": str(j.get("id")),
        "title": (j.get("title") or "").strip(),
        "location": locs[0],
        "locations": [l for l in locs if l],
        "countries": [c for c in countries if c],
        "url": j.get("careers_url"),
        "updated": j.get("updated_at"),
        "published": j.get("published_at"),
        "department": j.get("department") or "",
        "salary": salary,
        "text": text,
        "remote": j.get("remote"),
    }


# ---------------------------------------------------------------- registry

def _gh_fetch(token, prev=None):
    data = get_json(f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs?content=true")
    return None if data is None else data.get("jobs", [])


ATS = {
    "greenhouse": (_gh_fetch, _norm_gh),
    "ashby": (lambda t, prev=None: ashby_jobs(t), _norm_ashby),
    "lever": (lambda t, prev=None: lever_jobs(t), _norm_lever),
    "smartrecruiters": (sr_jobs, _norm_sr),
    "workable": (lambda t, prev=None: workable_jobs(t), _norm_workable),
    "recruitee": (lambda t, prev=None: recruitee_jobs(t), _norm_recruitee),
}
# boards on these share slugs with unrelated small companies, so a hit must name the company
NAME_CHECKED = {"smartrecruiters", "workable", "recruitee"}


def reported_name(ats, raw):
    if not raw:
        return None
    j = raw[0]
    if ats == "smartrecruiters":
        return (j.get("company") or {}).get("name")
    if ats == "workable":
        return j.get("_account")
    if ats == "recruitee":
        return j.get("company_name")
    return None


def _words(s):
    return re.findall(r"[a-z0-9]+", (s or "").lower())


GENERIC_WORDS = {"system", "systems", "health", "care", "healthcare", "data", "global", "digital", "tech", "technology",
                 "technologies", "solutions", "services", "group", "software", "consulting", "labs", "the", "american",
                 "united", "national", "first", "general", "international", "network", "networks", "capital", "partners"}


def name_ok(expected, reported):
    """Same company if the names match ignoring spacing, or one is a whole-word prefix of the other.
    A prefix match needs a distinctive short side: "Intuitive" for Intuitive Surgical, not "System" for System Soft."""
    a, b = _words(expected), _words(reported)
    if not a or not b:
        return False
    if "".join(a) == "".join(b):
        return True
    short, long_ = sorted((a, b), key=len)
    return long_[:len(short)] == short and len("".join(short)) >= 5 and not set(short) <= GENERIC_WORDS


def normalize(ats, company, token, raw):
    return [ATS[ats][1](company, token, j) for j in raw]


# ---------------------------------------------------------------- probing and refresh

def load_companies(path: Path):
    out = []
    seen = set()
    for line in path.read_text().splitlines():
        line = re.sub(r"\s+#.*$", "", line).strip()
        if not line or line.startswith("#"):
            continue
        name, _, toks = line.partition("|")
        name = name.strip()
        if name.lower() in seen:
            continue
        seen.add(name.lower())
        if toks.strip():
            tokens = [t.strip() for t in toks.split(",") if t.strip()]
        else:
            base = re.sub(r"[^a-z0-9 ]", "", name.lower())
            tokens = list(dict.fromkeys([base.replace(" ", ""), base.replace(" ", "-")]))
        out.append((name, tokens))
    return out


def _cache_path(cache_dir, ats, token):
    return cache_dir / f"{ats}__{token}.json"


def _read_cache(cache_dir, ats, token):
    p = _cache_path(cache_dir, ats, token)
    try:
        return json.loads(p.read_text()) if p.exists() else None
    except ValueError:
        return None


def fetch_board(ats, token, cache_dir, name=None, strict=False):
    """Fetch one board fresh. Returns the raw job list, [] if empty, None if missing or not this company.

    With a name (probing), boards on NAME_CHECKED ATSes must report a matching company name; strict also
    checks the Greenhouse board name."""
    if ats == "greenhouse" and name is not None:
        board = gh_board(token)
        if board is None or strict and not name_ok(name, board.get("name")):
            return None
    if ats == "smartrecruiters" and name is not None:
        peek = get_json(f"{SR}/{token}/postings?limit=1&country=us")
        if not peek or not peek.get("content") or not name_ok(name, reported_name(ats, peek["content"])):
            return None
    raw = ATS[ats][0](token, prev=_read_cache(cache_dir, ats, token))
    if raw and name is not None and ats in NAME_CHECKED and not name_ok(name, reported_name(ats, raw)):
        return None
    if raw:
        _cache_path(cache_dir, ats, token).write_text(json.dumps(raw))
    return raw


def probe(name, tokens, cache_dir, ats_list=None, strict=False):
    """Try each ATS and token in order. Returns (ats, token, raw, tried) for the first board with jobs,
    where tried lists the ATSes that answered (a rate-limited one is left out so it gets tried again)."""
    tried = []
    for ats in ats_list or ATS:
        # "smartrecruiters:servicenow" pins a token to one ATS; plain tokens are tried everywhere
        toks = [t.split(":", 1)[1] if ":" in t else t for t in tokens if ":" not in t or t.split(":", 1)[0] == ats]
        try:
            for token in toks:
                raw = fetch_board(ats, token, cache_dir, name=name, strict=strict)
                if raw:
                    return ats, token, raw, tried + [ats]
        except RateLimited:
            continue
        tried.append(ats)
    return None, None, [], tried


REPROBE_DAYS = 7
MAX_FAILS = 3


def _due(b, today):
    """A known miss gets probed on any ATS it hasn't tried, and on all of them once a week."""
    missing = [a for a in ATS if a not in (b.get("probed") or [])]
    if (today - _day(b.get("checked"))).days >= REPROBE_DAYS:
        return list(ATS)
    return missing


def _day(s):
    from datetime import date
    try:
        return date.fromisoformat(s)
    except (TypeError, ValueError):
        return date(2000, 1, 1)


def refresh(name, tokens, prev, cache_dir, today):
    """Return (board, postings) for one company, reusing what we learned on earlier runs."""
    iso = today.isoformat()
    same = bool(prev) and prev.get("tokens") == tokens
    if same and prev.get("ats"):
        try:
            raw = fetch_board(prev["ats"], prev["token"], cache_dir)
        except RateLimited:
            return prev, []
        if raw:
            board = {**prev, "jobs": len(raw), "checked": iso, "last_hit": iso, "fails": 0}
            return board, normalize(prev["ats"], name, prev["token"], raw)
        fails = prev.get("fails", 0) + 1
        if fails < MAX_FAILS:  # could be a blip; keep the board and try again tomorrow
            return {**prev, "jobs": 0, "fails": fails}, []
        ats_list = list(ATS)  # board vanished or the company moved ATS
    elif same:
        ats_list = _due(prev, today)
        if not ats_list:
            return prev, []
    else:
        ats_list = list(ATS)
    ats, token, raw, tried = probe(name, tokens, cache_dir, ats_list)
    if ats:
        return {"company": name, "tokens": tokens, "ats": ats, "token": token, "jobs": len(raw), "checked": iso,
                "last_hit": iso, "probed": list(ATS)}, normalize(ats, name, token, raw)
    if set(ats_list) == set(ATS):  # a full probe restarts the weekly clock
        probed, checked = tried, iso
    else:
        probed, checked = sorted(set(prev.get("probed") or []) | set(tried)), prev.get("checked", iso)
    return {"company": name, "tokens": tokens, "ats": None, "token": None, "jobs": 0, "checked": checked,
            "last_hit": (prev or {}).get("last_hit"), "probed": probed}, []


def fetch_all(companies, state, cache_dir: Path, workers: int = 8, today=None):
    from datetime import date
    today = today or date.today()
    cache_dir.mkdir(parents=True, exist_ok=True)
    prev = {b["company"]: b for b in state}
    boards, postings = [], []

    def work(item):
        name, tokens = item
        try:
            return refresh(name, tokens, prev.get(name), cache_dir, today)
        except Exception as e:  # one bad board must not sink the daily run
            print(f"{name}: error {e!r}", flush=True)
            return prev.get(name) or {"company": name, "tokens": tokens, "ats": None, "token": None, "jobs": 0}, []

    with ThreadPoolExecutor(workers) as ex:
        for i, (board, jobs) in enumerate(ex.map(work, companies), 1):
            boards.append(board)
            postings.extend(jobs)
            status = f"{board['ats']}:{board['token']} {len(jobs)} jobs" if board["ats"] else "not found"
            print(f"[{i}/{len(companies)}] {board['company']}: {status}", flush=True)
    return boards, postings
