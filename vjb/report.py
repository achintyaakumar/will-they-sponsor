"""Join classified postings with filing history and form questions; write findings + board data."""
import html
import json
import re
from collections import Counter, defaultdict

import pandas as pd

from . import paths
from .filings import expand_by_fein, match_employers

TECH = {"software", "data_ml", "quant"}
STRONG = 10  # certified H-1B LCAs in the same role family this period = "sponsors this kind of role"

# verdict for an F-1 OPT holder who will need a cap-subject H-1B later
VERDICTS = {
    "blocked": "Citizens / US persons only",
    "no": "Posting says no sponsorship",
    "transfer": "H-1B transfers only",
    "yes": "Posting says it sponsors",
    "case": "Sponsorship case by case",
    "likely": "Silent, but files H-1Bs for this kind of role",
    "possible": "Silent; files H-1Bs, rarely for this kind of role",
    "unknown": "Silent, no H-1B filings found",
}


# verdict for someone already on H-1B who needs the new employer to file a transfer
VERDICTS_H1B = {
    "blocked": "Citizens / US persons only",
    "no": "Posting says no sponsorship",
    "transfer": "Transfers only",
    "yes": "Posting sponsors or takes transfers",
    "case": "Sponsorship case by case",
    "likely": "Silent, but takes H-1B transfers for this kind of role",
    "possible": "Silent; takes transfers, rarely for this kind of role",
    "unknown": "Silent, no H-1B transfers found",
}
TRANSFER_STRONG = 5


def verdict_h1b(stance, fam_transfer, co_transfer):
    if stance in ("transfer_only", "sponsors"):
        return "yes"
    if stance == "citizen_only":
        return "blocked"
    if stance == "no_sponsorship":
        return "no"
    if stance == "case_by_case":
        return "case"
    if fam_transfer >= TRANSFER_STRONG:
        return "likely"
    if co_transfer > 0:
        return "possible"
    return "unknown"


def _date(v):
    if isinstance(v, (int, float)):
        from datetime import datetime, timezone
        return datetime.fromtimestamp(v / 1000, timezone.utc).strftime("%Y-%m-%d")
    return (v or "")[:10]


def verdict(stance, fam_lca, co_lca):
    if stance == "citizen_only":
        return "blocked"
    if stance == "no_sponsorship":
        return "no"
    if stance == "transfer_only":
        return "transfer"
    if stance == "sponsors":
        return "yes"
    if stance == "case_by_case":
        return "case"
    if fam_lca >= STRONG:
        return "likely"
    if co_lca > 0:
        return "possible"
    return "unknown"


def _company_stats(lca, perm, companies):
    lm = expand_by_fein(match_employers(companies, set(lca["employer"].dropna())), lca)
    pm = match_employers(companies, set(perm["employer"].dropna())) if perm is not None else {}
    stats = {}
    for c in companies:
        sub = lca[lca["employer"].isin(lm.get(c, set()))]
        fam = {}
        for f, g in sub.groupby("family"):
            lv = g["pw_level"].fillna("").str.upper()
            fam[f] = {
                "lca": int(len(g)),
                "new": int(g["new_employment"].fillna(0).sum()),
                "transfer": int(g["change_employer"].fillna(0).sum()),
                "entry": int(lv.isin(["I", "II"]).sum()),
                "median_wage": int(g["annual_wage"].median()) if g["annual_wage"].notna().any() else None,
            }
        psub = perm[perm["employer"].isin(pm.get(c, set()))] if perm is not None else pd.DataFrame()
        stats[c] = {
            "lca": int(len(sub)),
            "new": int(sub["new_employment"].fillna(0).sum()),
            "transfer": int(sub["change_employer"].fillna(0).sum()),
            "entry": int(sub["pw_level"].fillna("").str.upper().isin(["I", "II"]).sum()),
            "perm": int(len(psub)),
            "payroll": int(psub["payroll"].max()) if len(psub) and psub["payroll"].notna().any() else None,
            "families": fam,
            "names": sorted(lm.get(c, set()))[:6],
            "top_titles": sub["job_title"].str.strip().str.title().value_counts().head(5).to_dict(),
        }
    return stats


def _forms():
    by_co = defaultdict(lambda: {"forms": 0, "asks": 0, "future": 0, "status_options": 0, "labels": Counter(), "notes": Counter()})
    if not paths.QUESTIONS.exists():
        return {}
    for r in map(json.loads, paths.QUESTIONS.open()):
        if not r["fetched"]:
            continue
        d = by_co[r["company"]]
        d["forms"] += 1
        sq = [q for q in r["questions"] if re.search(r"sponsor|visa|immigration", q["label"], re.I)]
        if sq:
            d["asks"] += 1
            d["labels"][sq[0]["label"]] += 1
        if any(q["future"] for q in sq):
            d["future"] += 1
        if any(q["status_options"] for q in r["questions"]):
            d["status_options"] += 1
        for q in sq:
            if q["desc"] and re.search(r"sponsor", q["desc"], re.I):
                d["notes"][html.unescape(q["desc"])[:300]] += 1
    out = {"__labels__": Counter()}
    for d in by_co.values():
        out["__labels__"].update(d["labels"])
    for c, d in by_co.items():
        out[c] = {k: v for k, v in d.items() if k not in ("labels", "notes")}
        out[c]["label"] = d["labels"].most_common(1)[0][0] if d["labels"] else None
        out[c]["note"] = d["notes"].most_common(1)[0][0] if d["notes"] else None
    return out


def run():
    rows = [json.loads(l) for l in paths.CLASSIFIED.open()]
    us = [r for r in rows if r["us"]]
    companies = sorted({r["company"] for r in rows})
    lca = pd.read_parquet(paths.LCA) if paths.LCA.exists() else None
    perm = pd.read_parquet(paths.PERM) if paths.PERM.exists() else None
    if lca is None:
        print("report: no LCA data yet; history-based verdicts will all be 'unknown'")
        lca = pd.DataFrame(columns=["employer", "family", "pw_level", "new_employment", "change_employer", "annual_wage", "job_title", "fein"])
    stats = _company_stats(lca, perm, companies)
    forms = _forms()
    form_labels = forms.pop("__labels__", Counter()).most_common(8) if forms else []

    for r in us:
        s = stats[r["company"]]
        r["fam_lca"] = s["families"].get(r["family"], {}).get("lca", 0)
        r["co_lca"] = s["lca"]
        r["verdict"] = verdict(r["stance"], r["fam_lca"], r["co_lca"])
        r["fam_transfer"] = s["families"].get(r["family"], {}).get("transfer", 0)
        r["verdict_h1b"] = verdict_h1b(r["stance"], r["fam_transfer"], s["transfer"])

    # ---------------------------------------------------------------- findings
    f = {}
    f["period"] = {
        "lca": f"{lca['decision_date'].min():%b %Y} – {lca['decision_date'].max():%b %Y}" if len(lca) and "decision_date" in lca else None,
        "perm": f"{perm['decision_date'].min():%b %Y} – {perm['decision_date'].max():%b %Y}" if perm is not None else None,
        "lca_rows": int(len(lca)),
        "perm_rows": int(len(perm)) if perm is not None else 0,
    }
    f["companies"] = len(companies)
    f["ats"] = Counter({r["company"]: r["ats"] for r in us}.values())
    f["companies_with_us_jobs"] = len({r["company"] for r in us})
    f["postings"] = len(rows)
    f["us_postings"] = len(us)
    f["stance"] = Counter(r["stance"] for r in us)
    f["verdict"] = Counter(r["verdict"] for r in us)
    f["verdict_h1b"] = Counter(r["verdict_h1b"] for r in us)
    tech = [r for r in us if r["family"] in TECH]
    f["tech_postings"] = len(tech)
    f["tech_stance"] = Counter(r["stance"] for r in tech)
    f["tech_verdict"] = Counter(r["verdict"] for r in tech)
    silent = {"none", "auth_required", "export_control"}
    f["tech_silent_share"] = sum(r["stance"] in silent for r in tech) / max(1, len(tech))

    strong = [r for r in tech if r["fam_lca"] >= STRONG]
    f["strong_tech_postings"] = len(strong)
    f["strong_tech_companies"] = len({r["company"] for r in strong})
    f["strong_tech_stance"] = Counter(r["stance"] for r in strong)
    contra = [r for r in strong if r["stance"] in ("no_sponsorship", "citizen_only")]
    f["contradictions"] = len(contra)
    f["contradiction_share"] = len(contra) / max(1, len(strong))
    f["contradiction_companies"] = Counter(r["company"] for r in contra).most_common(25)
    f["contradiction_by_stance"] = Counter(r["stance"] for r in contra)
    if contra:
        top = f["contradiction_companies"][0][0]
        rest_strong = [r for r in strong if r["company"] != top]
        rest_contra = [r for r in contra if r["company"] != top]
        f["contradiction_ex_top"] = {"company": top, "contradictions": len(rest_contra), "strong": len(rest_strong),
                                     "share": len(rest_contra) / max(1, len(rest_strong)),
                                     "no_sponsorship": sum(r["stance"] == "no_sponsorship" for r in rest_contra)}
    contra_quotes = {}
    for c, _ in f["contradiction_companies"]:
        qs = Counter((r.get("llm_quote") or (r["evidence"] or [""])[0]) for r in contra if r["company"] == c)
        contra_quotes[c] = qs.most_common(1)[0][0] if qs else ""

    early = [r for r in tech if r["seniority"] in ("early", "intern")]
    f["early_tech_postings"] = len(early)
    f["early_tech_verdict"] = Counter(r["verdict"] for r in early)

    # companies whose postings disagree with each other
    mixed = []
    by_co = defaultdict(list)
    for r in us:
        by_co[r["company"]].append(r)
    for c, rs in by_co.items():
        st = Counter(r["stance"] for r in rs)
        pos = st["sponsors"] + st["case_by_case"]
        neg = st["no_sponsorship"] + st["citizen_only"]
        if pos and neg:
            mixed.append({"company": c, "postings": len(rs), "positive": pos, "negative": neg, "silent": len(rs) - pos - neg,
                          "lca": stats[c]["lca"]})
    f["mixed_companies"] = sorted(mixed, key=lambda m: -(min(m["positive"], m["negative"])))

    fr = [v for v in forms.values()]
    f["forms"] = {
        "companies": len(fr),
        "forms": sum(v["forms"] for v in fr),
        "asks": sum(v["asks"] for v in fr),
        "future": sum(v["future"] for v in fr),
        "status_options": sum(v["status_options"] for v in fr),
        "companies_status_options": sorted(c for c, v in forms.items() if v["status_options"]),
    }

    # company table
    table = []
    for c in companies:
        rs = by_co.get(c, [])
        if not rs:
            continue
        st = Counter(r["stance"] for r in rs)
        s = stats[c]
        sw = s["families"].get("software", {})
        table.append({
            "company": c,
            "us_postings": len(rs),
            "tech_postings": sum(r["family"] in TECH for r in rs),
            "stance": dict(st),
            "lca": s["lca"], "new": s["new"], "transfer": s["transfer"], "entry": s["entry"], "perm": s["perm"],
            "sw_lca": sw.get("lca", 0), "sw_entry": sw.get("entry", 0), "sw_median_wage": sw.get("median_wage"),
            "dm_lca": s["families"].get("data_ml", {}).get("lca", 0),
            "names": s["names"], "top_titles": s["top_titles"],
            "form": forms.get(c),
            "ats": rs[0]["ats"],
        })
    f["company_table"] = sorted(table, key=lambda t: -t["lca"])

    # LLM vs regex agreement on postings that had any relevant text
    judged = [r for r in us if r.get("llm_stance")]
    f["llm"] = {"judged": len(judged), "agree": sum(r["llm_stance"] == r["regex_stance"] or (r["regex_stance"] == "none" and r["llm_stance"] == "export_control") for r in judged),
                "confusion": Counter(f"{r['regex_stance']}→{r['llm_stance']}" for r in judged if r["llm_stance"] != r["regex_stance"]).most_common(12)}

    (paths.OUT / "findings.json").write_text(json.dumps(f, indent=1, default=str))

    # ---------------------------------------------------------------- board data (dictionary-encoded)
    strings = {}

    def sid(s):
        s = (s or "").strip()
        if s not in strings:
            strings[s] = len(strings)
        return strings[s]

    cos = sorted(by_co)
    co_idx = {c: i for i, c in enumerate(cos)}
    jobs = []
    for r in us:
        quote = r.get("llm_quote") or (r["evidence"][0] if r["evidence"] and r["stance"] != "none" else "")
        jobs.append([
            co_idx[r["company"]], r["title"], r["location"][:80], r["url"], r["family"], r["seniority"],
            r["stance"], r["verdict"], sid(quote[:240]), sid((r.get("llm_note") or "")[:160]), r["fam_lca"],
            _date(r.get("published")), r.get("salary") or "", r["verdict_h1b"], r["fam_transfer"],
        ])
    board = {
        "companies": [{"name": c, **{k: v for k, v in next(t for t in table if t["company"] == c).items() if k in (
            "lca", "new", "transfer", "entry", "perm", "sw_lca", "sw_entry", "sw_median_wage", "dm_lca", "ats", "names")},
            "form": forms.get(c)} for c in cos],
        "strings": list(strings),
        "jobs": jobs,
        "verdicts": {"opt": VERDICTS, "h1b": VERDICTS_H1B},
    }
    (paths.OUT / "board_data.json").write_text(json.dumps(board, separators=(",", ":"), default=str))
    build_page(f, board, contra_quotes if contra else {}, form_labels)
    print(json.dumps({k: f[k] for k in ("us_postings", "tech_postings", "tech_silent_share", "strong_tech_postings",
                                        "strong_tech_companies", "contradictions", "contradiction_share")}, default=str))
    print("verdict:", dict(f["verdict"]))
    print("tech stance:", dict(f["tech_stance"]))
    print("forms:", f["forms"])
    print("llm:", f["llm"])
    print(f"wrote {paths.OUT / 'findings.json'} and board_data.json ({(paths.OUT / 'board_data.json').stat().st_size / 1e6:.1f} MB)")


SITE_TITLE = "Will They Sponsor?"
SITE_DESC = ("US job postings with a visa sponsorship verdict for F-1 OPT and H-1B holders, from each posting's own wording, "
             "the employer's H-1B filings for that kind of role, and its application form.")
FAVICON = ('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect x="2" y="2" width="28" height="28" rx="6" fill="#1f4e8c"/>'
           '<path d="M9 16.5l4.5 4.5L23 11.5" fill="none" stroke="#fff" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"/></svg>\n')
HEADERS = """/*
  X-Content-Type-Options: nosniff
  Referrer-Policy: strict-origin-when-cross-origin
/data.json
  Cache-Control: public, max-age=300
"""


def _js_json(obj):
    return json.dumps(obj, separators=(",", ":"), default=str).replace("</", "<\\/")


def build_page(findings, board, contra_quotes, form_labels):
    import hashlib
    import os
    from datetime import date
    fetched = date.fromtimestamp(paths.POSTINGS.stat().st_mtime).strftime("%b %-d, %Y")
    data = {"findings": findings, "board": board, "strong": STRONG, "contra_quotes": contra_quotes,
            "form_labels": form_labels, "fetched": fetched}
    blob = json.dumps(data, separators=(",", ":"), default=str)
    tpl = (paths.ROOT / "vjb" / "page_template.html").read_text()

    # one self-contained file, for the claude.ai artifact
    out = paths.OUT / "index.html"
    out.write_text(tpl.replace("/*__CFG__*/", _js_json({"mode": "artifact"})).replace("/*__DATA__*/", blob.replace("</", "<\\/")))
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")

    # the public site: same page as a full document, data fetched from data.json
    repo = os.environ.get("VJB_REPO_URL", "").rstrip("/")
    site_url = os.environ.get("VJB_SITE_URL", "").rstrip("/")
    cfg = {"mode": "site", "repo": repo, "build": hashlib.sha1(blob.encode()).hexdigest()[:10]}
    page = tpl.replace("/*__CFG__*/", _js_json(cfg)).replace("/*__DATA__*/", "")
    cut = page.index("</style>") + len("</style>")
    meta = [
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">',
        f'<meta name="description" content="{html.escape(SITE_DESC)}">',
        f'<meta property="og:title" content="{SITE_TITLE}">',
        f'<meta property="og:description" content="{html.escape(SITE_DESC)}">',
        '<meta property="og:type" content="website">',
        *([f'<meta property="og:url" content="{html.escape(site_url)}/">', f'<link rel="canonical" href="{html.escape(site_url)}/">',
           f'<meta property="og:image" content="{html.escape(site_url)}/og.png">', '<meta property="og:image:width" content="1200">',
           '<meta property="og:image:height" content="630">'] if site_url else []),
        f'<meta name="twitter:card" content="{"summary_large_image" if site_url else "summary"}">',
        '<link rel="icon" href="favicon.svg" type="image/svg+xml">',
        '<style>:root{color-scheme:light;padding-top:env(safe-area-inset-top,0px);padding-bottom:env(safe-area-inset-bottom,0px)}'
        'body{margin:0}img{max-width:100%}[hidden]{display:none!important}</style>',
    ]
    doc = ('<!doctype html>\n<html lang="en">\n<head>\n' + "\n".join(meta) + "\n" + page[:cut].strip() +
           "\n</head>\n<body>\n" + page[cut:].strip() + "\n</body>\n</html>\n")
    (paths.SITE / "index.html").write_text(doc)
    (paths.SITE / "data.json").write_text(blob)
    (paths.SITE / "favicon.svg").write_text(FAVICON)
    (paths.SITE / "_headers").write_text(HEADERS)
    (paths.SITE / "robots.txt").write_text("User-agent: *\nAllow: /\n")
    og = paths.ROOT / "assets" / "og.png"  # rendered from assets/og-card.html
    if og.exists():
        (paths.SITE / "og.png").write_bytes(og.read_bytes())
    print(f"wrote {paths.SITE}/ (index.html {len(doc) / 1e3:.0f} KB, data.json {len(blob) / 1e6:.1f} MB)")
