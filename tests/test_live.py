"""Live integration checks against real public services.

Run explicitly with:  pytest -m live
These contact external services and their results depend on what those
services publish at the time; they are excluded from the default test run.
"""

import pytest

from ebolawatch.config import get_settings
from ebolawatch.domain.enums import ConnectorStatus, Metric
from ebolawatch.sources.ecdc import EcdcConnector
from ebolawatch.sources.http import HttpClient
from ebolawatch.sources.reference import OverpassTransportConnector, WorldBankPopulationConnector
from ebolawatch.sources.who_don import WhoDonConnector

pytestmark = pytest.mark.live


def test_live_who_don_returns_official_figures():
    res = WhoDonConnector(page_size=10, max_items=10).fetch(HttpClient(), get_settings())
    assert res.status in (ConnectorStatus.OK, ConnectorStatus.PARTIAL)
    assert res.items
    assert any(o.metric == Metric.CASES for it in res.items for o in it.observations)


def test_live_ecdc_returns_official_figures():
    res = EcdcConnector().fetch(HttpClient(), get_settings())
    assert res.status == ConnectorStatus.OK, res.message
    assert any(o.metric == Metric.CASES and o.region_ref == "COD" for o in res.items[0].observations)


def test_live_world_bank_population():
    res = WorldBankPopulationConnector(["COD", "UGA"]).fetch(HttpClient(), get_settings())
    assert res.status == ConnectorStatus.OK
    pops = res.items[0].meta["populations"]
    assert pops["COD"]["population"] > 10_000_000


def test_live_overpass_check():
    chk = [{"edge_key": "lake-kivu-nk-sk", "bbox": [-2.6, 28.8, -1.4, 29.5], "selector": 'way["route"="ferry"]'}]
    res = OverpassTransportConnector(chk).fetch(HttpClient(), get_settings())
    assert res.status in (ConnectorStatus.OK, ConnectorStatus.UNAVAILABLE)
