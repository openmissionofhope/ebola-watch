"""Extraction of official figures from bulletin-style text (SYNTHETIC text and numbers)."""

from datetime import date

from ebolawatch.domain.enums import CaseClass, Metric, TransmissionType, ValueType
from ebolawatch.nlp.gazetteer import load_gazetteer
from ebolawatch.parsing.ecdc import extract as extract_ecdc
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


SYNTHETIC_ECDC = (
    "This page is updated every weekday. It was last updated on 5 March at 16:11.\n"
    "As of 4 March 2031, the Democratic Republic of the Congo (DRC) reported a total of 1 300 confirmed cases, including "
    "500 related deaths (from data up until 3 March). On 3 March, 40 new confirmed cases and 9 deaths were reported. "
    "The 40 new cases have been reported from Ituri (33 cases) and North Kivu (7 cases).\n"
    "Ituri province remains the most affected, with 1 000 cases, including 400 deaths, reported from 20 of 36 health zones. "
    "In Nord-Kivu, 298 cases, including 99 deaths, have been reported from 9 of 34 health zones. "
    "In Sud Ubangi, two cases and one death have been reported from one of 16 health zones. "
    "Overall, 30 of 167 health zones are currently affected across three provinces.\n"
    "According to media reports citing officials, two cases have been confirmed in Tshopo, making it the fourth affected province.\n"
    "On 1 March 2031, Kenya's Ministry of Health announced the country's first confirmed imported Ebola virus disease case. "
    "On 3 March, a second case was reported in a contact in quarantine.\n"
    "A healthcare worker who tested positive in DRC on 2 March was medically evacuated to Germany; it is the first case "
    "treated in Germany."
)


def ecdc_by(ex):
    return {(c.region_ref, c.metric, c.transmission): c for c in ex.candidates}


def test_ecdc_national_and_complete_provincial_breakdown():
    ex = extract_ecdc(SYNTHETIC_ECDC, date(2031, 3, 6), G)
    k = ecdc_by(ex)
    assert ex.updated_on == date(2031, 3, 5) and ex.as_of == date(2031, 3, 3)  # the data date, not the page date
    assert k[("COD", Metric.CASES, TransmissionType.ALL)].value == 1300
    assert k[("COD", Metric.DEATHS, TransmissionType.ALL)].value == 500
    assert k[("COD", Metric.AFFECTED_ADMIN1, TransmissionType.ALL)].value == 3
    assert k[("COD", Metric.AFFECTED_ADMIN2, TransmissionType.ALL)].attributes["denominator"] == 167
    provinces = {r: k[(r, Metric.CASES, TransmissionType.ALL)] for r in ("CD-IT", "CD-NK", "CD-SU")}
    assert [p.value for p in provinces.values()] == [1000, 298, 2]
    assert all(p.case_class == CaseClass.CONFIRMED and p.confidence == "high" for p in provinces.values())
    assert k[("CD-SU", Metric.DEATHS, TransmissionType.ALL)].value == 1
    # daily increments are not totals, and media reports are not official figures
    assert all(c.value not in (33, 7, 40) for c in ex.candidates)
    assert not [c for c in ex.candidates if c.region_ref == "CD-TO"]


def test_ecdc_incomplete_provincial_breakdown_goes_to_review():
    text = SYNTHETIC_ECDC.replace("In Sud Ubangi, two cases and one death have been reported from one of 16 health zones. ", "")
    k = ecdc_by(extract_ecdc(text, date(2031, 3, 6), G))
    assert k[("CD-IT", Metric.CASES, TransmissionType.ALL)].confidence == "low"
    assert k[("COD", Metric.CASES, TransmissionType.ALL)].confidence == "high"


def test_ecdc_other_countries_from_explicit_ordinals_only():
    k = ecdc_by(extract_ecdc(SYNTHETIC_ECDC, date(2031, 3, 6), G))
    imported = k[("KEN", Metric.CASES, TransmissionType.IMPORTED)]
    assert imported.value == 1 and imported.as_of == date(2031, 3, 1)
    total = k[("KEN", Metric.CASES, TransmissionType.ALL)]
    assert total.value == 2 and total.as_of == date(2031, 3, 3) and "lower bound" in total.notes[0]
    assert not [c for c in k.values() if c.region_ref == "DEU"]  # medical evacuation is not a case in Germany


def test_ecdc_without_dated_national_total_extracts_nothing():
    ex = extract_ecdc("It was last updated on 5 March at 16:11.\nIn Nord-Kivu, 298 cases have been reported.", date(2031, 3, 6), G)
    assert ex.candidates == [] and ex.skipped
