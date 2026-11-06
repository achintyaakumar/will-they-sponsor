"""CLI: python -m vjb <command>

  fetch       refresh every board in companies.txt (probes new or missing companies) and save postings
  discover    probe the largest H-1B filers not yet in companies.txt and append the ones with public boards
  questions   pull Greenhouse application-form questions for a sample of US jobs
  filings     load DOL LCA / PERM files from data/raw into data/filings (quarterly, local only)
  classify    regex + LLM sponsorship classification of every posting
  report      join everything and write out/findings.json, out/index.html and the site in out/site
  daily       fetch, questions, classify, report: what the scheduled job runs
  all         fetch, questions, filings, classify, report
"""
import json
import os
import sys

from . import paths


def cmd_fetch():
    from .ats import fetch_all, load_companies
    companies = load_companies(paths.COMPANIES)
    state = json.loads(paths.BOARDS.read_text()) if paths.BOARDS.exists() else []
    boards, postings = fetch_all(companies, state, paths.CACHE)
    before = sum(b.get("jobs", 0) for b in state if b.get("ats"))
    if before and len(postings) < before * 0.5 and not os.environ.get("VJB_FORCE"):
        sys.exit(f"fetch: only {len(postings)} postings against {before} last run; something is broken, not publishing "
                 "(set VJB_FORCE=1 to accept)")
    paths.BOARDS.write_text(json.dumps(sorted(boards, key=lambda b: b["company"].lower()), indent=1))
    with paths.POSTINGS.open("w") as f:
        for p in postings:
            f.write(json.dumps(p) + "\n")
    found = [b for b in boards if b["ats"]]
    print(f"\n{len(found)}/{len(boards)} companies found, {len(postings)} postings -> {paths.POSTINGS}")


def cmd_discover():
    from .discover import run
    run()


def cmd_questions():
    from .questions import run
    run()


def cmd_filings():
    from .filings import build
    build()


def cmd_classify():
    from .classify import run
    run()


def cmd_report():
    from .report import run
    run()


COMMANDS = {
    "fetch": cmd_fetch,
    "discover": cmd_discover,
    "questions": cmd_questions,
    "filings": cmd_filings,
    "classify": cmd_classify,
    "report": cmd_report,
}
PIPELINES = {
    "daily": ("fetch", "questions", "classify", "report"),
    "all": ("fetch", "questions", "filings", "classify", "report"),
}


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd in PIPELINES:
        for name in PIPELINES[cmd]:
            print(f"\n===== {name} =====", flush=True)
            COMMANDS[name]()
    elif cmd in COMMANDS:
        COMMANDS[cmd]()
    else:
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
