"""Contextual claim analysis for event-based surveillance.

For each document this produces an *interpretable* assessment:

* what is claimed (claim type), when it is said to have happened, where;
* whether the speaker is reporting first-hand, repeating someone, joking,
  debunking, or relaying an official statement;
* the evidence features behind each decision (negation, hedging, laboratory
  mention, alternative explanations such as cholera or malaria, staleness cues);
* whether human review is required.

Preparedness news ("Sierra Leone heightens Ebola surveillance after Kenya
cases") is surveillance activity in the country that prepares, not a case
claim there; and a place named only as a border ("near the CAR border") is not
where the cases are, nor is a country a case travelled from or through.

Outputs are categorical with reasons, not pseudo-probabilities. Keyword hits
alone never produce an Ebola claim: "several people are ill" without Ebola or
haemorrhagic-fever context is classified as an illness cluster with
alternative explanations considered, and "it is not Ebola" is a negation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, timedelta

from ..domain.enums import ClaimType, ReportKind, SourceCategory
from ..parsing.textnum import NUM_PATTERN, find_dates, parse_number
from .gazetteer import Gazetteer, load_gazetteer
from .langid import LanguageGuess, identify
from .lexicon import Language, fold_text, load_languages

# Raising it makes the pipeline re-analyse the documents of the last 60 days.
CLASSIFIER_VERSION = "2"
YEAR_RE = re.compile(r"\b(19[89]\d|20[0-4]\d)\b")
NEG_WINDOW = 40


@dataclass
class ClaimAnalysis:
    languages: list[LanguageGuess]
    claim_type: ClaimType
    report_kind: ReportKind
    relevance: str  # likely | ambiguous | unlikely
    event_date: date | None
    event_date_basis: str | None
    region_code: str | None
    region_level: int | None
    counts: dict[str, int]
    features: dict
    concepts: list[str]
    needs_review: bool
    review_reasons: list[str]
    translation_quality: str
    stale_indicators: list[str] = field(default_factory=list)


def _hits(langs: dict[str, Language], active: set[str], concept: str, folded: str) -> list[tuple[str, str]]:
    """Matches for a concept. Draft/low-support lexicons only count when that
    language was identified in the text (short words collide across languages)."""
    out = []
    for code, lang in langs.items():
        if code not in active and (lang.requires_review and concept != "ebola"):
            continue
        out.extend((code, t) for t in lang.match(concept, folded))
    return out


def _spans(langs: dict[str, Language], active: set[str], concept: str, folded: str) -> list[tuple[int, int]]:
    spans = []
    for code, lang in langs.items():
        if code not in active and (lang.requires_review and concept != "ebola"):
            continue
        spans.extend(lang.match_spans(concept, folded))
    return spans


_COUNT_DEATH = re.compile(rf"(?P<n>{NUM_PATTERN})\s+(?:\w+\s+){{0,2}}(?:people\s+)?(?:died|dead|deaths|morts|décès|décédés|wamekufa|vifo|bakufi|mortes|óbitos|morreram)", re.I)
_COUNT_DEATH_SW = re.compile(rf"(?:vifo|wamekufa|wafu|bakufi|bato)\s+(?:\w+\s+){{0,1}}(?P<n>{NUM_PATTERN})", re.I)
_ORDINAL_CASE = re.compile(
    r"\b(?P<o>first|second|third|fourth|fifth|premier|premi[eè]re|deuxi[eè]me|second|troisi[eè]me|quatri[eè]me)\s+(?:\w+\s+){0,2}?(?:confirmed\s+)?(?:case|cas)\b"
    r"|(?P<a>ثاني|الثانية|الثاني|ثالث|الثالثة)\s+(?:حالة|إصابة)", re.I)
_ORDINALS = {"first": 1, "premier": 1, "premiere": 1, "première": 1, "second": 2, "deuxieme": 2, "deuxième": 2, "third": 3,
             "troisieme": 3, "troisième": 3, "fourth": 4, "quatrieme": 4, "quatrième": 4, "fifth": 5,
             "ثاني": 2, "الثانية": 2, "الثاني": 2, "ثالث": 3, "الثالثة": 3}
_COUNT_ILL = re.compile(rf"(?P<n>{NUM_PATTERN})\s+(?:\w+\s+){{0,2}}(?:sick|ill|cases|malades|cas|wagonjwa|visa|doentes|casos|patients)", re.I)
# A case or test result being mentioned (on folded text), to tell where the cases are in preparedness news
_CASE_MENTION = re.compile(r"\b(?:cases?|patients?|infections?|infected|tested positive|tests? positive|cas|casos?|kisa|visa|"
                           r"wagonjwa|doentes)\b|حالات|حالة|إصابات|إصابة")
# A country named as a border or as a travel origin or transit point, not as the place of the event
_BORDER_AFTER = re.compile(r"^\s*(?:'s\s+)?(?:border|borders|frontier|frontiere|fronteira|mpakani|mpaka)\b")
_BORDER_BEFORE = re.compile(r"(?:border with|borders with|bordering|frontiere avec|frontiere de|fronteira com|mpaka wa|mpakani mwa"
                            # a place the case travelled from or through, not where it was confirmed
                            r"|(?:travell?(?:ing|ed)|arriv(?:ed|ing)|return(?:ed|ing)|coming|flew|flights?) from|via|"
                            r"transit(?:ed|ing)?(?: through| via| in)?|travel history (?:to|from|in)|had been in|"
                            r"en provenance de|de retour de|en transit par|proveniente de|vind[oa] de)"
                            r"\s+(?:the\s+|l'|la\s+|le\s+|du\s+|o\s+|a\s+)?$")


def _not_border(places: list, folded: str) -> list:
    return [p for p in places if not (_BORDER_AFTER.search(folded[p.end:p.end + 16])
                                      or _BORDER_BEFORE.search(folded[max(0, p.start - 24):p.start]))]


def _case_country(text: str, g: Gazetteer) -> str | None:
    """Country of the place named closest to the first mention of cases, within that sentence."""
    for sent in re.split(r"(?<=[.!?])\s+|\n+", text):
        folded = fold_text(sent)
        m = _CASE_MENTION.search(folded)
        if not m:
            continue
        found = g.find(sent)
        places = _not_border(found, folded) or found
        if not places:
            return None
        p = min(places, key=lambda p: min(abs(p.start - m.start()), abs(p.end - m.end())))
        return g.country_of(p.code) if p.level else p.code
    return None


def analyze(text: str, published: date, source_category: SourceCategory, *, g: Gazetteer | None = None,
            langs: dict[str, Language] | None = None, injection_suspected: bool = False,
            is_official_source: bool = False) -> ClaimAnalysis:
    langs = langs or load_languages()
    g = g or load_gazetteer()
    folded = fold_text(text)
    guesses = identify(text, langs)
    active = {x.code for x in guesses}

    f: dict = {}
    for concept in ("ebola", "vhf", "bleeding", "illness", "death", "unexplained", "cluster", "outbreak", "lab",
                    "surveillance", "hedging", "firsthand", "secondary", "rumor", "satire", "debunk",
                    "official_body", "urgency", "temporal_recent", "temporal_past", "preparedness"):
        hits = _hits(langs, active, concept, folded)
        f[concept] = sorted({t for _, t in hits})

    # Negation scoped to an Ebola mention ("ce n'est pas Ebola", "si Ebola", "ezali Ebola te")
    neg_spans = _spans(langs, active, "negation", folded)
    ebola_spans = _spans(langs, active, "ebola", folded)
    negated = any(abs(ns - es) <= NEG_WINDOW for ns, _ in neg_spans for es, _ in ebola_spans)
    f["ebola_negated"] = negated

    alternatives = sorted({alt for code, lang in langs.items() if code in active or not lang.requires_review
                           for alt, p in lang.alternatives.items() if p.search(folded)})
    f["alternative_explanations"] = alternatives

    # Counts claimed (bounded; never converted into case estimates)
    counts: dict[str, int] = {}
    for rx, key in ((_COUNT_DEATH, "deaths"), (_COUNT_DEATH_SW, "deaths"), (_COUNT_ILL, "ill")):
        m = rx.search(text)
        if m and (n := parse_number(m.group("n"))) is not None and 0 < n < 100_000 and key not in counts:
            counts[key] = n

    m = _ORDINAL_CASE.search(text)
    if m and "ill" not in counts:
        word = (m.group("o") or m.group("a") or "").lower()
        if word in _ORDINALS:
            counts["ill"] = _ORDINALS[word]
            f["ordinal_case_claim"] = True

    # Time: explicit dates, then relative expressions, else unknown (publication date is NOT the event date)
    event_date, basis = None, None
    dates = [d for _, _, d, _ in find_dates(text, published) if d <= published + timedelta(days=1)]
    if dates:
        event_date, basis = max(dates), "explicit date in text"
    else:
        for code in active:
            for phrase, days in langs[code].relative_dates.items():
                if re.search(rf"(?<![\w]){re.escape(phrase)}(?![\w])", folded):
                    event_date, basis = published - timedelta(days=days), f"relative expression '{phrase}'"
                    break
            if event_date:
                break

    stale: list[str] = []
    years = {int(y) for y in YEAR_RE.findall(text)}
    old_years = sorted(y for y in years if y < published.year - 0 and y != published.year)
    if old_years and published.year not in years:
        stale.append(f"refers to earlier year(s) {old_years}")
    if f["temporal_past"]:
        stale.append("past-tense temporal cues: " + ", ".join(f["temporal_past"][:3]))
    if event_date and (published - event_date).days > 60:
        stale.append(f"stated event date {event_date} is {(published - event_date).days} days before publication")

    # Place: most specific admin unit mentioned (resolution reduced later for publication)
    places = g.find(text)
    kept = _not_border(places, folded)
    if kept and len(kept) < len(places):
        f["border_mentions"] = sorted({p.surface for p in places if p not in kept})
        places = kept
    region_code, region_level = None, None
    elsewhere = False  # the cases mentioned are nearest another country than the one the text is about
    if places:
        # When several countries are named, attribute the claim to the place nearest the
        # first case/death statement, and keep only the counts stated near that place
        # (avoids e.g. assigning one country's totals to a neighbour in the same headline).
        claims = sorted((mm.start(), mm.end(), key) for rx, key in ((_ORDINAL_CASE, "ill"), (_COUNT_DEATH, "deaths"),
                                                                      (_COUNT_DEATH_SW, "deaths"), (_COUNT_ILL, "ill"))
                        for mm in rx.finditer(text))
        countries = {g.country_of(p.code) if p.level else p.code for p in places}

        def nearest(pos):
            return min(places, key=lambda m: (abs(m.start - pos), -m.level))

        if claims and len(countries) > 1:
            best = nearest(claims[0][1])
            keep = {}
            for _st, en, key in claims:
                if nearest(en).code == best.code and key in counts and key not in keep:
                    keep[key] = counts[key]
            dropped = set(counts) - set(keep)
            if dropped:
                f["counts_dropped_ambiguous_place"] = sorted(dropped)
            counts = keep
        else:
            best = sorted(places, key=lambda m: (-m.level, m.start))[0]
        region_code, region_level = best.code, best.level
        if len(countries) > 1:
            where = _case_country(text, g)
            elsewhere = where is not None and where != (g.country_of(best.code) if best.level else best.code)

    # Claim type
    has_ebola = bool(f["ebola"]) and not negated
    has_vhf = bool(f["vhf"]) or (bool(f["bleeding"]) and bool(f["illness"]))
    has_death = bool(f["death"]) or "deaths" in counts
    has_ill = bool(f["illness"]) or "ill" in counts
    if has_ebola and f["preparedness"] and not (has_death or counts) and (elsewhere or not _CASE_MENTION.search(folded)):
        # preparedness or screening news, not a case report (cases, if any, are in another country)
        claim = ClaimType.SURVEILLANCE_ACTIVITY
        f["preparedness_for_cases_elsewhere"] = elsewhere
    elif has_ebola and (has_death or has_ill or f["outbreak"] or f["lab"]):
        claim = ClaimType.EBOLA_CASES
    elif has_ebola and f["surveillance"]:
        claim = ClaimType.SURVEILLANCE_ACTIVITY
    elif has_vhf and (has_death or has_ill):
        claim = ClaimType.VHF_CLUSTER
    elif f["unexplained"] and has_death:
        claim = ClaimType.UNEXPLAINED_DEATHS
    elif alternatives and (has_ill or has_death):
        claim = ClaimType.ILLNESS_CLUSTER  # another disease is named; noted as alternative explanation
    elif (f["cluster"] or counts) and (has_ill or has_death) and not alternatives:
        claim = ClaimType.ILLNESS_CLUSTER
    elif f["outbreak"] and f["hedging"] and (has_ill or has_death):
        claim = ClaimType.SUSPECTED_OUTBREAK
    elif has_ebola or negated:
        claim = ClaimType.GENERAL_DISCUSSION
    elif (f["cluster"] or counts) and (has_ill or has_death):
        claim = ClaimType.ILLNESS_CLUSTER  # with alternative explanation noted
    elif (has_ill or has_death) and any(langs[x.code].requires_review for x in guesses):
        # Limited language support: do not dismiss what may be a health event; route to people.
        claim = ClaimType.ILLNESS_CLUSTER
    else:
        claim = ClaimType.NOT_RELEVANT

    # Report kind
    if f["satire"]:
        kind = ReportKind.SATIRE
    elif f["debunk"]:
        kind = ReportKind.UNCLEAR  # text disputes a claim; handled as counter-evidence
    elif is_official_source:
        kind = ReportKind.OFFICIAL_ANNOUNCEMENT
    elif source_category in (SourceCategory.NEWS, SourceCategory.HUMANITARIAN, SourceCategory.RESEARCH):
        kind = ReportKind.PROFESSIONAL_REPORTING
    elif f["firsthand"]:
        kind = ReportKind.FIRSTHAND_OBSERVATION
    elif f["secondary"] or f["official_body"]:
        kind = ReportKind.SECONDARY_REPORTING
    elif f["rumor"] or f["hedging"]:
        kind = ReportKind.RUMOR
    else:
        kind = ReportKind.UNCLEAR
    f["disputes_claim"] = bool(f["debunk"])

    # Relevance (categorical, with reasons)
    if claim in (ClaimType.EBOLA_CASES, ClaimType.VHF_CLUSTER, ClaimType.UNEXPLAINED_DEATHS) and kind != ReportKind.SATIRE:
        relevance = "likely" if (event_date or region_code) else "ambiguous"
    elif claim == ClaimType.ILLNESS_CLUSTER and alternatives:
        relevance = "unlikely"
    elif claim in (ClaimType.ILLNESS_CLUSTER, ClaimType.SUSPECTED_OUTBREAK):
        relevance = "ambiguous"
    elif claim in (ClaimType.SURVEILLANCE_ACTIVITY, ClaimType.GENERAL_DISCUSSION):
        relevance = "unlikely"
    else:
        relevance = "unlikely"

    reasons: list[str] = []
    low_support = [x.code for x in guesses if langs[x.code].requires_review]
    if low_support:
        reasons.append("language support is limited or lexicon not native-reviewed: " + ", ".join(low_support))
    if not guesses:
        reasons.append("language not identified")
    if len(guesses) > 1:
        f["code_switching"] = [x.code for x in guesses]
    if injection_suspected:
        reasons.append("text contains instructions aimed at automated systems")
    if relevance == "ambiguous":
        reasons.append("ambiguous terminology; may describe another illness")
    if alternatives and claim in (ClaimType.ILLNESS_CLUSTER, ClaimType.UNEXPLAINED_DEATHS):
        reasons.append("alternative explanations mentioned: " + ", ".join(alternatives))
    needs_review = bool(reasons) and claim not in (ClaimType.NOT_RELEVANT,)

    concepts = sorted({c for c in ("ebola", "vhf", "death", "illness", "unexplained", "cluster", "lab") if f.get(c)})
    if "deaths" in counts:
        concepts.append(f"deaths:{_bucket(counts['deaths'])}")
    translation_quality = "not_needed" if all(x.code in ("en", "fr") for x in guesses) and guesses else (
        "unavailable_human_review" if low_support or not guesses else "lexicon_only")

    return ClaimAnalysis(
        languages=guesses, claim_type=claim, report_kind=kind, relevance=relevance,
        event_date=event_date, event_date_basis=basis, region_code=region_code, region_level=region_level,
        counts=counts, features=f, concepts=concepts, needs_review=needs_review, review_reasons=reasons,
        translation_quality=translation_quality, stale_indicators=stale,
    )


def _bucket(n: int) -> str:
    return "1" if n == 1 else "2-4" if n < 5 else "5-19" if n < 20 else "20+"
