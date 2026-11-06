"""Batch-classify sponsorship text with Claude Haiku, cached by bundle hash.

Uses the Messages API when ANTHROPIC_API_KEY is set (the scheduled job), otherwise the local `claude` CLI."""
import hashlib
import json
import os
import re
import subprocess
import time
import threading
from concurrent.futures import ThreadPoolExecutor

from . import paths

MODEL = "haiku"
API_MODEL = "claude-haiku-4-5-20251001"
API_URL = "https://api.anthropic.com/v1/messages"
BATCH = 15
MAX_CALLS = int(os.environ.get("VJB_MAX_LLM_CALLS", "400"))
WORKERS = 4

SYSTEM = """You classify what US job postings say about immigration / work authorization.

The reader is an international student in the US on F-1 OPT (or STEM OPT). They can work today on their OPT EAD,
but will need an employer to sponsor an H-1B (cap-subject) later. Decide, for each snippet set, what the posting
means for that person applying to a US-based role.

stance (pick exactly one):
- "citizen_only": requires US citizenship, a US security clearance, or "US person" status (ITAR/EAR: citizen, green card, refugee/asylee). A clearance that is only "preferred"/"a plus" does NOT count.
- "no_sponsorship": will not sponsor visas for this role, or requires authorization "now and in the future"/"without sponsorship", or requires unrestricted/permanent authorization.
- "case_by_case": sponsorship possible but not guaranteed, depends on role/business need/candidate, or sponsors only some role types (say which in note).
- "sponsors": says it sponsors visas / supports immigration for this role.
- "transfer_only": will only take over an existing H-1B, no new sponsorship.
- "auth_required": requires current US work authorization but says nothing about future sponsorship (OPT holders can usually apply).
- "export_control": export-controlled role where non-US-persons may need an export license; employer doesn't say it refuses.
- "none": nothing about US work authorization (generic I-9/E-Verify notices, EEO text, HR job duties about immigration, non-US locations).

opt_ok: true if OPT/STEM OPT holders can apply per the text, false if they're excluded, null if unclear.
note: <= 15 words, plain English, the reason. Mention role conditions if any (e.g. "only engineering/product roles sponsored").
quote: the single most decisive sentence, copied verbatim (<= 200 chars), or "" for none.

Return ONLY a JSON array, one object per input id: [{"id": 1, "stance": "...", "opt_ok": null, "note": "...", "quote": "..."}]"""

_lock = threading.Lock()


def bundle_key(company, sentences, title=""):
    text = "\n".join(sentences)
    # some companies sponsor only certain role types; keep the title in the key for those
    if re.search(r"roles? (outside|in|within) |(engineering|product|technical|research) (and \w+ )?roles|for (certain|some|select) (roles|positions)", text, re.I):
        text = f"title={title}\n{text}"
    return hashlib.sha1(f"{company}\n{text}".encode()).hexdigest()[:16], text


def load_cache():
    cache = {}
    if paths.LLM_CACHE.exists():
        for line in paths.LLM_CACHE.read_text().splitlines():
            if line.strip():
                row = json.loads(line)
                cache[row["key"]] = row
    return cache


def available():
    import shutil
    return bool(os.environ.get("ANTHROPIC_API_KEY")) or shutil.which("claude") is not None


def _prompt(batch):
    return "Classify each snippet set.\n\n" + "\n\n".join(
        f"### id {i}\ncompany: {b['company']}\n{b['text']}" for i, b in enumerate(batch, 1)
    )


def _call_cli(prompt):
    cmd = ["claude", "-p", "--model", MODEL, "--output-format", "json", "--tools", "", "--strict-mcp-config",
           "--no-session-persistence", "--system-prompt", SYSTEM]
    try:
        out = subprocess.run(cmd, input=prompt, capture_output=True, text=True, timeout=180, cwd=paths.ROOT)
        return json.loads(out.stdout)["result"]
    except (subprocess.TimeoutExpired, ValueError, KeyError, TypeError):
        return None


def _call_api(prompt, key):
    import requests
    body = {"model": API_MODEL, "max_tokens": 4096, "system": SYSTEM, "messages": [{"role": "user", "content": prompt}]}
    headers = {"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"}
    for attempt in range(4):
        try:
            r = requests.post(API_URL, json=body, headers=headers, timeout=180)
        except requests.RequestException:
            time.sleep(5 * (attempt + 1))
            continue
        if r.status_code in (429, 500, 502, 503, 529):
            time.sleep(float(r.headers.get("retry-after") or 10 * (attempt + 1)))
            continue
        if r.status_code != 200:
            print(f"llm: API error {r.status_code}: {r.text[:200]}", flush=True)
            return None
        return "".join(b.get("text", "") for b in r.json().get("content", []) if b.get("type") == "text")
    return None


def parse_result(result, n):
    """Pull the JSON array out of a model reply; return a list of n results (None where missing)."""
    try:
        rows = json.loads(re.search(r"\[.*\]", result, re.S).group(0))
    except (ValueError, AttributeError, TypeError):
        return None
    by_id = {r.get("id"): r for r in rows if isinstance(r, dict)}
    return [by_id.get(i) for i in range(1, n + 1)]


def _call(batch):
    key = os.environ.get("ANTHROPIC_API_KEY")
    prompt = _prompt(batch)
    result = _call_api(prompt, key) if key else _call_cli(prompt)
    return parse_result(result, len(batch)) if result else None


def classify(bundles, max_calls=MAX_CALLS):
    """bundles: list of {key, company, text}. Returns {key: result}. Uncached ones go to the model, capped."""
    cache = load_cache()
    todo = [b for b in bundles if b["key"] not in cache]
    batches = [todo[i:i + BATCH] for i in range(0, len(todo), BATCH)][:max_calls]
    print(f"llm: {len(bundles)} bundles, {len(bundles) - len(todo)} cached, {len(batches)} calls to make", flush=True)
    done = [0]

    def work(batch):
        res = _call(batch)
        if res is None:
            res = _call(batch)  # one retry
        rows = []
        for b, r in zip(batch, res or [None] * len(batch)):
            if r and r.get("stance"):
                rows.append({"key": b["key"], "stance": r["stance"], "opt_ok": r.get("opt_ok"),
                             "note": r.get("note", ""), "quote": r.get("quote", ""),
                             "model": API_MODEL if os.environ.get("ANTHROPIC_API_KEY") else MODEL})
        with _lock:
            with paths.LLM_CACHE.open("a") as f:
                for row in rows:
                    f.write(json.dumps(row) + "\n")
                    cache[row["key"]] = row
            done[0] += 1
            if done[0] % 10 == 0 or done[0] == len(batches):
                print(f"llm: {done[0]}/{len(batches)} calls", flush=True)

    with ThreadPoolExecutor(WORKERS) as ex:
        list(ex.map(work, batches))
    return cache
