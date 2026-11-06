"""Job title -> role family / seniority, and location -> US or not."""
import re

FAMILIES = ["software", "data_ml", "quant", "hardware", "product_design", "other"]

_RX = lambda p: re.compile(p, re.I)

QUANT = _RX(r"\bquant(itative)?\b|\btrader\b|\btrading\b(?!.*\b(sales|operations)\b)")
DATA_ML = _RX(
    r"\b(data scien\w*|machine learning|ml|ai research|research scientist|applied scientist|"
    r"research engineer|data engineer\w*|analytics engineer|data analyst|statistic\w*|"
    r"deep learning|computer vision|nlp|llm|perception|inference|ai engineer)\b"
)
HARDWARE = _RX(
    r"\b(mechanical|electrical|hardware|manufacturing|propulsion|avionics|gnc|rf|asic|fpga|"
    r"silicon|chip|pcb|thermal|structures|structural|materials|chemical|process|"
    r"test engineer|reliability|optical|optics|power electronics|battery|controls engineer|"
    r"systems engineer|aerospace|robotics engineer|firmware|embedded|analog|mixed[- ]signal|"
    r"verification|physical design|technician|machinist|welder|assembler)\b"
)
NON_SWE_ENGINEER = _RX(
    r"\b(sales|solutions?|support|customer|field|success|implementation|pre-?sales|"
    r"partner|account|deployment strategist|recruit\w*|sourcer)\b"
)
SOFTWARE = _RX(
    r"\b(software|swe|developer|engineer\w*|sre|devops|backend|back-end|frontend|front-end|"
    r"full[- ]?stack|ios|android|mobile|platform|infrastructure|security engineer|programmer|"
    r"architect|tech lead|technical staff)\b"
)
PRODUCT_DESIGN = _RX(r"\b(product manager|product management|program manager|designer|design|ux|ui|researcher)\b")

EARLY = _RX(
    r"\b(new grad\w*|new college grad\w*|university|campus|intern(ship)?s?|co-?op|early[- ]career|"
    r"entry[- ]level|graduate|junior|apprentice\w*|residency|resident|fellow(ship)?|"
    r"20(25|26|27) (start|grad\w*)|associate software|engineer i\b|software engineer 1\b|level 1\b)\b"
)
INTERN = _RX(r"\b(intern(ship)?s?|co-?op)\b")
SENIOR = _RX(r"\b(senior|sr\.?|staff|principal|lead|director|head of|vp|vice president|manager|distinguished|chief)\b")


def role_family(title: str) -> str:
    t = title or ""
    if QUANT.search(t):
        return "quant"
    if DATA_ML.search(t):
        return "data_ml"
    if HARDWARE.search(t) and not re.search(r"\bsoftware\b", t, re.I):
        return "hardware"
    if SOFTWARE.search(t) and not NON_SWE_ENGINEER.search(t):
        return "software"
    if PRODUCT_DESIGN.search(t):
        return "product_design"
    return "other"


def seniority(title: str) -> str:
    t = title or ""
    if INTERN.search(t):
        return "intern"
    if EARLY.search(t) and not SENIOR.search(t):
        return "early"
    if SENIOR.search(t):
        return "senior"
    return "mid"


# ---------------------------------------------------------------- location

STATES = (
    "AL AK AZ AR CA CO CT DE FL GA HI ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY "
    "NC ND OH OK OR PA RI SC SD TN TX UT VT VA WA WV WI WY DC"
).split()
STATE_NAMES = (
    "Alabama|Alaska|Arizona|Arkansas|California|Colorado|Connecticut|Delaware|Florida|Georgia|Hawaii|Idaho|"
    "Illinois|Indiana|Iowa|Kansas|Kentucky|Louisiana|Maine|Maryland|Massachusetts|Michigan|Minnesota|"
    "Mississippi|Missouri|Montana|Nebraska|Nevada|New Hampshire|New Jersey|New Mexico|New York|"
    "North Carolina|North Dakota|Ohio|Oklahoma|Oregon|Pennsylvania|Rhode Island|South Carolina|South Dakota|"
    "Tennessee|Texas|Utah|Vermont|Virginia|Washington|West Virginia|Wisconsin|Wyoming"
)
US_CITIES = (
    "San Francisco|SF|Bay Area|New York|NYC|Brooklyn|Manhattan|Seattle|Bellevue|Redmond|Kirkland|Austin|Boston|"
    "Cambridge, MA|Chicago|Los Angeles|LA|Santa Monica|Culver City|Irvine|San Diego|Denver|Boulder|Atlanta|"
    "Washington, D\\.?C|Washington DC|Arlington|Reston|McLean|Palo Alto|Mountain View|Menlo Park|Sunnyvale|"
    "San Jose|Santa Clara|San Mateo|Redwood City|Foster City|South San Francisco|Oakland|Berkeley|Emeryville|"
    "Pittsburgh|Philadelphia|Miami|Salt Lake City|Lehi|Provo|Draper|Phoenix|Tempe|Scottsdale|Dallas|Houston|"
    "Portland|Minneapolis|Detroit|Ann Arbor|Raleigh|Durham|Nashville|Columbus|Hawthorne|El Segundo|Long Beach|"
    "Torrance|Costa Mesa|Huntsville|Cape Canaveral|Starbase|Mojave|McGregor|Fremont|Livermore|Pleasanton|"
    "Waltham|Somerville|Stamford|Greenwich|Jersey City|Hoboken|Princeton|Baltimore|Orlando|Tampa|St\\. Louis|"
    "Kansas City|Indianapolis|Madison|Charlotte|Richmond|Sacramento|Las Vegas|Reno|Albuquerque|Honolulu|Plano"
)
NON_US = (
    "Canada|Toronto|Vancouver|Montreal|Ontario|British Columbia|Quebec|UK|United Kingdom|London|England|Ireland|"
    "Dublin|Germany|Berlin|Munich|France|Paris|Netherlands|Amsterdam|Spain|Madrid|Barcelona|Portugal|Lisbon|"
    "Poland|Warsaw|Krakow|Sweden|Stockholm|Switzerland|Zurich|Israel|Tel Aviv|India|Bangalore|Bengaluru|"
    "Hyderabad|Pune|Mumbai|Delhi|Gurgaon|Gurugram|Chennai|Noida|Singapore|Japan|Tokyo|Australia|Sydney|"
    "Melbourne|Brazil|S[aã]o Paulo|Mexico|Mexico City|Argentina|Buenos Aires|Colombia|Bogot[aá]|Korea|Seoul|"
    "China|Shanghai|Beijing|Hong Kong|Taiwan|Taipei|Philippines|Manila|Estonia|Romania|Serbia|Ukraine|"
    "Czech|Prague|Denmark|Copenhagen|Norway|Oslo|Finland|Helsinki|Italy|Milan|Belgium|Brussels|Austria|Vienna|"
    "EMEA|APAC|LATAM|Europe|Costa Rica|Chile|Peru|Egypt|Nigeria|Kenya|South Africa|UAE|Dubai|Saudi|Vietnam|"
    "Thailand|Indonesia|Malaysia|New Zealand|Greece|Hungary|Budapest|Lithuania|Latvia|Bulgaria|Croatia"
)

US_RX = re.compile(
    rf"(United States|\bU\.?S\.?A?\b|\bUSA\b|Americas?\b(?! ?latin)|\bNorth America\b|\b({STATE_NAMES})\b|"
    rf"\b({US_CITIES})\b|,\s*({'|'.join(STATES)})\b)",
)
NON_US_RX = re.compile(rf"\b({NON_US})\b")
US_COUNTRY = {"us", "usa", "united states", "united states of america", "u.s."}


def is_us(locations, countries=()) -> bool | None:
    """True if any listed location is in the US, False if all are clearly elsewhere, None if unknown."""
    if countries:
        if any(c.strip().lower() in US_COUNTRY for c in countries):
            return True
    pieces = []
    for loc in locations or []:
        pieces += [p.strip() for p in re.split(r"[;|/]| or |•", loc) if p.strip()]
    if not pieces:
        return False if countries else None
    verdicts = []
    for p in pieces:
        us = bool(US_RX.search(p))
        non_us = bool(NON_US_RX.search(p))
        if us and not non_us:
            return True
        if us and non_us:
            # "Remote - US or Canada", "Toronto, CA" style ambiguity: trust explicit country words
            if re.search(r"United States|\bUSA?\b", p):
                return True
            verdicts.append(False)
        elif non_us:
            verdicts.append(False)
        else:
            verdicts.append(None)
    if all(v is False for v in verdicts):
        return False
    return None
