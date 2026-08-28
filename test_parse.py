"""Runnable check: python test_parse.py  (no pytest needed)"""
from linkedin import LinkedInError, parse_profile_view, vanity_from_url

SAMPLE = {
    "profile": {
        "firstName": "Ada", "lastName": "Lovelace",
        "headline": "Mathematician | Analytical Engine",
        "summary": "First programmer.",
        "locationName": "London", "geoCountryName": "United Kingdom",
        "industryName": "Computer Software",
        "miniProfile": {
            "publicIdentifier": "ada-lovelace",
            "entityUrn": "urn:li:fs_miniProfile:ACoAAAxyz",
            "occupation": "Mathematician",
            "picture": {"com.linkedin.common.VectorImage": {
                "rootUrl": "https://media.licdn.com/dms/image/x/",
                "artifacts": [
                    {"width": 100, "fileIdentifyingUrlPathSegment": "small.jpg"},
                    {"width": 800, "fileIdentifyingUrlPathSegment": "big.jpg"},
                ]}},
        },
    },
    "positionView": {"elements": [{
        "title": "Analyst", "companyName": "Analytical Engine Co",
        "locationName": "London", "description": "Notes G.",
        "timePeriod": {"startDate": {"month": 6, "year": 1842}},
        "company": {"miniCompany": {"name": "Analytical Engine Co",
                                    "entityUrn": "urn:li:fs_miniCompany:1234"}},
    }]},
    "educationView": {"elements": [{"schoolName": "Home tutoring",
                                    "degreeName": "Mathematics",
                                    "timePeriod": {"startDate": {"year": 1830},
                                                   "endDate": {"year": 1835}}}]},
    "certificationView": {"elements": [{"name": "Cert", "authority": "Body"}]},
    "languageView": {"elements": [{"name": "English", "proficiency": "NATIVE_OR_BILINGUAL"}]},
    "skillView": {"elements": [{"name": "Algorithms"}]},
}


def main():
    assert vanity_from_url("https://www.linkedin.com/in/ada-lovelace/") == "ada-lovelace"
    assert vanity_from_url("http://linkedin.com/in/ada?trk=x") == "ada"
    assert vanity_from_url("https://in.linkedin.com/in/ada-2") == "ada-2"
    assert vanity_from_url("ada-lovelace") == "ada-lovelace"
    try:
        vanity_from_url("https://example.com/foo/bar")
        raise AssertionError("expected LinkedInError")
    except LinkedInError as e:
        assert e.status == 400

    p = parse_profile_view(SAMPLE, contact=None, skills=["Algorithms", "Notation"])
    assert p["full_name"] == "Ada Lovelace"
    assert p["headline"].startswith("Mathematician")
    assert p["about"] == "First programmer."
    assert p["location"] == "London"
    assert p["profile_picture"] == "https://media.licdn.com/dms/image/x/big.jpg"  # largest artifact
    exp = p["experience"][0]
    assert exp["start_date"] == "1842-06" and exp["end_date"] is None and exp["is_current"]
    assert exp["company_url"] == "https://www.linkedin.com/company/1234/"
    edu = p["education"][0]
    assert edu["start_date"] == "1830" and edu["end_date"] == "1835" and not edu["is_current"]
    assert p["skills"] == ["Algorithms", "Notation"]  # supplementary call wins
    assert p["certifications"][0]["authority"] == "Body"
    assert p["languages"][0]["proficiency"] == "NATIVE_OR_BILINGUAL"
    assert p["projects"] == [] and p["contact"] is None

    # empty payload must not explode
    empty = parse_profile_view({})
    assert empty["full_name"] is None and empty["experience"] == []
    print("ok")


if __name__ == "__main__":
    main()
