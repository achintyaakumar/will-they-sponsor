"""Find public job boards for the largest H-1B filers that companies.txt doesn't cover yet.

Each filer name is turned into a few board slugs and probed on every supported ATS. A hit must name the
same company (or, on Ashby and Lever, which don't report a name, mention it in most posting texts) and have
US postings. Hits are appended to companies.txt; filer names that the display name won't match are written
to data/aliases.json so the LCA counts line up.
"""
import json
import os
import re
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import pandas as pd

from . import paths
from .ats import ATS, NAME_CHECKED, gh_board, load_companies, normalize, probe, reported_name
from .filings import ALIASES_FILE, expand_by_fein, match_employers, norm
from .roles import is_us

TOP = int(os.environ.get("VJB_DISCOVER_TOP", "500"))
MIN_US = 3
# Workable rate-limits hard and hosts small companies; the daily fetch still tries it for companies.txt
DISCOVER_ATS = [a for a in ATS if a != "workable"]
SKIP = re.compile(r"UNIVERSITY|COLLEGE|SCHOOL|HOSPITAL|MEDICAL CENTER|HEALTH SYSTEM|CLINIC|STATE OF|COUNTY|CITY OF|"
                  r"BOARD OF|DEPARTMENT OF|INSTITUTE|ACADEMY|RESEARCH FOUNDATION|CHILDREN S", re.I)
GENERIC = {"american", "united", "global", "national", "first", "general", "international", "digital", "data", "systems",
           "tech", "technologies", "solutions", "services", "new", "north", "advanced", "applied", "pacific"}


def slugs(filer):
    toks = [re.sub(r"[^a-z0-9]", "", t) for t in norm(filer).lower().split()]
    toks = [t for t in toks if t]
    out = []
    if len(toks) >= 2:
        out.append(toks[0] + toks[1])
    if toks and (len(toks) == 1 or len(toks[0]) >= 5) and toks[0] not in GENERIC:
        out.append(toks[0])
    if len(toks) >= 2:
        out.append(f"{toks[0]}-{toks[1]}")
    return list(dict.fromkeys(out))[:3]


def display_name(filer, reported):
    if reported:
        return re.sub(r"\s*\((?:US|USA|United States)\)$", "", reported.strip())
    return " ".join(w if w.isupper() and len(w) <= 3 else w.title() for w in norm(filer).split())


def mentions(filer, postings):
    """Most postings name the company in full ("Health Care Service", not just "healthcare"). Ashby and Lever
    don't report a board's company name, so this is the only check there; one-word names must be long."""
    toks = norm(filer).lower().split()
    if not toks or not postings or (len(toks) == 1 and len(toks[0]) < 8):
        return False
    rx = re.compile(r"\b" + r"\W*".join(map(re.escape, toks)) + r"\b", re.I)
    return sum(bool(rx.search(p["text"])) for p in postings) / len(postings) >= 0.3


def candidates(lca, existing):
    counts = Counter(lca["employer"].dropna().map(norm))
    covered = set()
    matched = expand_by_fein(match_employers(existing, set(lca["employer"].dropna())), lca)
    for names in matched.values():
        covered |= {norm(n) for n in names}
    covered |= {norm(c) for c in existing}
    out = []
    for n, k in counts.most_common():
        if len(out) >= TOP:
            break
        if not n or n in covered or SKIP.search(n) or not slugs(n):
            continue
        out.append((n, k))
    return out


def run():
    lca = pd.read_parquet(paths.LCA, columns=["employer", "fein"])
    existing = [c for c, _ in load_companies(paths.COMPANIES)]
    cands = candidates(lca, existing)
    print(f"discover: probing {len(cands)} filers (largest not in companies.txt, {cands[-1][1] if cands else 0}+ LCAs)", flush=True)

    def work(item):
        filer, k = item
        ats, token, raw, _ = probe(filer, slugs(filer), paths.CACHE, DISCOVER_ATS, strict=True)
        if not ats:
            return None
        rep = reported_name(ats, raw) or ((gh_board(token) or {}).get("name") if ats == "greenhouse" else None)
        name = display_name(filer, rep)
        posts = normalize(ats, name, token, raw)
        us = [p for p in posts if is_us(p["locations"], p["countries"])]
        if len(us) < MIN_US:
            return None
        if ats not in NAME_CHECKED and ats != "greenhouse" and not mentions(filer, posts):
            return None
        return {"filer": filer, "lca": k, "name": name, "ats": ats, "token": token, "us": len(us), "jobs": len(posts)}

    hits = []
    with ThreadPoolExecutor(8) as ex:
        for i, h in enumerate(ex.map(work, cands), 1):
            if h:
                hits.append(h)
                print(f"discover: {h['filer']} -> {h['name']} on {h['ats']}:{h['token']} ({h['us']} US jobs, {h['lca']} LCAs)", flush=True)
            if i % 50 == 0:
                print(f"discover: {i}/{len(cands)} probed, {len(hits)} found", flush=True)

    seen = {c.lower() for c in existing}
    new = []
    for h in sorted(hits, key=lambda h: -h["lca"]):
        if h["name"].lower() in seen:
            continue
        seen.add(h["name"].lower())
        new.append(h)
    if not new:
        print("discover: nothing new")
        return
    with paths.COMPANIES.open("a") as f:
        f.write(f"\n# discovered {date.today().isoformat()}: largest H-1B filers with a public board (python -m vjb discover)\n")
        for h in new:
            f.write(f"{h['name']} | {h['ats']}:{h['token']}\n")

    # make sure the LCA match finds the filer that led us here
    aliases = json.loads(ALIASES_FILE.read_text()) if ALIASES_FILE.exists() else {}
    names = set(lca["employer"].dropna())
    matched = match_employers([h["name"] for h in new], names)
    for h in new:
        if not any(norm(n) == h["filer"] for n in matched.get(h["name"], ())):
            aliases.setdefault(h["name"], [])
            if h["filer"] not in aliases[h["name"]]:
                aliases[h["name"]].append(h["filer"])
    ALIASES_FILE.write_text(json.dumps(dict(sorted(aliases.items())), indent=1))
    (paths.WORK / "discovered.json").write_text(json.dumps(new, indent=1))
    print(f"discover: added {len(new)} companies to {paths.COMPANIES.name}; {len(aliases)} aliases in {ALIASES_FILE.name}")
