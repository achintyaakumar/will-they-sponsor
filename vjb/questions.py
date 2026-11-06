"""Pull Greenhouse application-form questions for a sample of US postings and pick out the visa ones."""
import hashlib
import json
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

from . import paths
from .ats import gh_job_questions
from .roles import is_us, role_family, seniority

PER_COMPANY = 20
VISA_Q = re.compile(r"sponsor|visa|immigration|authori[sz]ed to work|work authori[sz]ation|legally (?:able|eligible|authori[sz]ed)|citizen|"
                    r"right to work|work permit|export|itar|u\.?s\.? person|clearance", re.I)
FUTURE = re.compile(r"(now|currently|today)\W+(?:\w+\W+){0,4}?(in the future|future)|in the future|will you (?:ever )?(?:need|require)", re.I)
STATUS_OPTS = re.compile(r"\bopt\b|\bcpt\b|f-?1|h-?1-?b|green card|permanent resident|tn\b|e-?3|h-?4|l-?1|l-?2|ead", re.I)


def _kind(text):
    t = text.lower()
    if re.search(r"sponsor|visa status|immigration", t):
        return "sponsorship"
    if re.search(r"citizen|u\.?s\.? person|export|itar|clearance", t):
        return "citizen_export"
    return "authorized"


def extract(q):
    out = []
    for qq in (q or {}).get("questions", []) + (q or {}).get("location_questions", []) or []:
        label = (qq.get("label") or "").strip()
        desc = re.sub(r"<[^>]+>", " ", qq.get("description") or "").strip()
        if not VISA_Q.search(label + " " + desc):
            continue
        opts = [v.get("label", "") for f in qq.get("fields", []) for v in f.get("values", []) or []]
        out.append({
            "label": label[:400],
            "desc": desc[:400],
            "required": bool(qq.get("required")),
            "options": opts[:20],
            "kind": _kind(label + " " + desc),
            "future": bool(FUTURE.search(label)),
            "status_options": sum(bool(STATUS_OPTS.search(o)) for o in opts) >= 2,
        })
    return out


def run():
    postings = [json.loads(l) for l in paths.POSTINGS.open()]
    by_co = defaultdict(list)
    for p in postings:
        if p["ats"] == "greenhouse" and is_us(p["locations"], p["countries"]):
            by_co[p["token"]].append(p)
    # postings whose form we already have come first, then a stable hash order: a posting stays in the
    # sample while it's open, so the daily job only fetches forms for new postings
    cached = {(r["token"], r["job_id"]) for r in map(json.loads, paths.QUESTIONS.open())} if paths.QUESTIONS.exists() else set()
    order = lambda p: ((p["token"], p["job_id"]) not in cached, hashlib.sha1(f"{p['token']}/{p['job_id']}".encode()).hexdigest())
    sample = []
    for tok, ps in by_co.items():
        tech = sorted((p for p in ps if role_family(p["title"]) in ("software", "data_ml", "quant")), key=order)
        early = [p for p in tech if seniority(p["title"]) in ("early", "intern")]
        rest = sorted((p for p in ps if p not in tech), key=order)
        pick = (early[:8] + [p for p in tech if p not in early][:8] + rest)[:PER_COMPANY]
        sample += pick

    # keep only forms for postings still in the sample, so the committed cache tracks live postings
    want = {(p["token"], p["job_id"]) for p in sample}
    kept = [r for r in map(json.loads, paths.QUESTIONS.open())] if paths.QUESTIONS.exists() else []
    kept = [r for r in kept if (r["token"], r["job_id"]) in want]
    with paths.QUESTIONS.open("w") as f:
        for r in kept:
            f.write(json.dumps(r) + "\n")
    done = {(r["token"], r["job_id"]) for r in kept}
    todo = [p for p in sample if (p["token"], p["job_id"]) not in done]
    print(f"questions: {len(sample)} sampled across {len(by_co)} Greenhouse companies, {len(kept)} cached, {len(todo)} to fetch", flush=True)

    def work(p):
        q = gh_job_questions(p["token"], p["job_id"])
        return {"company": p["company"], "token": p["token"], "job_id": p["job_id"], "title": p["title"],
                "fetched": q is not None, "questions": extract(q)}

    with ThreadPoolExecutor(6) as ex, paths.QUESTIONS.open("a") as f:
        for i, row in enumerate(ex.map(work, todo), 1):
            f.write(json.dumps(row) + "\n")
            if i % 200 == 0:
                print(f"questions: {i}/{len(todo)}", flush=True)
    print("questions: done")
