from nwtracker import extract as ex


def test_eaves_variants():
    assert ex.eaves("12m eaves height") == 12.0
    assert ex.eaves("Eaves height of 7.6m (10m at the roof apex)") == 7.6
    assert ex.eaves("8 metre eaves (10 metres to apex)") == 8.0
    assert ex.eaves("Circa. 4.5 metres to the underside of the haunch") == 4.5
    assert ex.eaves("8.4m clear internal height") == 8.4
    assert ex.eaves("eaves of 20ft") == 6.1
    assert ex.eaves("No height information") is None


def test_doors():
    t = "10 x dock level and 1 x level loading door"
    assert ex.dock_doors(t) == 10 and ex.level_doors(t) == 1
    assert ex.level_doors("11 level access loading doors") == 11
    assert ex.level_doors("2 x electronically operated drive-in loading doors") == 2
    assert ex.dock_doors("4 dock level loading doors") == 4
    assert ex.dock_doors("two dock levellers") == 2
    assert ex.dock_doors("roller shutter door") is None


def test_site_power_epc_breeam():
    assert ex.site_acres("site area extends to 1.29 Hectares (3.2 Acres)") == 3.2
    assert ex.site_acres("on a site area of 2.89 acres") == 2.89
    assert ex.power("175 KVA power") == "175 kVA"
    assert ex.power("3 phase electricity") == "Three-phase (capacity not stated)"
    assert ex.epc("The building has an EPC rating of A-20.") == "A"
    assert ex.epc("EPC rating: Exempt") == "Exempt"
    assert ex.breeam("Targeting BREEAM Excellent") == "Excellent (target)"
    assert ex.breeam("BREEAM Very Good") == "Very Good"


def test_rent_and_price():
    assert ex.rent("Rent £7.95 per sq ft") == (7.95, "£7.95 psf")
    assert ex.rent("£6.50 - £7.25 psf") == (6.5, "£6.50–£7.25 psf")
    assert ex.rent("To Let - £120,000 per annum")[1] == "£120,000 pa"
    assert ex.rent("nothing here") == (None, "")
    assert "£460,000" in ex.price("Offers in the region of £460,000 for the freehold")


def test_sizes_units_estates():
    assert ex.parse_size_range("49,561 - 101,000 ft²") == (49561, 101000)
    assert ex.parse_size_range("Size: 3,719 - 7,780 Sq Ft") == (3719, 7780)
    assert ex.parse_size_range("45,351 sq ft") == (45351, 45351)
    assert ex.unit_number("Unit 4B, Stretton Green") == "4B"
    assert ex.unit_number("Units 1&2, Rossendale Road") == "1&2"
    assert ex.estate_name("Unit D3 Broadoak Business Park, Ashburton Road West") == "Broadoak Business Park"
    assert ex.estate_name("Penlaw House, 2 Eagle Park Drive, Warrington") == ""
    assert ex.find_postcode("Charon Way, Warrington, WA5 7YD") == "WA5 7YD"
    assert ex.outcode("WA5 7YD") == "WA5"


def test_accommodation_schedule():
    t = "| Ground Warehouse | 16,345 | 1,518.50 | Available | Ground Office | 1,061 | 98.57 | 1st Office | 1,061 | 98.57 |"
    assert ex.accommodation_areas(t) == (16345, 2122)


def test_availability_classification():
    c = ex.classify_availability
    assert c("Under Offer", "", "", "Existing")[0] == "Under Offer"
    assert c("To Let", "Units available for immediate occupation", ex.availability_date("immediate occupation"), "Existing")[0] == "Available Now"
    assert c("To Let", "New build. On site now - available Q3 2099", "Q3 2099", "New Build")[0] == "Under Construction"
    assert c("To Let", "Refurbishment due to complete Q1 2099", "Q1 2099", "Existing – Refurbished")[0] == "Available at a Future Date"
    assert c("To Let", "Design and build opportunities up to 200,000 sq ft", "", "Design & Build")[0] == "Proposed / Design and Build"
    assert c("To Let", "Warehouse to let", "", "Existing")[0] == "Availability Unconfirmed"
    st, conf = c("To Let", "available August 2020", "August 2020", "Existing")
    assert st == "Availability Unconfirmed" and "has passed" in conf[0]
    st, conf = c("To Let", "This unit is now under offer", "", "Existing")
    assert conf  # label vs text conflict retained


def test_build_status():
    assert ex.build_status("New build warehouse unit") == "New Build"
    assert ex.build_status("Comprehensively refurbished unit") == "Existing – Refurbished"
    assert ex.build_status("Design & build opportunities") == "Design & Build"
    assert ex.build_status("Steel portal frame warehouse") == "Existing"


def test_apply_text_never_overwrites():
    from nwtracker.models import Listing
    l = Listing(agent="A", url="u", eaves_m=10.0, epc="B")
    ex.apply_text(l, "6m eaves, EPC rating C, 2 dock doors", "web")
    assert l.eaves_m == 10.0 and l.epc == "B" and l.dock_doors == 2
