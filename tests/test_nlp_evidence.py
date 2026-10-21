"""Multilingual analysis and evidence assessment on SYNTHETIC posts."""

from datetime import UTC, date, datetime, timedelta

from ebolawatch.domain.enums import ClaimType, Corroboration, ReportKind, SignalAssessment, SourceCategory
from ebolawatch.evidence.assess import OfficialContext, SignalRecord, cluster
from ebolawatch.evidence.fingerprint import minhash, similarity
from ebolawatch.nlp.classifier import analyze
from ebolawatch.nlp.gazetteer import load_gazetteer
from ebolawatch.nlp.langid import identify

PUB = date(2031, 6, 20)
G = load_gazetteer()


def rec(i, text, author, kind=None, published=None, lang=None, cat=SourceCategory.SOCIAL_MEDIA, **kw):
    a = analyze(text, (published or datetime(2031, 6, 20, tzinfo=UTC)).date(), cat)
    admin1 = G.admin1_of(a.region_code) if a.region_code else None
    return SignalRecord(
        id=i, document_id=i, published_at=published or datetime(2031, 6, 20, 8, tzinfo=UTC), event_date=a.event_date,
        region_code=a.region_code, admin1_code=admin1, country_code=G.country_of(a.region_code) if a.region_code else None,
        claim_type=a.claim_type, report_kind=kind or a.report_kind, relevance=a.relevance, fingerprint=minhash(text), author=author,
        author_first_seen=kw.get("first_seen"), is_repost=kw.get("repost", False), languages=[x.code for x in a.languages],
        stale_indicators=a.stale_indicators, official_attribution=bool(a.features["official_body"]),
        disputes_claim=a.features["disputes_claim"], ebola_negated=a.features["ebola_negated"], injection_suspected=False,
        is_official_source=kw.get("official", False), urgency=bool(a.features["urgency"]), platform="x",
    )


def test_language_identification_handles_code_switching():
    codes = [g.code for g in identify("Bato mingi bazali malades na quartier, on dit que c'est Ebola, ezali solo te?")]
    assert codes[0] == "ln" and "fr" in codes


def test_keyword_alone_is_not_an_outbreak_and_negation_is_respected():
    a = analyze("Several people in our village are sick with fever", PUB, SourceCategory.SOCIAL_MEDIA)
    assert a.claim_type == ClaimType.ILLNESS_CLUSTER and a.relevance == "ambiguous"
    b = analyze("Ce n'est pas Ebola, les tests sont négatifs selon le ministère", PUB, SourceCategory.NEWS)
    assert b.features["ebola_negated"] and b.claim_type == ClaimType.GENERAL_DISCUSSION
    c = analyze("Watu watano wamekufa kwa kipindupindu kijijini kwetu jana", PUB, SourceCategory.SOCIAL_MEDIA)
    assert "cholera" in c.features["alternative_explanations"] and c.claim_type != ClaimType.EBOLA_CASES
    d = analyze("LOL Ebola is coming for us all 😂", PUB, SourceCategory.SOCIAL_MEDIA)
    assert d.report_kind == ReportKind.SATIRE and d.relevance == "unlikely"


def test_preparedness_news_is_not_a_case_claim_where_the_country_prepares():
    def claim(text):
        a = analyze(text, PUB, SourceCategory.NEWS)
        return a.claim_type, a.region_code

    # reacting to cases in another country, or preventing a possible outbreak: surveillance activity
    assert claim("Sierra Leone heightens Ebola surveillance after Kenya confirmed cases")[0] == ClaimType.SURVEILLANCE_ACTIVITY
    assert claim("Ghana on high alert after traveller tested positive for Ebola in Kenya")[0] == ClaimType.SURVEILLANCE_ACTIVITY
    assert claim("Ethiopia intensifies coordinated measures to prevent potential Ebola outbreak")[0] == ClaimType.SURVEILLANCE_ACTIVITY
    # cases in the preparing country itself are still case claims
    assert claim("Tanzania steps up response after suspected Ebola cases in Kagera") == (ClaimType.EBOLA_CASES, "TZ-05")
    assert claim("Rwanda heightens vigilance as two suspected Ebola cases are isolated in Kigali")[0] == ClaimType.EBOLA_CASES
    # a country named only as a border or as where a case travelled from is not where the cases are
    assert claim("Nigeria confirms first Ebola case in woman traveling from Uganda") == (ClaimType.EBOLA_CASES, "NGA")
    assert claim("Ebola reaches a new province in DRC as two new cases are reported near the CAR border") == (ClaimType.EBOLA_CASES, "COD")


def test_virus_name_is_not_the_district_and_denials_are_not_case_claims():
    def claim(text):
        a = analyze(text, PUB, SourceCategory.NEWS)
        return a.claim_type, a.region_code

    # "Bundibugyo" names the virus here, not the district in western Uganda
    assert claim("Nigeria reports first imported Ebola Bundibugyo case in Abuja") == (ClaimType.EBOLA_CASES, "NGA")
    assert claim("Au Nigeria, le choc après l'annonce d'un premier cas d'Ebola de souche Bundibugyo")[1] == "NGA"
    assert claim("Ebola case confirmed in Bundibugyo district, health ministry says")[1] == "UG-W"
    # a country saying it has no cases is not reporting cases
    assert claim("Uganda says no active Ebola cases after Nigeria confirms infection")[0] == ClaimType.GENERAL_DISCUSSION
    assert claim("Uganda denies Ebola outbreak after Nigeria confirms imported case")[0] == ClaimType.GENERAL_DISCUSSION


def test_scenario_03_rumour_with_100_reposts_is_one_origin():
    base = "URGENT: Ebola outbreak in Goma, 40 people dead, hospitals hiding it, share before deleted"
    sigs = [rec(i, f"RT @acct{i}: " + base + (" #ebola" if i % 3 else ""), f"user{i}",
                published=datetime(2031, 6, 20, 8, tzinfo=UTC) + timedelta(minutes=i * 40)) for i in range(100)]
    res = cluster(sigs, OfficialContext(), today=PUB)
    assert len(res) == 1
    c = res[0]
    assert c.n_documents == 100 and c.n_origins == 1 and c.n_independent <= 1
    assert c.assessment in (SignalAssessment.INFORMATION_EVENT, SignalAssessment.COORDINATED_AMPLIFICATION, SignalAssessment.INSUFFICIENT_EVIDENCE)
    assert c.assessment != SignalAssessment.POSSIBLE_EMERGING


def test_scenario_04_independent_sources_raise_possible_emerging_signal():
    texts = [
        ("I saw three of my neighbours die suddenly after bleeding and fever in Isiro this week", "a1"),
        ("Dans notre village près d'Isiro, ma voisine et son mari sont morts hier, maladie inconnue avec saignements", "a2"),
        ("Local radio reports unexplained deaths with fever and bleeding in Isiro area; families buried five people", "a3"),
    ]
    sigs = [rec(i, t, a, published=datetime(2031, 6, 19 + i % 2, tzinfo=UTC)) for i, (t, a) in enumerate(texts)]
    res = cluster(sigs, OfficialContext(), today=PUB)
    assert len(res) == 1
    c = res[0]
    assert c.unit == "CD-HU" and c.n_independent >= 2
    assert c.assessment == SignalAssessment.POSSIBLE_EMERGING and c.needs_review


def test_scenario_05_french_and_lingala_posts_link_to_same_event():
    fr = rec(1, "Plusieurs personnes sont mortes hier à Bunia, on dit que c'est Ebola", "u1")
    ln = rec(2, "Na mononi bato mingi bakufi na Bunia lobi, bokono ya makila, baloba ezali Ebola", "u2")
    res = cluster([fr, ln], OfficialContext(), today=PUB)
    assert len(res) == 1 and set(res[0].languages) >= {"fr", "ln"} and res[0].n_origins == 2


def test_scenario_06_ambiguous_low_resource_language_escalates_to_review():
    a = analyze("Abantu benshi bapfuye, indwara itazwi, ni icyorezo?", PUB, SourceCategory.SOCIAL_MEDIA)
    assert a.needs_review and any("language support" in r for r in a.review_reasons)
    assert a.translation_quality == "unavailable_human_review"
    assert a.claim_type != ClaimType.EBOLA_CASES


def test_scenario_07_outdated_report_reposted_is_stale():
    old_text = "Ebola outbreak: 25 deaths confirmed in Mbandaka, ministry says"
    old = rec(1, old_text, "news1", published=datetime(2030, 11, 1, tzinfo=UTC), cat=SourceCategory.NEWS)
    new = rec(2, "Fwd: " + old_text, "u9", published=datetime(2031, 6, 20, tzinfo=UTC))
    res = cluster([new], OfficialContext(), history=[(1, old.fingerprint, old.published_at)], today=PUB)
    assert res and res[0].stale and res[0].assessment == SignalAssessment.STALE_RECIRCULATION
    a = analyze("Throwback: in 2014 Ebola killed thousands in West Africa", PUB, SourceCategory.SOCIAL_MEDIA)
    assert a.stale_indicators


def test_scenario_20_coordinated_campaign_does_not_manufacture_corroboration():
    text = "BREAKING: Ministry of Health confirms Ebola outbreak in Goma, 12 dead. Share widely!"
    t0 = datetime(2031, 6, 20, 6, tzinfo=UTC)
    sigs = [rec(i, text + (" " * (i % 3)), f"bot{i}", published=t0 + timedelta(minutes=7 * i), first_seen=t0 - timedelta(days=1))
            for i in range(12)]
    res = cluster(sigs, OfficialContext(), today=PUB)
    c = res[0]
    assert c.coordination_suspected and c.assessment == SignalAssessment.COORDINATED_AMPLIFICATION
    assert c.n_independent == 0 and c.corroboration != Corroboration.INDEPENDENT_UNOFFICIAL


def test_minhash_similarity_detects_copies():
    a = minhash("Ebola outbreak reported in Beni, many dead, stay safe everyone")
    b = minhash("RT @x: Ebola outbreak reported in Beni, many dead, stay safe everyone!!")
    c = minhash("Market prices for cassava rose sharply in Kisangani this week")
    assert similarity(a, b) > 0.6 > similarity(a, c)
