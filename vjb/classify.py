"""Run the regex rules over every posting, send ambiguous ones to the LLM, and write classified.jsonl."""
import json
import sys

from . import llm, paths
from .roles import is_us, role_family, seniority
from .rules import analyze, is_ambiguous, stance

TECH = {"software", "data_ml", "quant"}
LLM_STANCES = {"citizen_only", "no_sponsorship", "case_by_case", "sponsors", "transfer_only", "auth_required", "export_control", "none"}


def run(use_llm=True, llm_all=True):
    postings = [json.loads(l) for l in paths.POSTINGS.open()]
    rows, bundles = [], {}
    for p in postings:
        us = is_us(p["locations"], p["countries"])
        r = analyze(p["text"])
        row = {k: p[k] for k in ("company", "ats", "token", "job_id", "title", "location", "url", "department", "salary", "published")}
        row.update({
            "us": us,
            "family": role_family(p["title"]),
            "seniority": seniority(p["title"]),
            "regex_stance": stance(r["labels"]),
            "labels": sorted(r["labels"]),
            "evidence": r["sentences"][:12],
            "everify": "everify" in r["labels"],
            "ambiguous": is_ambiguous(r),
        })
        if r["sentences"] and us is not False:
            key, text = llm.bundle_key(p["company"], r["sentences"], p["title"])
            row["bundle"] = key
            if llm_all or row["ambiguous"]:
                prio = (us is True) * 2 + (row["family"] in TECH)
                b = bundles.setdefault(key, {"key": key, "company": p["company"], "text": text, "prio": prio})
                b["prio"] = max(b["prio"], prio)
        rows.append(row)

    # when the call cap bites, US tech postings get classified first
    todo = sorted(bundles.values(), key=lambda b: -b["prio"])
    if use_llm and not llm.available():
        print("classify: no ANTHROPIC_API_KEY and no claude CLI; using cached LLM results only")
        use_llm = False
    cache = llm.classify(todo) if use_llm and bundles else llm.load_cache()
    agree = total = 0
    for row in rows:
        res = cache.get(row.get("bundle"))
        if res and res["stance"] in LLM_STANCES:
            row["llm_stance"] = res["stance"]
            row["llm_note"] = res["note"]
            row["llm_quote"] = res["quote"]
            row["opt_ok"] = res["opt_ok"]
            row["stance"] = res["stance"]
            # a hard clearance/citizenship requirement beats a hedged model answer
            if row["regex_stance"] == "citizen_only" and res["stance"] in ("case_by_case", "auth_required", "sponsors"):
                row["stance"] = "citizen_only"
            total += 1
            agree += _same(row["regex_stance"], res["stance"])
        else:
            row["stance"] = row["regex_stance"]
    with paths.CLASSIFIED.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")
    print(f"classified {len(rows)} postings; llm-labelled {total}; regex/llm agreement {agree}/{total}")


def _same(regex, llm_stance):
    if regex == llm_stance:
        return 1
    # the regex rules have no export_control stance; they report those as none
    return int(regex == "none" and llm_stance == "export_control")


if __name__ == "__main__":
    run(use_llm="--no-llm" not in sys.argv)
