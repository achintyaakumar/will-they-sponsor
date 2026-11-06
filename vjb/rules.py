"""Regex rules that pull visa/sponsorship statements out of job-description text.

`analyze(text)` returns the visa-relevant sentences, a label -> sentences map, and
the relevant sentences no rule could interpret. `stance()` collapses labels into
one answer for a posting. Anything ambiguous is meant to go to the LLM pass.
"""
import re

from .roles import NON_US_RX

I = re.I

KEY = re.compile(
    r"sponsor|\bvisas?\b|immigration|h-?1-?b|authori[sz]ed to work|authori[sz]ation to work|work authori[sz]ation|"
    r"employment authori[sz]ation|legally (able|eligible|permitted|authori[sz]ed) to work|right to work|eligib\w* to work|"
    r"citizen|clearance|\bitar\b|export control|export administration|export licen[cs]e|u\.?\s?s\.?\s?persons?\b|green card|"
    r"permanent resident|\bopt\b|\bcpt\b|\bf-?1\b|e-?verify|work permit",
    I,
)
EEO = re.compile(
    r"equal (employment )?opportunit|without regard to|regardless of|discriminat|protected (veteran|class|characteristic|status)|"
    r"affirmative action|consider for employment qualified|arrest (and|or) conviction|fair chance|reasonable accommodation",
    I,
)
VISA_CTX = re.compile(
    r"\bvisas?\b|immigration|h-?1-?b|authori[sz]|work permit|employment|green card|\bopt\b|\bcpt\b|work in the|right to work",
    I,
)
NON_VISA_SPONSOR = re.compile(
    r"executive sponsor|clinical|\btrials?\b|pharma|\bevents?\b|conference|sponsored (content|ads?|posts?|listings?)|"
    r"stakeholder|employee resource|\bergs?\b|plan sponsor|401|retirement|pension|professional development|"
    r"(employer|company)[- ]sponsored|benefits? (plan|program)|brand|sponsorship (sales|deals?|partners?)|"
    r"sponsor(s|ing)? (and|&) partners|program sponsor|project sponsor|business sponsor|sponsored (by|events?|trips?)",
    I,
)
PREFERRED = re.compile(r"prefer|nice[- ]to[- ]have|bonus|\bplus\b|desired|desirable|ideal(ly)?|extra credit|differential|helpful", I)

NEG = r"(?:not|unable|cannot|can't|can not|won't|will not|do not|does not|don't|doesn't|no longer|aren't|are not|isn't|is not|without|never|n't|nor)"

R_DENY = [
    re.compile(rf"\b{NEG}\b(?:\W+\w+){{0,8}}?\W+(?:sponsor\w*|take over\W+(?:\w+\W+)?sponsorship)", I),
    re.compile(r"sponsorship\W+(?:\w+\W+){0,5}?(?:is |are |will be )?(?:not|unavailable|n/?a|none)\b", I),
    re.compile(r"\bno\W+(?:\w+\W+){0,3}?sponsorship", I),
    re.compile(r"not\W+(?:\w+\W+){0,3}?eligible for\W+(?:\w+\W+){0,3}?sponsorship", I),
    re.compile(r"visa sponsorship\s*[:\-]\s*no\b", I),
]
R_NEG_FAR = re.compile(rf"\b{NEG}\b(?:\W+\w+){{0,30}}?\W+sponsor", I)
R_FUTURE = re.compile(
    r"(authori[sz]ed|authori[sz]ation|eligible|permitted|able) to work\W+(?:\w+\W+){0,10}?"
    r"(now and in the future|now or in the future|on a permanent basis|permanently|indefinitely)", I)
R_UNRESTRICTED = re.compile(r"\b(unrestricted|without restrictions?|not restricted)\b", I)
R_HEDGE = re.compile(
    r"\b(every|all) (roles?|positions?|candidates?|cases?|jobs?|countr\w+|locations?|levels?|situations?)\b|"
    r"\bin (every|all) cases?\b|\bfor all\b|\bevery (role|candidate)\b|\bnot all\b|\bnot every\b|\bnot always\b|"
    r"\bcase[- ]by[- ]case\b|\bcertain (roles|positions)\b|\bsome (roles|positions)\b|\bnot guaranteed\b|\bgenerally\b", I)

R_OFFER = [
    re.compile(r"\b(?:we|company|team|employer|[A-Z][\w.&]+)\s+(?:do|does|will|can|may|might|offer\w*|provide\w*|support\w*|consider\w*|"
               r"(?:are|is) (?:able|happy|open|willing|pleased) to|(?:will|would) (?:consider|be happy to|be open to))\b"
               r"(?:\W+\w+){0,4}?\W+sponsor", I),
    re.compile(r"sponsorship\W+(?:\w+\W+){0,4}?(?:is |are |may be |can be |will be )?(?:available|offered|provided|possible|"
               r"supported|considered|an option)\b", I),
    re.compile(r"(?:visa|immigration|green card)\W+(?:\w+\W+){0,2}?(?:support|assistance|benefits?)\b", I),
    re.compile(r"(?:open|happy|willing|able) to\W+(?:\w+\W+){0,2}?sponsor", I),
    re.compile(r"sponsor\w*\W+(?:\w+\W+){0,2}?(?:for|of)\W+(?:h-?1-?b|visas?|green cards?|work visas?)", I),
    re.compile(r"visa sponsorship\s*[:\-]\s*(?:yes|available)\b", I),
]
R_OFFER_NO_WORD = re.compile(
    r"(?:get|obtain|secure) you a visa|help (?:you )?(?:with|obtain|secure|get) (?:a |your )?visa|retain an immigration (?:lawyer|attorney)|"
    r"immigration (?:lawyer|attorney|counsel) to help", I)
R_TRANSFER = re.compile(r"(h-?1-?b|visa)\W+(?:\w+\W+){0,2}?transfers?\b", I)
R_DUTIES = re.compile(r"\b(manage|managing|partner with|serve as|point of contact|administer|process(ing)?|coordinate|oversee)\b", I)

ABBR = r"(?<!\bU\.S\.)(?<!\bU\. S\.)(?<!\be\.g\.)(?<!\bi\.e\.)(?<!\bInc\.)(?<!\bNo\.)(?<!\bSt\.)(?<!\bvs\.)(?<!\bU\.S\.C\.)"
R_CITIZEN = [
    re.compile(r"(?:u\.?\s?s\.?|united states|american) citizen(?:ship)?\b(?:\W+\w+){0,10}?\W+(?:required|requirement|is a must|mandatory|only|necessary|needed)", I),
    re.compile(r"\b(?:must|required to|need to|should)\W+(?:\w+\W+){0,3}?(?:be|hold|have|possess)\W+(?:a |an )?(?:\(\w+\)\s*)?(?:u\.?\s?s\.?|united states) citizen", I),
    re.compile(r"\b(?:only|requires?|require|requiring)\W+(?:\w+\W+){0,2}?(?:u\.?\s?s\.?|united states) citizen", I),
    re.compile(r"\bcitizenship (?:is )?(?:required|mandatory)", I),
    re.compile(r"\b(?:u\.?\s?s\.?|united states) citizens? only\b", I),
]
R_CLEARANCE = [
    re.compile(r"(?:active|current|existing|ability to (?:obtain|get|acquire|secure)|able to (?:obtain|get|acquire|secure)|eligib\w+ (?:for|to obtain)|"
               r"obtain and maintain|obtaining and maintaining|maintain|hold|possess|qualify for|secure)\W+(?:\w+\W+){0,5}?(?:security )?clearance", I),
    re.compile(r"\b(?:secret|top secret|ts/sci|ts sci|ts)\W+(?:\w+\W+){0,2}?clearance", I),
    re.compile(r"clearance\W+(?:\w+\W+){0,4}?(?:required|is a must|mandatory|needed|essential)", I),
]
R_NOT_SECURITY_CLEARANCE = re.compile(r"background (check|clearance)|medical clearance|clearance (sale|rack)|drug|credit clearance|customs clearance", I)
R_USPERSON = [
    re.compile(r"u\.?\s?s\.?\s?persons?\b", I),
    re.compile(r"\bitar\b", I),
]
R_EXPORT_LICENSE = re.compile(r"export (?:control )?(?:licen[cs]e|authori[sz]ation)|deemed export|may (?:need|be required) to obtain", I)
R_EXPORT_CONTROLLED = re.compile(r"export[- ]controlled|export control (?:laws|regulations|compliance)|export administration regulations", I)
R_WORK_AUTH = re.compile(
    r"(?:authori[sz]ed|authori[sz]ation|eligible|legally (?:able|permitted)|permitted|right|entitled) to work(?! from)|"
    r"work authori[sz]ation|employment authori[sz]ation|work permit|right to work", I)
R_EVERIFY = re.compile(r"e-?verify", I)
R_EVERIFY_NEG = re.compile(rf"\b{NEG}\b(?:\W+\w+){{0,4}}?\W+(?:participate|use)\w*\W+(?:\w+\W+){{0,2}}?e-?verify", I)
R_OPT = re.compile(r"\b(?:stem opt|opt|cpt|f-?1)\b", I)

_SPLIT = re.compile(ABBR + r"(?<=[.!?])\s+(?=[A-Z(\"'*])")


HEADER_WORDS = re.compile(
    r"qualifications?|requirements?|responsibilities|about|what you|who you|benefits|preferred|nice[- ]to[- ]have|bonus|"
    r"you have|you will|you'll|minimum|basic|required|desired|skills|compensation|perks|why |the role|overview|"
    r"description|summary|eligibility|itar|export|visa|looking for|ideal|plus", I)


def _is_header(line: str) -> bool:
    if len(line) > 70 or line.endswith("."):
        return False
    return line.endswith(":") or (len(line.split()) <= 6 and line[:1].isupper() and bool(HEADER_WORDS.search(line))
                                  and not re.search(r"clearance|citizen|sponsor", line, I))


def sentences(text: str):
    """Yield (section_header, sentence) pairs."""
    out = []
    section = ""
    for line in (text or "").split("\n"):
        line = line.strip(" -•*\t·")
        if not line:
            continue
        if _is_header(line):
            section = line.rstrip(":")
        for s in _SPLIT.split(line):
            s = s.strip(" -•*\t·")
            if len(s) > 3:
                out.append((section, s))
    return out


def relevant_sentences(text: str):
    """Visa-relevant sentences. Preferred-qualification ones carry a '[preferred] ' prefix."""
    keep = []
    for section, s in sentences(text):
        if not KEY.search(s):
            continue
        has_sponsor = re.search(r"sponsor|visa|authori[sz]|h-?1-?b", s, I)
        if EEO.search(s) and not has_sponsor:
            continue
        if re.search(r"sponsor", s, I) and not re.search(r"\bvisas?\b|immigration|h-?1-?b|authori[sz]|work permit|green card", s, I) \
                and NON_VISA_SPONSOR.search(s):
            continue
        if re.search(r"\bcitizen", s, I) and not re.search(r"(u\.?\s?s\.?|united states|american) citizen|citizenship (is )?(required|mandatory)", s, I) \
                and not has_sponsor and not re.search(r"clearance|itar|person", s, I):
            continue
        if re.search(r"eligible to work from|work remotely from", s, I) and not has_sponsor:
            continue
        s = s[:600]
        if PREFERRED.search(section) and not re.search(r"sponsor|visa", s, I):
            s = "[preferred] " + s
        keep.append(s)
    return list(dict.fromkeys(keep))


def _about_non_us_only(s: str) -> bool:
    return bool(NON_US_RX.search(s)) and not re.search(r"\bU\.?\s?S\.?A?\b|United States|America", s)


def analyze_sentence(s: str):
    labels = set()
    if _about_non_us_only(s):
        return {"non_us"}
    preferred = s.startswith("[preferred] ") or bool(PREFERRED.search(s))

    restricted = set()
    if any(r.search(s) for r in R_CITIZEN):
        restricted.add("citizen")
    if any(r.search(s) for r in R_CLEARANCE) and not R_NOT_SECURITY_CLEARANCE.search(s):
        restricted.add("clearance")
    export_license = bool(R_EXPORT_LICENSE.search(s))
    if any(r.search(s) for r in R_USPERSON) and not export_license:
        restricted.add("us_person")
    if export_license:
        labels.add("export_license")
    elif R_EXPORT_CONTROLLED.search(s) and not restricted:
        labels.add("export_controlled")
    if restricted:
        labels |= {"clearance_preferred"} if preferred and restricted <= {"clearance"} else restricted

    # "without sponsorship for an export license" is about export controls, not visas
    sponsor_word = re.search(r"sponsor", s, I) and not export_license
    denied = bool(sponsor_word) and any(r.search(s) for r in R_DENY)
    if denied:
        labels.add("hedged_deny" if R_HEDGE.search(s) else "deny")
    elif sponsor_word and R_NEG_FAR.search(s):
        labels.add("hedged_deny")
    elif sponsor_word and any(r.search(s) for r in R_OFFER):
        labels.add("hedged_offer" if R_HEDGE.search(s) else "offer")
    elif R_OFFER_NO_WORD.search(s):
        labels.add("offer")
    if R_TRANSFER.search(s) and not R_DUTIES.search(s):
        if re.search(rf"\b{NEG}\b(?:\W+\w+){{0,6}}?\W+(?:transfer|take over)", s, I):
            labels.add("deny")
        else:
            labels.add("transfer")
    if R_WORK_AUTH.search(s):
        if R_FUTURE.search(s):
            labels.add("future_auth")
        elif R_UNRESTRICTED.search(s):
            labels.add("unrestricted_auth")
        elif not denied:
            labels.add("work_auth")
    if R_EVERIFY.search(s):
        labels.add("no_everify" if R_EVERIFY_NEG.search(s) else "everify")
    if R_OPT.search(s):
        labels.add("mentions_opt")
    return labels


def analyze(text: str):
    sents = relevant_sentences(text)
    by_label = {}
    unmatched = []
    for s in sents:
        labs = analyze_sentence(s)
        if not labs:
            unmatched.append(s)
        for l in labs:
            by_label.setdefault(l, []).append(s)
    return {"sentences": sents, "labels": by_label, "unmatched": unmatched}


STANCES = ["citizen_only", "no_sponsorship", "case_by_case", "sponsors", "transfer_only", "auth_required", "none"]


def stance(labels: dict) -> str:
    L = set(labels)
    if L & {"citizen", "clearance", "us_person"}:
        return "citizen_only"
    if "deny" in L or "future_auth" in L:
        if ("offer" in L or "hedged_offer" in L) and "transfer" in L:
            return "transfer_only"
        return "no_sponsorship"
    if "hedged_deny" in L or "hedged_offer" in L or ("offer" in L and "unrestricted_auth" in L):
        return "case_by_case"
    if "offer" in L:
        return "sponsors"
    if "transfer" in L:
        return "transfer_only"
    if "unrestricted_auth" in L:
        return "no_sponsorship"
    if "work_auth" in L:
        return "auth_required"
    return "none"


def is_ambiguous(result) -> bool:
    L = set(result["labels"])
    if result["unmatched"]:
        return True
    if ("deny" in L and "offer" in L) or L & {"hedged_deny", "hedged_offer", "unrestricted_auth", "transfer", "work_auth",
                                              "export_license", "export_controlled", "mentions_opt", "clearance_preferred"}:
        return True
    return False
