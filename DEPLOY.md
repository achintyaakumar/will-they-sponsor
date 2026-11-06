# Deploying the site

The site is static. A GitHub Actions job runs every morning: it fetches the job boards, classifies new
postings with Claude Haiku, rebuilds `out/site/`, commits the small caches in `data/state/`, and uploads
the site to Cloudflare Pages. Nothing runs on a server you manage.

You need three accounts, all free to start: GitHub, Cloudflare and the Anthropic API.

## 1. Set the commit email before the first commit

Every commit in a public repo shows its author email. Use your private GitHub address, set for this
repo only:

1. On GitHub, go to Settings → Emails, turn on "Keep my email addresses private", and copy the
   `…@users.noreply.github.com` address shown there.
2. Then:

```sh
cd ~/Repos/visa-job-board
git init -b main
git config user.name "Your Name"
git config user.email "12345678+yourname@users.noreply.github.com"
```

## 2. Create the repo and push

Create an empty **public** repo on GitHub (no README or license), for example `will-they-sponsor`.
Public repos get unlimited Actions minutes. Then:

```sh
git add -A
git status --short | grep -c .   # roughly 30 files; data/raw, data/work, out and .venv are ignored
git commit -m "Initial commit"
git remote add origin https://github.com/yourname/will-they-sponsor.git
git push -u origin main
```

The DOL spreadsheets in `data/raw/` stay on your machine. Only the parquet files built from them
(`data/filings/`, about 18 MB) are committed.

## 3. Get the keys

**Claude, either way:**
- *Your Claude subscription:* run `claude setup-token` in your own terminal and save the token as
  `CLAUDE_CODE_OAUTH_TOKEN`. The calls count against your plan's usage limits.
- *An API key:* create one at console.anthropic.com under API Keys and save it as `ANTHROPIC_API_KEY`.
  Under Billing, set a monthly spend limit; $10 is plenty.

Each daily run is capped at 80 model calls (`MAX_LLM_CALLS`). A typical day needs well under that.

**Cloudflare.** Sign up at cloudflare.com, then:
- Account ID: Workers & Pages → the Account ID in the right-hand column.
- API token: My Profile → API Tokens → Create Token → Create Custom Token. Under Permissions, add
  Account → Cloudflare Pages → Edit.

## 4. Add them to the repo

In the repo, go to Settings → Secrets and variables → Actions.

| Secret | Value |
|---|---|
| `CLAUDE_CODE_OAUTH_TOKEN` or `ANTHROPIC_API_KEY` | the subscription token or the API key |
| `CLOUDFLARE_API_TOKEN` | the Cloudflare token |
| `CLOUDFLARE_ACCOUNT_ID` | the account ID |

Optional variables, on the Variables tab:

| Variable | Default | What it does |
|---|---|---|
| `SITE_URL` | none | canonical URL for link previews, e.g. `https://willtheysponsor.com` |
| `CF_PAGES_PROJECT` | `will-they-sponsor` | Cloudflare Pages project name, which sets the `*.pages.dev` address |
| `MAX_LLM_CALLS` | `80` | cap on model calls per run |

## 5. First run

Go to Actions → daily → Run workflow. The first run creates the Cloudflare Pages project and deploys
it to `https://will-they-sponsor.pages.dev` (or your project name). After that it runs every day at
10:23 UTC.

Without the Cloudflare secrets the job still builds, and you can download the site from the run's
"site" artifact. Without either Claude secret it reuses cached classifications, and new postings keep
their rule-based verdict.

**Custom domain:** Workers & Pages → your project → Custom domains.

## Keeping it up to date

- **New H-1B data (quarterly).** DOL posts new LCA and PERM disclosure files every quarter at
  dol.gov/agencies/eta/foreign-labor/performance. Download them into `data/raw/`, then run:

  ```sh
  .venv/bin/python -m vjb filings
  git add data/filings && git commit -m "LCA FY2026 Q4" && git push
  ```

- **More companies.** Add a line to `companies.txt` (`Name` or `Name | board-slug`) and push; the next
  daily run probes it on every supported job board. After a filings update, `python -m vjb discover`
  finds the largest H-1B filers that have a public board and appends them.
- **Corrections.** Every posting has a "Wrong verdict?" link that opens a prefilled GitHub issue.
- **If the site stops updating.** GitHub pauses scheduled workflows in repos with no activity for 60
  days. The daily state commit should count as activity. If it doesn't, re-enable the workflow on the
  Actions tab.
