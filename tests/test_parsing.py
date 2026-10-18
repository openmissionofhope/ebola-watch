"""Extraction of official figures from bulletin-style text (SYNTHETIC text and numbers)."""

from datetime import date

from ebolawatch.domain.enums import CaseClass, Metric, TransmissionType, ValueType
from ebolawatch.nlp.gazetteer import load_gazetteer
from ebolawatch.parsing.textnum import find_dates, parse_number
from ebolawatch.parsing.who_don import extract

G = load_gazetteer()

SYNTHETIC_DON = (
    "As of 3 March 2031, the Democratic Republic of the Congo has reported 1234 confirmed cases, including 456 deaths, "
    "corresponding to a crude case fatality ratio (CFR) of 37.0%. Since the last Disease Outbreak News, an additional "
    "210 confirmed cases have been reported. Confirmed cases have been identified in 21 health zones across three provinces. "
    "Ituri remains the epicentre, with 900 cumulative confirmed cases and 300 deaths. "
    "On 1 March 2031, WHO was informed about a laboratory-confirmed imported case of Bundibugyo virus disease in Kenya "
    "with travel history from the Democratic Republic of the Congo. "
    "As of 2 March, 15 120 of 18 000 contacts were followed up."
)


def kinds(ex):
    return {(c.region_ref, c.metric, c.case_class, c.value_type, c.transmission): c for c in ex.candidates}


def test_numbers_and_dates():
    assert parse_number("23 741") == 23741
    assert parse_number("8,728") == 8728
    assert parse_number("nine") == 9
    ds = find_dates("As of 6 October, and on 1 July 2030", date(2031, 1, 5))
    assert ds[0][2] == date(2030, 10, 6)  # year inferred as the most recent past date
    assert ds[1][2] == date(2030, 7, 1)


def test_extracts_national_totals_with_classes():
    ex = extract("Ebola disease caused by Bundibugyo virus - Democratic Republic of the Congo", SYNTHETIC_DON, date(2031, 3, 5), G)
    k = kinds(ex)
    c = k[("COD", Metric.CASES, CaseClass.CONFIRMED, ValueType.CUMULATIVE, TransmissionType.ALL)]
    assert c.value == 1234 and c.as_of == date(2031, 3, 3) and c.quote
    assert k[("COD", Metric.DEATHS, CaseClass.CONFIRMED, ValueType.CUMULATIVE, TransmissionType.ALL)].value == 456
    assert ex.stated_cfr[0] == 37.0
    # the "additional 210" increment is not mistaken for a cumulative total
    assert all(c.value != 210 for c in ex.candidates)


def test_pathogen_name_does_not_geocode_to_uganda():
    ex = extract("Ebola disease caused by Bundibugyo virus - Democratic Republic of the Congo", SYNTHETIC_DON, date(2031, 3, 5), G)
    assert ex.primary_countries == ["COD"]


def test_province_and_context_metrics():
    ex = extract("Ebola disease caused by Bundibugyo virus - Democratic Republic of the Congo", SYNTHETIC_DON, date(2031, 3, 5), G)
    k = kinds(ex)
    assert k[("CD-IT", Metric.CASES, CaseClass.CONFIRMED, ValueType.CUMULATIVE, TransmissionType.ALL)].value == 900
    assert k[("COD", Metric.AFFECTED_ADMIN2, CaseClass.CONFIRMED, ValueType.CUMULATIVE, TransmissionType.ALL)].value == 21
    contacts = k[("COD", Metric.CONTACTS_SEEN, CaseClass.NOT_APPLICABLE, ValueType.INCIDENT, TransmissionType.ALL)]
    assert contacts.value == 15120 and contacts.attributes["denominator"] == 18000


def test_imported_case_has_origin_and_is_not_local():
    ex = extract("Ebola disease caused by Bundibugyo virus - Democratic Republic of the Congo", SYNTHETIC_DON, date(2031, 3, 5), G)
    imp = [c for c in ex.candidates if c.transmission == TransmissionType.IMPORTED]
    assert imp and imp[0].region_ref == "KEN" and imp[0].attributes["origin_iso3"] == "COD"


def test_multicountry_total_is_split_only_for_review():
    text = "As of 9 April, a total of 50 confirmed cases, including four in Uganda, have been reported across both countries."
    ex = extract("Ebola disease, Democratic Republic of the Congo & Uganda", text, date(2031, 4, 10), G)
    by = {(c.region_ref, c.extraction_method): c for c in ex.candidates}
    assert by[("UGA", "text_pattern")].value == 4
    derived = by[("COD", "derived")]
    assert derived.value == 46 and derived.confidence == "low"  # routed to review


def test_zero_statement_and_end_declaration():
    text = ("In Uganda no new cases have been reported since 2 May 2031. "
            "On 14 June 2031, the Ministry of Health of Uganda declared the end of the outbreak in the country.")
    ex = extract("Ebola disease, Democratic Republic of the Congo & Uganda", text, date(2031, 6, 20), G)
    zero = [c for c in ex.candidates if c.value_type == ValueType.INCIDENT and c.value == 0]
    assert zero and zero[0].period_start == date(2031, 5, 2)
    assert any(c.metric == Metric.OUTBREAK_END_DECLARED and c.as_of == date(2031, 6, 14) for c in ex.candidates)


def test_health_zone_sentence_not_assigned_to_province():
    text = ("As of 3 March 2031, the country has recorded 500 confirmed cases. "
            "Mandima in Ituri is the most recently affected health zone and reported four confirmed cases.")
    ex = extract("Ebola disease - Democratic Republic of the Congo", text, date(2031, 3, 5), G)
    assert not [c for c in ex.candidates if c.region_ref == "CD-IT"]
