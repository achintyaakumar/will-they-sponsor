from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAW = ROOT / "data" / "raw"          # DOL downloads, not committed
FILINGS = ROOT / "data" / "filings"  # parquet built from RAW, committed, rebuilt quarterly
STATE = ROOT / "data" / "state"      # small caches the daily job carries forward, committed
WORK = ROOT / "data" / "work"        # per-run scratch, not committed
CACHE = WORK / "boards"
OUT = ROOT / "out"
SITE = OUT / "site"                  # what gets deployed

for d in (RAW, FILINGS, STATE, WORK, CACHE, OUT, SITE):
    d.mkdir(parents=True, exist_ok=True)

COMPANIES = ROOT / "companies.txt"
BOARDS = STATE / "boards.json"
QUESTIONS = STATE / "gh_questions.jsonl"
LLM_CACHE = STATE / "llm_cache.jsonl"
LCA = FILINGS / "lca.parquet"
PERM = FILINGS / "perm.parquet"
USCIS = FILINGS / "uscis.parquet"
POSTINGS = WORK / "postings.jsonl"
CLASSIFIED = WORK / "classified.jsonl"
