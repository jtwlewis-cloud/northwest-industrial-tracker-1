from nwtracker import config
from nwtracker.geo import is_candidate_nw


def test_prefilter():
    assert is_candidate_nw("WA5 0ND") and is_candidate_nw("CA14 4ED") and is_candidate_nw("SY14 8AA")
    assert not is_candidate_nw("LS10 1AA") and not is_candidate_nw("LL13 7TF") and not is_candidate_nw("")


def test_district_mapping_covers_requested_areas():
    m = config.DISTRICT_TO_COUNTY
    assert m["Warrington"] == m["Halton"] == m["Cheshire East"] == m["Cheshire West and Chester"] == "Cheshire"
    assert m["Wirral"] == "Merseyside" and m["Cumberland"] == "Cumbria" and m["Blackpool"] == "Lancashire"
    assert "Flintshire" not in m and "High Peak" not in m and "Calderdale" not in m


def test_size_band():
    assert config.size_band(9999) == "Under 10,000 sq ft"
    assert config.size_band(10000) == "10,000–25,000 sq ft"
    assert config.size_band(250000) == "Over 250,000 sq ft"
    assert config.size_band(None) == "Size Not Disclosed"
