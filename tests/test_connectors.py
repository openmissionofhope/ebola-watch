"""Connectors against mocked HTTP (SYNTHETIC payloads). Live checks are in test_live.py."""

import httpx
import pytest

from ebolawatch.config import get_settings
from ebolawatch.domain.enums import ConnectorStatus
from ebolawatch.nlp.gazetteer import load_gazetteer
from ebolawatch.sources.hdx import parse_rows
from ebolawatch.sources.http import HttpClient
from ebolawatch.sources.manual import ManualImportError, parse_manual_csv
from ebolawatch.sources.news import GdeltConnector, ReliefWebConnector, parse_feed
from ebolawatch.sources.registry import all_connectors
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
    assert status["who_don"] is None
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
