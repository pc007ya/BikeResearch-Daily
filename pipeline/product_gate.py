"""Cheap, title-led product gate: event and video coverage stays editorial news."""

import re

# Negative keywords indicating an article is NOT a complete bike review/launch
NON_BIKE_TITLE_RE = re.compile(
    r"\b(?:helmet|helm|headlamp|shorts|chamois|shoes?|goggles?|jacket|jersey|gloves?|"
    r"wheelset|wheels?\b|tire|tyre|reifen|motor\s+review|motor\s+test|autoshift|"
    r"airforce|trockenblasen|verkaufsstopp|rückruf|recall|giveaway|ps5|poll:|"
    r"slack\s+randoms|check\s+out:|geile\s+teile|bike\s+show|hallen|herbst-update|"
    r"transvienna|fast\s+forward\s+team|world\s+cup|tour\s+down\s+under|"
    r"rapencross|grand\s+tour|transfer|coach|nica\s+expands|menstrual|comeback|"
    r"upgrades?\s+unter|die\s+\d+\s+besten|top\s+\d+\s+upgrades?|best\s+upgrades?)\b",
    re.I,
)

# Positive indicators of a complete bicycle
BIKE_MODEL_HINTS_RE = re.compile(
    r"\b(?:tallboy|remote\s*160|g32\s*superfast|tambora|all-road\s*v2|rise\s*lt|"
    r"aventura|turbo\s*vado|rn0|ue\s*carbon|stumpjumper|levo|epic|tarmac|aethos|"
    r"fuel\s*ex|slash|madone|checkpoint|aeroad|spectral|strive|neuron|grail|grizl|"
    r"trance|reign|anthem|propel|defy|tcr|revolt|megatower|hightower|bronson|nomad|"
    r"heckler|bullit|valia|spark|genius|ransom|foil|addict|scalpel|supersix|topstone|"
    r"jekyll|habit|motera|sb140|sb160|switchblade|firebird|shuttle|spire|sentinel|"
    r"smuggler|relay|meta|clash|supreme|jeffsy|capra|decoy|izzo|sight|range|fluid|"
    r"altitude|instinct|slayer|powerplay|occam|oiz|orca|terra|stereo|crafty|"
    r"neat|dune|tyee|spindrift|ekan|jam²|sam²|thron²|s-works|roubaix|diverge|"
    r"gravel\s+bike|road\s+bike|mountain\s+bike|trail\s+bike|enduro\s+bike|"
    r"downhill\s+bike|all-road|suv\s+ebike|e-?mtb|e-?bike\s+review|carbon\s+pro\s+on\s+test)\b",
    re.I,
)

# Check event headings before the product lexical hints or feed taxonomy.
RACE_NEWS_TITLE_RE = re.compile(
    r"\b(?:prize[\s-]+purse|wild[\s-]+card|race[\s-]+results?|"
    r"qualif(?:y|ies|ied|ication)[\s-]+for)\b", re.I
)
VIDEO_NEWS_TITLE_RE = re.compile(r"^\s*(?:video|watch)\s*[:：]", re.I)

# High-confidence exact subjects, with punctuation and case normalization at display.
_PRODUCT_SIGNATURES = (
    (re.compile(r"\bStorck\s+Aerfast[.\s-]*5\s+Pro\b", re.I), ("Storck", "Aerfast.5 Pro")),
    (re.compile(r"\bOrbea\s+Wild(?:\s+(?:ST|FS|H[0-9]+|M[0-9]+|LTD|Team))*\b", re.I),
     ("Orbea", None)),
)


def subject_product(title):
    """Return an unambiguous brand and optional canonical model from the title."""
    for pattern, (brand, canonical_model) in _PRODUCT_SIGNATURES:
        match = pattern.search(title)
        if match:
            return brand, canonical_model or match.group()[len(brand):].strip()
    return None


def editorial_news_kind(title):
    if VIDEO_NEWS_TITLE_RE.search(title):
        return "video"
    if RACE_NEWS_TITLE_RE.search(title):
        return "race"
    return None


def is_complete_bike_article(item):
    title = item["title"]
    if editorial_news_kind(title) or NON_BIKE_TITLE_RE.search(title):
        return False
    if subject_product(title) or BIKE_MODEL_HINTS_RE.search(title):
        return True
    # RSS categories are only supporting evidence; don't count model hints from
    # arbitrary categories/body or treat the year by itself as product evidence.
    cats = " ".join(item.get("categories") or [])
    product_context = re.search(r"\b(?:gravel|mountain|road|trail|enduro|downhill)\s+bikes?\b|\be[- ]?bikes?\b", title, re.I)
    return bool(re.search(r"\b(?:gravel bikes|mountain bikes|road bikes|e-bikes|complete bikes)\b", cats, re.I)
                and product_context)
