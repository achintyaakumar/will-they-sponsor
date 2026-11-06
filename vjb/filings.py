"""Load DOL LCA disclosure files and USCIS H-1B Employer Data Hub files from data/raw/,
and match employer names to the companies on our job boards."""
import json
import re
from pathlib import Path

import pandas as pd

from . import paths
from .roles import role_family

LCA_COLS = {
    "case_status": ["CASE_STATUS"],
    "visa_class": ["VISA_CLASS"],
    "received_date": ["RECEIVED_DATE"],
    "decision_date": ["DECISION_DATE"],
    "employer": ["EMPLOYER_NAME"],
    "dba": ["TRADE_NAME_DBA"],
    "employer_state": ["EMPLOYER_STATE"],
    "fein": ["EMPLOYER_FEIN"],
    "job_title": ["JOB_TITLE"],
    "soc_code": ["SOC_CODE"],
    "soc_title": ["SOC_TITLE"],
    "worksite_city": ["WORKSITE_CITY", "WORKSITE_CITY_1"],
    "worksite_state": ["WORKSITE_STATE", "WORKSITE_STATE_1"],
    "positions": ["TOTAL_WORKER_POSITIONS", "TOTAL_WORKERS"],
    "new_employment": ["NEW_EMPLOYMENT"],
    "continued": ["CONTINUED_EMPLOYMENT"],
    "change_previous": ["CHANGE_PREVIOUS_EMPLOYMENT"],
    "concurrent": ["NEW_CONCURRENT_EMPLOYMENT", "NEW_CONCURRENT_EMP"],
    "change_employer": ["CHANGE_EMPLOYER"],
    "amended": ["AMENDED_PETITION"],
    "wage_from": ["WAGE_RATE_OF_PAY_FROM", "WAGE_RATE_OF_PAY_FROM_1"],
    "wage_unit": ["WAGE_UNIT_OF_PAY", "WAGE_UNIT_OF_PAY_1"],
    "pw": ["PREVAILING_WAGE", "PREVAILING_WAGE_1"],
    "pw_unit": ["PW_UNIT_OF_PAY", "PW_UNIT_OF_PAY_1"],
    "pw_level": ["PW_WAGE_LEVEL", "PW_WAGE_LEVEL_1"],
}
LCA_REQUIRED = ["case_status", "visa_class", "employer", "job_title"]
NUMERIC = ["positions", "new_employment", "continued", "change_previous", "concurrent", "change_employer", "amended", "wage_from", "pw"]
ANNUAL = {"Year": 1, "Month": 12, "Bi-Weekly": 26, "Week": 52, "Hour": 2080}


def _stream_xlsx(path: Path, spec, required=()):
    """Read only the needed columns of a big single-sheet xlsx, row by row."""
    from python_calamine import CalamineWorkbook
    wb = CalamineWorkbook.from_path(str(path))
    rows = wb.get_sheet_by_name(wb.sheet_names[0]).iter_rows()
    header = [str(h).strip() for h in next(rows)]
    cols = _resolve(header, spec)
    missing = [k for k in required if k not in cols]
    if missing:
        raise ValueError(f"{path.name}: missing columns {missing}; got {header[:40]}")
    idx = {k: header.index(v) for k, v in cols.items()}
    data = {k: [] for k in idx}
    for r in rows:
        for k, i in idx.items():
            v = r[i] if i < len(r) else None
            data[k].append(None if v == "" else str(v))
    return pd.DataFrame(data)


def _resolve(columns, spec):
    upper = {str(c).strip().upper(): c for c in columns}
    out = {}
    for key, names in spec.items():
        for n in names:
            if n in upper:
                out[key] = upper[n]
                break
    return out


def load_lca_file(path: Path) -> pd.DataFrame:
    print(f"filings: reading {path.name} ...", flush=True)
    if path.suffix.lower() in (".xlsx", ".xls"):
        df = _stream_xlsx(path, LCA_COLS, LCA_REQUIRED)
    else:
        head = pd.read_csv(path, nrows=0)
        cols = _resolve(head.columns, LCA_COLS)
        df = pd.read_csv(path, usecols=list(cols.values()), dtype=str, low_memory=False)
        df = df.rename(columns={v: k for k, v in cols.items()})
    for k in LCA_COLS:
        if k not in df:
            df[k] = None
    for k in NUMERIC:
        df[k] = pd.to_numeric(df[k].astype(str).str.replace(r"[$,]", "", regex=True), errors="coerce")
    for k in ("received_date", "decision_date"):
        df[k] = pd.to_datetime(df[k], errors="coerce")
    df["source"] = path.name
    return df[list(LCA_COLS) + ["source"]]


PERM_COLS = {
    "case_status": ["CASE_STATUS"],
    "decision_date": ["DECISION_DATE"],
    "employer": ["EMP_BUSINESS_NAME", "EMPLOYER_NAME"],
    "fein": ["EMP_FEIN", "EMPLOYER_FEIN"],
    "payroll": ["EMP_NUM_PAYROLL", "EMPLOYER_NUM_EMPLOYEES"],
    "job_title": ["JOB_TITLE"],
    "soc_code": ["PWD_SOC_CODE"],
    "worksite_city": ["PRIMARY_WORKSITE_CITY", "WORKSITE_CITY"],
    "worksite_state": ["PRIMARY_WORKSITE_STATE", "WORKSITE_STATE"],
    "wage_from": ["JOB_OPP_WAGE_FROM", "WAGE_OFFER_FROM"],
    "wage_unit": ["JOB_OPP_WAGE_PER", "WAGE_OFFER_UNIT_OF_PAY"],
}


def load_perm_file(path: Path) -> pd.DataFrame:
    print(f"filings: reading {path.name} ...", flush=True)
    df = _stream_xlsx(path, PERM_COLS, ["employer", "case_status"])
    for k in PERM_COLS:
        if k not in df:
            df[k] = None
    for k in ("payroll", "wage_from"):
        df[k] = pd.to_numeric(df[k], errors="coerce")
    df["decision_date"] = pd.to_datetime(df["decision_date"], errors="coerce")
    df["source"] = path.name
    return df[list(PERM_COLS) + ["source"]]


def load_uscis_file(path: Path) -> pd.DataFrame:
    raw = path.read_bytes()[:4]
    if raw.startswith(b"\xff\xfe") or raw.startswith(b"\xfe\xff"):
        df = pd.read_csv(path, encoding="utf-16", sep="\t", dtype=str)
    else:
        df = pd.read_csv(path, dtype=str, sep=None, engine="python")
    df.columns = [re.sub(r"\s+", " ", str(c)).strip().lower() for c in df.columns]

    def col(*needles):
        for c in df.columns:
            if all(n in c for n in needles):
                return c
        return None

    out = pd.DataFrame({
        "fiscal_year": df[col("fiscal year")] if col("fiscal year") else None,
        "employer": df[col("employer")] if col("employer") else df[col("petitioner", "name")],
        "state": df[col("state")] if col("state") else None,
        "city": df[col("city")] if col("city") else None,
    })
    groups = {
        "new_approval": [("initial approval",), ("new employment approval",)],
        "new_denial": [("initial denial",), ("new employment denial",)],
        "continuing_approval": [("continuing approval",), ("continuation approval",)],
        "change_employer_approval": [("change of employer approval",)],
    }
    for key, alts in groups.items():
        c = next((col(*a) for a in alts if col(*a)), None)
        out[key] = pd.to_numeric(df[c].str.replace(",", ""), errors="coerce").fillna(0) if c else 0
    out["source"] = path.name
    return out


def build():
    lca_files = sorted(p for p in paths.RAW.iterdir() if re.search(r"lca", p.name, re.I) and p.suffix.lower() in (".xlsx", ".csv"))
    perm_files = sorted(p for p in paths.RAW.iterdir() if re.search(r"perm", p.name, re.I) and p.suffix.lower() == ".xlsx")
    uscis_files = sorted(p for p in paths.RAW.iterdir() if re.search(r"h1b|h-1b|datahub|data_hub|employer", p.name, re.I)
                         and p.suffix.lower() in (".csv", ".txt") and p not in lca_files)
    if not lca_files and not uscis_files and not perm_files:
        print(f"filings: nothing in {paths.RAW} yet (expecting LCA_Disclosure_Data_FY*.xlsx and/or a USCIS data hub CSV)")
        return
    if lca_files:
        df = pd.concat([load_lca_file(p) for p in lca_files], ignore_index=True)
        n0 = len(df)
        df = df[df["visa_class"].str.upper().str.strip() == "H-1B"]
        df = df[df["case_status"].str.lower().str.startswith("certified")]
        df = df.drop_duplicates()
        df["family"] = df["job_title"].fillna("").map(role_family)
        df["annual_wage"] = df["wage_from"] * df["wage_unit"].map(ANNUAL).fillna(1)
        df.to_parquet(paths.LCA, index=False)
        print(f"filings: {n0} LCA rows -> {len(df)} certified H-1B rows -> {paths.LCA}")
    if perm_files:
        pm = pd.concat([load_perm_file(p) for p in perm_files], ignore_index=True)
        pm = pm[pm["case_status"].str.lower().str.startswith("certified")]
        pm["family"] = pm["job_title"].fillna("").map(role_family)
        pm.to_parquet(paths.PERM, index=False)
        print(f"filings: {len(pm)} certified PERM rows -> {paths.PERM}")
    if uscis_files:
        u = pd.concat([load_uscis_file(p) for p in uscis_files], ignore_index=True)
        u.to_parquet(paths.USCIS, index=False)
        print(f"filings: {len(u)} USCIS data hub rows -> {paths.USCIS}")


# ---------------------------------------------------------------- employer matching

SUFFIX = {"INC", "INCORPORATED", "LLC", "L L C", "CORP", "CORPORATION", "CO", "COMPANY", "LTD", "LIMITED", "LP", "LLP",
          "PBC", "PC", "PLLC", "THE", "AND", "OF", "USA", "US", "NA"}
ALLOWED_TAIL = {
    "MARKETS", "OPCO", "SECURITIES", "CAPITAL", "INVESTMENTS", "TECHNOLOGIES", "TECHNOLOGY", "LABS", "LAB", "SOFTWARE",
    "SYSTEMS", "INDUSTRIES", "HOLDINGS", "AMERICA", "AMERICAS", "SERVICES", "PLATFORMS", "PLATFORM", "INTERACTIVE",
    "GAMES", "HEALTH", "AI", "INTERNET", "FINANCIAL", "PAYMENTS", "NETWORKS", "DATA", "CLOUD", "INNOVATION", "ROBOTICS",
    "AVIATION", "AEROSPACE", "MOTORS", "BIO", "BIOWORKS", "THERAPEUTICS", "PHARMACEUTICALS", "ENTERPRISE", "ENTERPRISES",
    "MEDIA", "DIGITAL", "COMMERCE", "OPERATIONS", "OPERATING", "MANAGEMENT", "TRADING", "INTERNATIONAL", "GLOBAL",
    "SOLUTIONS", "WORKS", "TECH", "ENERGY", "MATERIALS", "SPACE", "SECURITY", "INTELLIGENCE", "RESEARCH", "MOBILE",
    "FOUNDATION", "GROUP", "AUTOMATION", "INDUSTRIES", "HQ", "NORTH", "ENGINEERING", "MANUFACTURING", "CONSUMER",
}
TAIL_BLOCK = {"GROUP"}  # "Compass Group", "Box Group": only for multi-word company names
ALIASES = {
    "SpaceX": ["SPACE EXPLORATION TECHNOLOGIES"],
    "Cursor": ["ANYSPHERE"],
    "Lucid Motors": ["LUCID USA", "ATIEVA USA", "ATIEVA"],
    "Ro": ["ROMAN HEALTH VENTURES"],
    "Character.AI": ["CHARACTER TECHNOLOGIES"],
    "The New York Times": ["NEW YORK TIMES"],
    "Twitch": ["TWITCH INTERACTIVE"],
    "Jane Street": ["JANE STREET CAPITAL", "JANE STREET GROUP"],
    "IMC Trading": ["IMC FINANCIAL MARKETS", "IMC AMERICAS"],
    "Hudson River Trading": ["HUDSON RIVER TRADING"],
    "Wikimedia": ["WIKIMEDIA FOUNDATION"],
    "Mozilla": ["MOZILLA"],
    "Cognition": ["COGNITION AI"],
    "Glean": ["GLEAN TECHNOLOGIES"],
    "Anduril": ["ANDURIL INDUSTRIES"],
    "Toast": ["TOAST"],
    "Hex": ["HEX TECHNOLOGIES"],
    "Modal": ["MODAL LABS"],
    "Linear": ["LINEAR ORBIT"],
    "Notion": ["NOTION LABS"],
    "Runway": ["RUNWAY AI"],
    "Writer": ["WRITER"],
    "Sierra": ["SIERRA TECHNOLOGIES"],
    "Persona": ["PERSONA IDENTITIES"],
    "Unit": ["UNIT FINANCE"],
    "Alloy": ["ALLOY LABS"],
    "Island": ["ISLAND TECHNOLOGY"],
    "Color": ["COLOR HEALTH"],
    "Render": ["RENDER SERVICES"],
    "Docker": ["DOCKER"],
    "Redis": ["REDIS"],
    "Snap": ["SNAP"],
    "Ramp": ["RAMP BUSINESS"],
    "Mercury": ["MERCURY TECHNOLOGIES"],
    "Circle": ["CIRCLE INTERNET FINANCIAL", "CIRCLE INTERNET MANAGEMENT SERVICES"],
    "CircleCI": ["CIRCLE INTERNET SERVICES"],
    "Instacart": ["MAPLEBEAR"],
    "Sentry": ["FUNCTIONAL SOFTWARE"],
    "Airtable": ["FORMAGRID"],
    "ClickUp": ["MANGO TECHNOLOGIES"],
    "1Password": ["AGILEBITS"],
    "Faire": ["FAIRE WHOLESALE"],
    "GOAT": ["GOAT GROUP"],
    "SoFi": ["SOCIAL FINANCE"],
    "Carta": ["ESHARES"],
    "Grafana Labs": ["RAINTANK"],
    "Miro": ["REALTIMEBOARD"],
    "LaunchDarkly": ["CATAMORPHIC"],
    "Lattice": ["DEGREE"],
    "Together AI": ["TOGETHER COMPUTER"],
    "ElevenLabs": ["ELEVEN LABS"],
    "Gopuff": ["GOBRANDS"],
    "Acorns": ["ACORNS GROW"],
    "Elastic": ["ELASTICSEARCH"],
    "Oscar Health": ["OSCAR MANAGEMENT", "OSCAR INSURANCE"],
    "Point72": ["POINT72 ASSET MANAGEMENT", "POINT72"],
    "Physical Intelligence": ["PHYSICAL INTELLIGENCE"],
    "Cohere": ["COHERE", "COHERE TECHNOLOGIES"],
    "Harvey": ["HARVEY AI", "COUNSEL AI"],
    "Codeium": ["EXAFUNCTION"],
    "Teleport": ["GRAVITATIONAL"],
    "Turso": ["CHISELSTRIKE"],
    "Dagster": ["ELEMENTL", "DAGSTER LABS"],
    "incident.io": ["INCIDENT IO"],
    "Millennium": ["MILLENNIUM MANAGEMENT"],
    "Bosch": ["ROBERT BOSCH"],
    "Zeta": ["ZETA GLOBAL"],
    "Visa": ["VISA", "VISA TECHNOLOGY OPERATIONS"],
    "Balyasny": ["BALYASNY ASSET MANAGEMENT"],
    "Virtu Financial": ["VIRTU AMERICAS", "VIRTU FINANCIAL"],
    "AQR": ["AQR CAPITAL MANAGEMENT"],
    "Unity": ["UNITY TECHNOLOGIES", "UNITY SOFTWARE"],
    "Susquehanna International Group": ["SUSQUEHANNA INTERNATIONAL GROUP"],
    "Tower Research Capital": ["TOWER RESEARCH CAPITAL"],
    "Schonfeld": ["SCHONFELD STRATEGIC ADVISORS"],
    "Squarepoint Capital": ["SQUAREPOINT OPS", "SQUAREPOINT CAPITAL"],
    "Arrowstreet Capital": ["ARROWSTREET CAPITAL"],
    "Headlands Technologies": ["HEADLANDS TECHNOLOGIES"],
    "Watershed": ["WATERSHED TECHNOLOGY"],
    "Public": ["PUBLIC HOLDINGS"],
    "Column": ["COLUMN NATIONAL ASSOCIATION"],
    "Increase": ["INCREASE TECHNOLOGIES"],
    "Alpaca": ["ALPACADB", "ALPACA SECURITIES"],
    "Remote": ["REMOTE TECHNOLOGY"],
    "Gemini": ["GEMINI TRUST"],
    "Weave": ["WEAVE COMMUNICATIONS"],
    "Recursion": ["RECURSION PHARMACEUTICALS", "RECURSION TECHNOLOGIES"],
    "Brex": ["BREX"],
    "Plaid": ["PLAID"],
    "Lambda": ["LAMBDA"],
    "Abridge": ["ABRIDGE AI"],
    "Decagon": ["DECAGON AI"],
    "Astranis": ["ASTRANIS SPACE TECHNOLOGIES"],
    "Archer Aviation": ["ARCHER AVIATION"],
    "Zipline": ["ZIPLINE INTERNATIONAL"],
    "Aurora": ["AURORA OPERATIONS", "AURORA INNOVATION"],
    "Lucid Software": ["LUCID SOFTWARE"],
    "Calm": ["CALM COM"],
}
# short/common names: match only the aliases above, exactly
# aliases found by `python -m vjb discover`, kept as data so the scheduled job never edits code
ALIASES_FILE = paths.ROOT / "data" / "aliases.json"
if ALIASES_FILE.exists():
    for _c, _names in json.loads(ALIASES_FILE.read_text()).items():
        ALIASES.setdefault(_c, [])
        ALIASES[_c] += [n for n in _names if n not in ALIASES[_c]]

EXACT_ONLY = {"Bosch", "Zeta", "Visa", "Mercury", "Unit", "Alloy", "Persona", "Cohere", "Harvey", "Sierra", "Modal", "Gemini", "Writer", "Hex", "Lambda",
              "Ro", "Calm", "Color", "Island", "Render", "Linear", "Notion", "Runway", "Circle", "Ramp", "Toast", "Lucid Motors",
              "Docker", "Redis", "Snap", "Weave", "Wiz", "Box", "Cognition", "Glean", "Decagon", "Abridge", "Figure AI", "Hinge",
              "Public", "Current", "Dave", "Column", "Increase", "Pipe", "Rho", "Atomic", "Alpaca", "Bolt", "Pilot", "Digits", "Phantom",
              "Socket", "Neon", "Convex", "Clerk", "Railway", "Magic", "Factory", "Lindy", "Warp", "Chroma", "Gamma", "Clay", "Mercor",
              "Turing", "Vast", "Span", "Twelve", "Arcadia", "Watershed", "Apex Space", "Albedo", "Nuna", "Alma", "Headway", "Cerebral",
              "Grail", "Asimov", "Nav", "Homie", "Pattern", "Canopy", "Route", "Neighbor", "Divvy", "Coda", "Pitch", "Mural", "Framer",
              "Gem", "Remote", "Medium", "Quora", "Sleeper", "Underdog", "Rover", "Turo", "Harness", "Observe", "Depot", "Prisma",
              "Resend", "ReadMe", "Stainless", "Speakeasy", "Torq", "Panther", "Coalition", "Sardine", "Footprint", "Unity", "Census",
              "Prefect", "Atlan", "Tecton", "Millennium", "Balyasny", "AQR", "Kong", "Galileo Health", "Harmonic", "Magic", "Graphite",
              "Vellum", "Braintrust", "Adept", "Imbue", "Suno", "Pika", "Gamma", "Clay", "Writer", "Etched", "Rivos", "Highnote", "Lithic",
              "Orum", "Moov", "Earnest", "Varo", "Upwind", "Sysdig", "Tines", "Middesk", "Census", "Hightouch", "Materialize", "Ashby",
              "Greenhouse Software", "Patreon", "Substack", "Scopely", "Bungie", "Kalshi", "Polymarket", "Instawork", "Glossier",
              "Grailed", "Lendio", "Owlet", "Entrata", "Filevine", "Awardco", "Ancestry", "Dexterity", "Aeva", "Ouster", "Gatik", "Waabi",
              "Motional", "Wayve", "Oklo", "Saildrone", "Epirus", "Castelion", "Inceptive", "Freenome", "Enveda", "Dyno Therapeutics"}
# names that would match the wrong company by prefix
BLOCK = {"COMPASS GROUP", "SIERRA NEVADA", "CIRCLE K", "LINEAR TECHNOLOGY", "BOX HILL", "TOAST ITALIA", "RAMP RATE"}


def norm(name: str) -> str:
    s = str(name or "").upper().replace("&", " AND ")
    s = re.sub(r"\bL\.\s?L\.\s?[CP]\b\.?|\bL\.\s?P\b\.?|\bP\.\s?C\b\.?|\bN\.\s?A\b\.?|\bU\.\s?S\.(?:\s?A\b\.?)?", lambda m: re.sub(r"[.\s]", "", m.group(0)), s)
    s = re.sub(r"[^A-Z0-9 ]", " ", s)
    toks = [t for t in s.split() if t not in SUFFIX]
    return " ".join(toks)


def match_employers(companies, employer_names):
    """Return {company: set(raw employer names)}."""
    by_norm = {}
    for raw in employer_names:
        by_norm.setdefault(norm(raw), set()).add(raw)
    norms = list(by_norm)
    out = {}
    for c in companies:
        exact_only = c in EXACT_ONLY
        aliases = {norm(a) for a in ALIASES.get(c, [])}
        targets = (aliases or {norm(c)}) if exact_only else aliases | {norm(c)}
        targets.discard("")
        hits = set()
        for n in norms:
            if any(n.startswith(b) for b in BLOCK):
                continue
            for t in targets:
                if n == t:
                    hits |= by_norm[n]
                elif not exact_only and n.startswith(t + " "):
                    tail = set(n[len(t) + 1:].split())
                    if tail <= ALLOWED_TAIL and (len(t.split()) > 1 or not tail & TAIL_BLOCK):
                        hits |= by_norm[n]
        out[c] = hits
    return out


def expand_by_fein(matches, df):
    """Add every employer-name spelling that shares a FEIN with an already-matched name."""
    if "fein" not in df:
        return matches
    pairs = df[["employer", "fein"]].dropna().drop_duplicates()
    fein_of = pairs.groupby("employer")["fein"].agg(set).to_dict()
    names_of = pairs.groupby("fein")["employer"].agg(set).to_dict()
    taken = {n for names in matches.values() for n in names}
    out = {}
    for c, names in matches.items():
        feins = set().union(*(fein_of.get(n, set()) for n in names)) if names else set()
        extra = set().union(*(names_of.get(f, set()) for f in feins)) if feins else set()
        out[c] = names | (extra - taken)
    return out
