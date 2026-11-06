# Will They Sponsor?

A job board that gives every US posting a sponsorship verdict for people on a student or work visa,
instead of a per-company "sponsors H-1B" flag.

Each verdict combines three sources:

1. **The posting text.** Regex rules find sentences about sponsorship, work authorization,
   citizenship, security clearances and export control. Claude Haiku reads every posting that has
   such text and decides the final stance.
2. **Filing history.** DOL LCA disclosure data (certified H-1B cases) and PERM green-card data,
   matched to companies by normalized name, aliases and FEIN, and bucketed by role type.
3. **The application form.** Greenhouse's public API exposes the form questions. We sample them to see
   whether the form asks "now or in the future" and whether it lets you pick a visa type.

Postings come from the public job-board APIs of Greenhouse, Ashby, Lever, SmartRecruiters, Workable
and Recruitee.

## Run it locally

```sh
python3.12 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m vjb daily      # fetch -> questions -> classify -> report
.venv/bin/python -m pytest tests
```

Open `out/site/index.html` through a local server (`python3 -m http.server -d out/site`), or
`out/index.html` directly, which has the data inlined.

| command | what |
|---|---|
| `fetch` | refresh every board in `companies.txt`. Known boards are fetched directly, new companies are probed on every ATS, and misses are re-probed weekly |
| `discover` | probe the largest H-1B filers that aren't in `companies.txt` yet, and append the ones with a public board |
| `questions` | Greenhouse application-form questions for a sample of US postings |
| `filings` | DOL spreadsheets in `data/raw/` to `data/filings/*.parquet` (quarterly, local only) |
| `classify` | rules plus LLM over all postings. Uses `ANTHROPIC_API_KEY` if set, otherwise the `claude` CLI; capped by `VJB_MAX_LLM_CALLS` |
| `report` | verdicts, `out/findings.json`, `out/index.html` (single file), and `out/site/` (deployable) |
| `daily` | fetch, questions, classify, report: what the scheduled job runs |
| `all` | `daily` plus `filings` |

Deploying: see [DEPLOY.md](DEPLOY.md).

## Layout

| path | what | committed |
|---|---|---|
| `companies.txt` | employers to track, with optional board slugs | yes |
| `data/aliases.json` | extra filer names for companies whose LCA name differs, written by `discover` | yes |
| `data/filings/` | LCA and PERM parquet built from the DOL files | yes, about 18 MB |
| `data/state/` | board lookup results, LLM results by text hash, sampled form questions | yes; the daily job updates it |
| `data/raw/` | DOL spreadsheets, downloaded by hand | no |
| `data/work/` | postings, classifications and raw board JSON for the current run | no |
| `out/` | build output | no |
| `assets/` | link-preview image `og.png`, rendered from `og-card.html` with headless Chrome | yes |
| `vjb/ats.py` | job-board fetchers, normalization, refresh logic, rate limiting | |
| `vjb/discover.py` | finds boards for large H-1B filers | |
| `vjb/roles.py` | title to role family and level; location to US or not | |
| `vjb/rules.py` | sponsorship regex rules and stance logic | |
| `vjb/llm.py` | batched, cached classification (Messages API or `claude -p`) | |
| `vjb/classify.py` | rules plus LLM over all postings | |
| `vjb/questions.py` | Greenhouse application-form questions | |
| `vjb/filings.py` | LCA / PERM loaders, employer-name matching | |
| `vjb/report.py` | verdicts, findings, board data, page and site build | |
| `vjb/page_template.html` | the page. `mode: "site"` fetches `data.json`; the artifact build inlines it | |

## Known gaps

- Only companies on the six supported job boards. Workday, iCIMS, Taleo and in-house career sites (most of
  big tech) have no documented public API and aren't covered.
- LCA counts show intent to file, not hires. One fiscal year's data at a time.
- Employer matching is name-based plus FEIN expansion. Check `names` in `findings.json` for a company
  before trusting its numbers.
- "Likely" means the posting is silent and the company files for that role type. It is a guess.
- Applicant outcome reports are the missing ground truth. The claude.ai artifact build has them; the
  public site has "Wrong verdict?" links to GitHub issues until reports get a backend.
