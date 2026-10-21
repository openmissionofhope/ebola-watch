"""Connectors against mocked HTTP (SYNTHETIC payloads). Live checks are in test_live.py."""

import httpx
import pytest

from ebolawatch.config import get_settings
from ebolawatch.domain.enums import ConnectorStatus
from ebolawatch.nlp.gazetteer import load_gazetteer
from ebolawatch.sources.ecdc import EcdcConnector
from ebolawatch.sources.hdx import parse_rows
from ebolawatch.sources.http import HttpClient
from ebolawatch.sources.manual import ManualImportError, parse_manual_csv
from ebolawatch.sources.news import GdeltConnector, ReliefWebConnector, parse_feed
from ebolawatch.sources.registry import all_connectors
from ebolawatch.sources.statements import OfficialStatementsConnector, StatementError, parse_statement
from ebolawatch.sources.who_don import WhoDonConnector


def client_for(handler):
    return HttpClient(transport=httpx.MockTransport(handler), sleep=lambda s: None)


SYNTHETIC_DON_JSON = {"value": [{
    "DonId": "2031-DON999", "Title": "Ebola disease caused by Bundibugyo virus - Democratic Republic of the Congo",
    "PublicationDateAndTime": "2031-03-05T10:00:00Z", "LastModified": "2031-03-05T10:00:00Z", "UrlName": "2031-DON999",
    "Summary": "<p>As of 3 March 2031, the Democratic Republic of the Congo has reported 1234 confirmed cases, including 456 deaths.</p>",
    "Overview": "<p>SYNTHETIC test bulletin.</p>", "Epidemiology": "",
}]}


def test_who_don_connector_parses_bulletins():
    def handler(req):
        return httpx.Response(200, json=SYNTHETIC_DON_JSON if "skip=0" in str(req.url) or "%24skip=0" in str(req.url) else {"value": []})

    res = WhoDonConnector(page_size=50).fetch(client_for(handler), get_settings())
    assert res.status == ConnectorStatus.OK and len(res.items) == 1
    item = res.items[0]
    assert item.is_official and item.url.endswith("2031-DON999")
    assert any(c.region_ref == "COD" and c.value == 1234 for c in item.observations)


SYNTHETIC_ECDC_HTML = """<html><body><nav><p>Topics A-Z</p></nav><main>
<h1>Ebola disease outbreak in the Democratic Republic of the Congo</h1>
<p>This page is updated every weekday. It was last updated on 5 March 2031 at 16:11.</p>
<p>As of 4 March 2031, the Democratic Republic of the Congo (DRC) reported a total of 1 234 confirmed cases, including
456 related deaths (from data up until 3 March). Bundibugyo virus SYNTHETIC test page.</p>
<p>Ituri province remains the most affected, with 1 234 cases, including 456 deaths, reported from 20 of 36 health zones.</p>
<p>According to ECDC modelling, the risk for the EU/EEA remains very low.</p>
<p>In Uganda, the first confirmed case was reported on 1 March.</p>
</main></body></html>"""


def test_ecdc_connector_parses_the_situation_summary_only():
    res = EcdcConnector().fetch(client_for(lambda req: httpx.Response(200, text=SYNTHETIC_ECDC_HTML)), get_settings())
    assert res.status == ConnectorStatus.OK and len(res.items) == 1
    item = res.items[0]
    assert item.is_official and item.meta["pathogen"] == "BDBV" and item.meta["data_as_of"] == "2031-03-03"
    assert item.external_id == "update 2031-03-05T16:11" and item.published_at.hour == 16
    assert "Topics A-Z" not in item.text and "EU/EEA" not in item.text  # navigation and risk assessment are not kept
    assert not [c for c in item.observations if c.region_ref == "UGA"]  # after the summary ends
    assert {(c.region_ref, c.value) for c in item.observations if c.metric.value == "cases"} == {("COD", 1234), ("CD-IT", 1234)}

    changed = EcdcConnector().fetch(client_for(lambda req: httpx.Response(200, text="<main><p>Redesigned page</p></main>")),
                                    get_settings())
    assert changed.status == ConnectorStatus.PARTIAL and not changed.items and "not recognised" in changed.message


def test_official_statements_file_is_valid_and_every_figure_is_cited():
    countries = {code for code, level in load_gazetteer().names.values() if level == 0}
    res = OfficialStatementsConnector().fetch(None, get_settings())
    assert res.status == ConnectorStatus.OK and res.items, res.message
    assert len({i.external_id for i in res.items}) == len(res.items)
    for item in res.items:
        assert item.is_official and item.url.startswith("https://") and item.meta["citation"] and item.meta["authority"]
        for c in item.observations:
            assert c.quote and c.extraction_method == "transcribed" and c.region_ref in countries
            for code in [c.attributes.get("origin_iso3"), *c.attributes.get("transit_iso3", [])]:
                assert code is None or code in countries


def test_official_statement_entries_are_checked():
    entry = {"id": "x", "published_on": "2031-03-05", "authority": "SYNTHETIC ministry", "title": "SYNTHETIC statement",
             "url": "https://example.invalid/s", "citation": "SYNTHETIC", "quote": "SYNTHETIC quote",
             "observations": [{"region": "KEN", "metric": "cases", "transmission": "imported", "as_of": "2031-03-05", "value": 1,
                               "attributes": {"transit_iso3": ["uga"], "travel_date": "2031-03-01"}}]}
    item = parse_statement(entry)
    (c,) = item.observations
    assert c.attributes == {"transit_iso3": ["UGA"], "travel_date": "2031-03-01"} and c.quote == "SYNTHETIC quote"
    for broken in ({"url": None}, {"observations": [{"region": "KEN", "metric": "cases", "as_of": "2031-03-05", "value": -1}]},
                   {"observations": [{"region": "KEN", "metric": "cases", "as_of": "2031-03-05", "value": 1,
                                      "attributes": {"route": "x"}}]}):
        with pytest.raises(StatementError):
            parse_statement(entry | broken)


def test_blocked_or_rate_limited_sources_report_unavailable_without_bypass():
    calls = []

    def forbidden(req):
        calls.append(req)
        return httpx.Response(403)

    res = WhoDonConnector().fetch(client_for(forbidden), get_settings())
    assert res.status == ConnectorStatus.UNAVAILABLE and "not bypassed" in res.message and len(calls) == 1

    res2 = GdeltConnector(languages={"english": ("en", "ebola")}).fetch(client_for(lambda r: httpx.Response(429)), get_settings())
    assert res2.status == ConnectorStatus.UNAVAILABLE and "rate limited" in res2.message


def test_connectors_that_need_configuration_or_are_unsupported_say_so():
    s = get_settings()
    status = {c.info.key: c.configuration_problem(s) for c in all_connectors(s)}
    assert status["reliefweb"][0] == ConnectorStatus.REQUIRES_CONFIGURATION
    assert status["facebook"][0] == ConnectorStatus.UNSUPPORTED and status["telegram"][0] == ConnectorStatus.UNSUPPORTED
    assert status["hdx_cod_ebola"][0] == ConnectorStatus.REQUIRES_ACKNOWLEDGEMENT
    assert status["who_don"] is None and status["ecdc"] is None
    assert ReliefWebConnector().fetch is not None


def test_feed_parser_rejects_entity_expansion():
    evil = """<?xml version="1.0"?><!DOCTYPE lolz [<!ENTITY lol "lol"><!ENTITY lol2 "&lol;&lol;">]><rss><channel><item><title>&lol2;</title></item></channel></rss>"""
    from defusedxml import DTDForbidden, EntitiesForbidden

    with pytest.raises((EntitiesForbidden, DTDForbidden)):
        parse_feed(evil)
    ok = parse_feed("<rss><channel><item><title>Ebola update</title><link>https://x.invalid/a</link></item></channel></rss>")
    assert ok[0]["title"] == "Ebola update"


def test_hdx_rows_map_health_zones_and_skip_unknown_names():
    csv_text = (
        "location_country,location_level,location_name,location_name_source,location_code,location_code_type,reference_date,"
        "measure,case_classification,time_period,value,unit,source,source_url,source_indicator_name,indicator_label,"
        "reporting_period_start,reporting_period_end,last_updated,data_quality_flag,notes\n"
        "COD,0,RDC,DRC,COD,iso3,2031-01-10,cases,confirmed,cumulative,50,count,SYNTHETIC,,,,,,,,\n"
        "COD,3,Mongbalu,Mongbwalu,CD540510,pcode,2031-01-10,cases,confirmed,cumulative,12,count,SYNTHETIC,,,,,,,,\n"
        "COD,3,Nowhere-zone,Nowhere-zone,CD999999,pcode,2031-01-10,cases,confirmed,cumulative,3,count,SYNTHETIC,,,,,,,,\n"
    )
    obs, unmatched = parse_rows(csv_text, load_gazetteer())
    assert {o.region_ref for o in obs} == {"COD", "HZ:CD-IT:mongbwalu"}
    assert unmatched == {"Nowhere-zone"}


def test_manual_import_validates_rows():
    good = "region,metric,case_class,value_type,as_of,value\nCOD,cases,confirmed,cumulative,2031-01-01,10\n"
    item = parse_manual_csv(good, "manual:test", citation="SYNTHETIC sitrep")
    assert item.observations[0].value == 10 and item.observations[0].extraction_method == "manual"
    with pytest.raises(ManualImportError):
        parse_manual_csv("region,metric\nCOD,cases\n", "x")
    with pytest.raises(ManualImportError):
        parse_manual_csv(good.replace(",10", ",-4"), "x")
