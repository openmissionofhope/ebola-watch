"""Scope enforcement for user-facing questions.

Ebola Watch is an epidemiological intelligence product, not a medical service.
Requests for treatment, medicines, vaccines, dosages, diagnosis or evaluation of
an individual's symptoms are declined with a referral. Requests to identify
patients, contacts or individuals, to track people, or to obtain operationally
sensitive details are refused.

Patterns are deliberately broad: a false refusal costs a rephrased question,
whereas a false acceptance could produce clinical advice or expose people.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum


class Intent(StrEnum):
    DATA_QUESTION = "data_question"
    CLINICAL = "clinical_advice_request"
    PERSONAL_SYMPTOMS = "personal_symptom_evaluation"
    IDENTITY = "identity_request"
    TRACKING = "individual_tracking_request"
    OPERATIONAL = "operational_targeting_request"
    OUT_OF_SCOPE = "out_of_scope"


DISCLAIMER = (
    "Ebola Watch provides epidemiological observation, burden estimation, forecasting and "
    "public-health intelligence. It is not a medical service and does not provide diagnosis, "
    "treatment, medicine, vaccine or other clinical advice. Estimates and forecasts are uncertain "
    "and must not be used to make decisions about an individual's care."
)

CLINICAL_REFERRAL = (
    "Ebola Watch does not provide clinical advice, including advice about medicines, vaccines, "
    "antiviral or experimental treatments, dosages, or care decisions. Please consult a qualified "
    "health professional, or contact your national public-health authority or Ebola hotline. "
    "If someone may have been exposed or is unwell, seek care from a health facility and follow "
    "the instructions of local health authorities."
)

SYMPTOM_REFERRAL = (
    "Ebola Watch cannot evaluate an individual's symptoms or tell anyone whether they have Ebola. "
    "Please contact a qualified health professional or your national public-health authority or "
    "Ebola hotline without delay."
)

IDENTITY_REFUSAL = (
    "Ebola Watch never identifies patients, contacts, witnesses, social-media users or other "
    "individuals, and holds no patient-level, household-level or contact-tracing data. "
    "Only aggregated, non-identifying statistics are available."
)

TRACKING_REFUSAL = (
    "Ebola Watch does not track individuals or groups of people and does not provide "
    "individual movement or travel information. Transport analysis is limited to broad, "
    "aggregated regional connectivity."
)

OPERATIONAL_REFUSAL = (
    "Ebola Watch does not provide operational details about response teams, treatment "
    "facilities, patient transfers, personnel movements or vulnerabilities of infrastructure."
)

_M = re.I | re.S

_CLINICAL = [
    r"\b(treat(ment|ing|s)?|cure[sd]?|therap(y|ies|eutic)s?|medicines?|medications?|drugs?|antivirals?|remd[ie]sivir|inmazeb|ebanga|mab114|zmapp|ansuvimab|monoclonal|dos(e|age|ing)s?|prescri(be|ption)|pills?|antibiotics?|vaccin(e|es|ate|ation)|ervebo|rvsv|immuni[sz]ation|jab)\b",
    r"\b(traitement|soigner|guérir|médicaments?|remèdes?|vaccins?|posologie|ordonnance)\b",
    r"\b(dawa|tiba|chanjo|kutibu|kipimo cha dawa)\b",  # Swahili
    r"\b(nkisi|kisi|monganga)\b",  # Lingala: medicine / healer
    r"\b(tratamento|remédios?|medicamentos?|vacinas?|dosagem)\b",  # Portuguese
    r"(علاج|دواء|لقاح|جرعة)",  # Arabic
]

_SYMPTOMS = [
    r"\b(i|my (child|son|daughter|wife|husband|mother|father|friend|baby|neighbou?r)|we|he|she)\b.{0,60}\b(fever|bleed(ing)?|vomit(ing)?|diarrh(o)?ea|headache|rash|sick|ill|symptoms?)\b",
    r"\b(do|does|could|might)\b.{0,10}\b(i|he|she|they|my \w+)\b.{0,20}\b(have|got|caught)\b.{0,20}\bebola\b",
    r"\b(j'ai|mon enfant|ma fille|mon fils|il a|elle a)\b.{0,60}\b(fièvre|saign|vomi|diarrhée|malade|symptômes?)\b",
    r"\b(nina|mtoto wangu|ana)\b.{0,40}\b(homa|kutapika|kuhara|damu|mgonjwa)\b",
    r"\b(nazali|mwana na ngai)\b.{0,40}\b(fievre|kobela|makila|bokono)\b",
]

_IDENTITY = [
    r"\b(names?|identit(y|ies)|who (is|are|was|were)|identify|addresses?|phone numbers?|photos?|where does)\b.{0,60}\b(patients?|cases?|infected|victims?|sick people|contacts?|suspects?|health ?workers?|witness(es)?|poster|users?|families|households?)\b",
    r"\blist of (the )?(patients|infected|sick people|contacts|suspects|victims|families|households)\b",
    r"\b(patients?|infected people|contacts?|cases?)\b.{0,40}\b(names?|identit(y|ies)|addresses?|phone|who are they)\b",
    r"\b(nom|noms|identité|adresse|qui sont)\b.{0,40}\b(patients?|malades|cas|contacts?|infectés?)\b",
    r"\b(majina|jina|anwani)\b.{0,40}\b(wagonjwa|mgonjwa|walioambukizwa)\b",
    r"\b(which|what) (house|household|family|street|building|village) (has|have|is)\b",
    r"\b(dox|unmask|de-?anonymi[sz]e|reveal the (author|account|user))\b",
]

_TRACKING = [
    r"\b(track|trace|follow|locate|find|monitor|where (is|are|did))\b.{0,50}\b(patients?|infected|person|people|someone|refugees?|migrants?|displaced|travell?ers?|contacts?|him|her|them)\b.{0,50}\b(go|went|now|movements?|location|travel(l?ed)?|whereabouts)?",
    r"\b(travel history|movements?|itinerary|flight (number|manifest)|passenger list)\b.{0,40}\b(of|for)\b.{0,30}\b(patient|case|infected|person|individual)\b",
    r"\b(suivre|localiser|retrouver)\b.{0,40}\b(patients?|malades|personnes?|réfugiés?)\b",
]

_OPERATIONAL = [
    r"\b(attack|target|sabotage|disrupt|block|ambush|loot|raid|burn)\b.{0,60}\b(treatment (centre|center|unit)s?|ETCs?|clinics?|hospitals?|response teams?|health ?workers?|labs?|laborator(y|ies)|convoys?|ferr(y|ies)|bridges?|roads?|airports?|vaccination teams?)\b",
    r"\b(where|when|which route|schedule)\b.{0,40}\b(response teams?|burial teams?|convoys?|vaccination teams?|patient transfers?|medevac|ambulances?)\b.{0,40}\b(go|travel|move|pass|located|stationed)?",
    r"\b(security (gaps?|weakness(es)?)|unguarded|least protected)\b",
]

_FACILITY_WORDS = re.compile(
    r"\b(treatment (cent(re|er)|unit)s?|centres? de traitement( ebola)?|CTEs?|ETCs?)\b", re.I
)

_DATA_WORDS = re.compile(
    r"\b(cases?|deaths?|outbreak|forecast|estimate|trend|province|country|region|severity|risk|"
    r"surveillance|reported|confirmed|probable|how (many|much)|incidence|rt\b|reproduction|spread|"
    r"cas|décès|épidémie|prévision|wagonjwa|vifo|mlipuko|bokono|bakufi)\b",
    re.I,
)


@dataclass(frozen=True)
class ScopeDecision:
    intent: Intent
    allowed: bool
    message: str | None
    matched: tuple[str, ...] = ()


def _any(patterns: list[str], text: str) -> list[str]:
    return [p for p in patterns if re.search(p, text, _M)]


def classify_request(text: str) -> ScopeDecision:
    t = " ".join((text or "").split())
    if not t:
        return ScopeDecision(Intent.OUT_OF_SCOPE, False, "Empty question.")

    # Order matters: safety refusals outrank everything else.
    if m := _any(_OPERATIONAL, t):
        return ScopeDecision(Intent.OPERATIONAL, False, OPERATIONAL_REFUSAL, tuple(m))
    if m := _any(_IDENTITY, t):
        return ScopeDecision(Intent.IDENTITY, False, IDENTITY_REFUSAL, tuple(m))
    if m := _any(_TRACKING, t):
        # "where is the outbreak spreading" is a data question; tracking requires a person target.
        return ScopeDecision(Intent.TRACKING, False, TRACKING_REFUSAL, tuple(m))
    if m := _any(_SYMPTOMS, t):
        return ScopeDecision(Intent.PERSONAL_SYMPTOMS, False, SYMPTOM_REFERRAL, tuple(m))
    # Facility names are not treatment requests ("deaths in treatment centres").
    t_clin = _FACILITY_WORDS.sub(" facility ", t)
    clinical = _any(_CLINICAL, t_clin)
    if clinical:
        # Any request mentioning treatments, medicines or vaccines is referred,
        # whether or not it is phrased as a recommendation.
        return ScopeDecision(Intent.CLINICAL, False, CLINICAL_REFERRAL, tuple(clinical))
    if _DATA_WORDS.search(t):
        return ScopeDecision(Intent.DATA_QUESTION, True, None)
    return ScopeDecision(
        Intent.OUT_OF_SCOPE,
        False,
        "Ebola Watch answers questions about reported Ebola data, estimates, forecasts, severity and "
        "surveillance quality. Try asking, for example, 'How many confirmed cases in Uganda?'",
    )
