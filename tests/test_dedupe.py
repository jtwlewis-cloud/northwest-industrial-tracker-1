from nwtracker.dedupe import deduplicate, merge_group, unit_tokens
from nwtracker.models import Listing


def L(agent, url, title, pc, size, unit="", status="Availability Unconfirmed", la="Warrington", **kw):
    return Listing(agent=agent, url=url, title=title, property_name=title, address=f"{title}, {pc}", postcode=pc,
                   max_sqft=size, min_sqft=size, unit_number=unit, availability_status=status,
                   local_authority=la, county="Cheshire", **kw)


def test_joint_instruction_merged_with_all_agents():
    ls = [L("JLL", "j1", "Dallam 2, Folly Lane", "WA5 0ND", 49561),
          L("CBRE", "c1", "Dallam Two Folly Lane Warrington", "WA5 0ND", 49561),
          L("B8 Real Estate", "b1", "Dallam 2", "WA5 0ND", 49500)]
    groups, pairs = deduplicate(ls)
    assert len(groups) == 1
    rec = merge_group(groups[0])
    assert set(rec["agents"]) == {"JLL", "CBRE", "B8 Real Estate"}


def test_different_units_same_estate_not_merged():
    ls = [L("JLL", "a", "Unit 3, Stretford Motorway Estate", "M32 0ZH", 9300, "3", la="Trafford"),
          L("Avison Young", "b", "Unit 16, Stretford Motorway Estate", "M32 0ZH", 2960, "16", la="Trafford"),
          L("B8 Real Estate", "c", "Unit 3 Stretford Motorway Estate", "M32 0ZH", 9300, "3", la="Trafford")]
    groups, _ = deduplicate(ls)
    sizes = sorted(len(g) for g in groups)
    assert sizes == [1, 2]


def test_different_buildings_same_postcode_different_size_flagged_not_merged():
    ls = [L("JLL", "a", "Florida Farm Building A", "WA11 9TH", 150000),
          L("DTRE", "b", "Florida Farm Building B", "WA11 9TH", 60000)]
    groups, pairs = deduplicate(ls)
    assert len(groups) == 2
    assert any(p.decision == "ambiguous" for p in pairs)


def test_same_agent_two_pages_same_unit_merged():
    ls = [L("Avison Young", "a", "Unit 16, Stretford Motorway Estate", "M32 0ZH", 2960, "16", la="Trafford"),
          L("Avison Young", "b", "Unit 16, Stretford Motorway Estate", "M32 0ZH", 2960, "16", la="Trafford")]
    groups, _ = deduplicate(ls)
    assert len(groups) == 1
    assert merge_group(groups[0])["same_agent_repeats"] == 1


def test_conflicts_recorded():
    ls = [L("JLL", "a", "Omega 250", "WA5 3XA", 250000, status="Available Now", rent_psf=7.5),
          L("DTRE", "b", "Omega 250", "WA5 3XA", 252000, status="Under Offer", rent_psf=7.75)]
    groups, _ = deduplicate(ls)
    rec = merge_group(groups[0])
    assert rec["availability_status"] == "Under Offer"
    assert any("Availability differs" in c for c in rec["conflicts"])
    assert any("rent" in c.lower() for c in rec["conflicts"])


def test_different_postcodes_never_merged():
    ls = [L("JLL", "a", "Trade Park", "WA5 0ND", 5000), L("B8 Real Estate", "b", "Trade Park", "WA2 8QU", 5000)]
    groups, _ = deduplicate(ls)
    assert len(groups) == 2


def test_unit_tokens():
    assert unit_tokens("1&2") == frozenset({"1", "2"})
    assert unit_tokens("A1-A10") == frozenset({"A1-A10"})
    assert unit_tokens("") == frozenset()


def test_generic_place_words_do_not_create_matches():
    ls = [L("B8 Real Estate", "a", "Premier Park, Acheson Way, Trafford Park", "M17 1AA", 120000, la="Trafford"),
          L("DTRE", "b", "Grand Central, Westinghouse Road, Trafford Park", "M17 1PQ", 16000, la="Trafford")]
    groups, pairs = deduplicate(ls)
    assert len(groups) == 2 and not pairs
