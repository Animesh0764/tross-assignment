"""Voyager client + parsers. No browser: raw HTTPS calls to LinkedIn's internal API."""
import re
import time
from urllib.parse import unquote

import httpx

BASE = "https://www.linkedin.com/voyager/api"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")


class LinkedInError(Exception):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


def vanity_from_url(url: str) -> str:
    """linkedin.com/in/<vanity>/ -> <vanity>. Also accepts a bare vanity."""
    url = unquote((url or "").strip())
    m = re.search(r"linkedin\.com/(?:[a-z]{2,3}/)?in/([^/?#\s]+)", url, re.I)
    if m:
        return m.group(1)
    if re.fullmatch(r"[\w\-%.À-￿]{3,120}", url):  # bare slug
        return url
    raise LinkedInError(400, "Not a LinkedIn profile URL (expected .../in/<vanity>)")


# --- field helpers -----------------------------------------------------------

def _date(d):
    if not d or not d.get("year"):
        return None
    return f"{d['year']}-{d['month']:02d}" if d.get("month") else str(d["year"])


def _period(e):
    tp = e.get("timePeriod") or {}
    start, end = _date(tp.get("startDate")), _date(tp.get("endDate"))
    return {"start_date": start, "end_date": end, "is_current": bool(start) and not end}


def _img(vector):
    """VectorImage -> highest-resolution absolute URL."""
    if not vector:
        return None
    v = vector.get("com.linkedin.common.VectorImage", vector)
    root, arts = v.get("rootUrl"), v.get("artifacts") or []
    if not root or not arts:
        return None
    best = max(arts, key=lambda a: a.get("width") or 0)
    return root + best.get("fileIdentifyingUrlPathSegment", "")


def _elements(view, fn):
    return [fn(e) for e in (view or {}).get("elements", [])]


def _company_url(e):
    urn = ((e.get("company") or {}).get("miniCompany") or {}).get("entityUrn", "")
    cid = urn.rsplit(":", 1)[-1]
    return f"https://www.linkedin.com/company/{cid}/" if cid else None


# --- parsers -----------------------------------------------------------------

def _experience(e):
    mini = (e.get("company") or {}).get("miniCompany") or {}
    return {
        "title": e.get("title"),
        "company": e.get("companyName") or mini.get("name"),
        "company_url": _company_url(e),
        "company_logo": _img(mini.get("logo")),
        "employment_type": e.get("employmentTypeUrn", "").rsplit(":", 1)[-1] or None,
        "location": e.get("locationName"),
        "description": e.get("description"),
        **_period(e),
    }


def _education(e):
    mini = (e.get("school") or {}).get("miniSchool") or {}
    return {
        "school": e.get("schoolName") or mini.get("schoolName"),
        "school_logo": _img(mini.get("logo")),
        "degree": e.get("degreeName"),
        "field_of_study": e.get("fieldOfStudy"),
        "grade": e.get("grade"),
        "activities": e.get("activities"),
        "description": e.get("description"),
        **_period(e),
    }


def _certification(e):
    return {
        "name": e.get("name"),
        "authority": e.get("authority"),
        "license_number": e.get("licenseNumber"),
        "url": e.get("url"),
        **_period(e),
    }


def _language(e):
    return {"name": e.get("name"), "proficiency": e.get("proficiency")}


def _volunteer(e):
    return {
        "role": e.get("role"),
        "organization": e.get("companyName"),
        "cause": e.get("cause"),
        "description": e.get("description"),
        **_period(e),
    }


def _project(e):
    return {
        "name": e.get("title"),
        "description": e.get("description"),
        "url": e.get("url"),
        **_period(e),
    }


def _publication(e):
    return {
        "name": e.get("name"),
        "publisher": e.get("publisher"),
        "description": e.get("description"),
        "url": e.get("url"),
        "date": _date((e.get("date") or {})),
    }


def _honor(e):
    return {
        "title": e.get("title"),
        "issuer": e.get("issuer"),
        "description": e.get("description"),
        "date": _date(e.get("issueDate")),
    }


def _course(e):
    return {"name": e.get("name"), "number": e.get("number")}


def _organization(e):
    return {"name": e.get("name"), "position": e.get("position"),
            "description": e.get("description"), **_period(e)}


def parse_profile_view(pv: dict, contact: dict | None = None,
                       skills: list | None = None) -> dict:
    p = pv.get("profile") or {}
    mini = p.get("miniProfile") or {}
    first, last = p.get("firstName") or "", p.get("lastName") or ""
    public_id = p.get("publicIdentifier") or mini.get("publicIdentifier")
    location = p.get("locationName") or (p.get("geoLocationName"))

    out = {
        "public_id": public_id,
        "profile_url": f"https://www.linkedin.com/in/{public_id}/" if public_id else None,
        "urn": mini.get("entityUrn") or p.get("entityUrn"),
        "first_name": first or None,
        "last_name": last or None,
        "full_name": f"{first} {last}".strip() or None,
        "headline": p.get("headline") or mini.get("occupation"),
        "about": p.get("summary"),
        "location": location,
        "country": p.get("geoCountryName"),
        "industry": p.get("industryName"),
        "student": p.get("student"),
        "profile_picture": _img(mini.get("picture")),
        "background_image": _img(mini.get("backgroundImage") or p.get("backgroundImage")),
        "experience": _elements(pv.get("positionView"), _experience),
        "education": _elements(pv.get("educationView"), _education),
        "skills": skills if skills is not None
                  else [e.get("name") for e in (pv.get("skillView") or {}).get("elements", [])],
        "certifications": _elements(pv.get("certificationView"), _certification),
        "languages": _elements(pv.get("languageView"), _language),
        "volunteering": _elements(pv.get("volunteerExperienceView"), _volunteer),
        "projects": _elements(pv.get("projectView"), _project),
        "publications": _elements(pv.get("publicationView"), _publication),
        "honors": _elements(pv.get("honorView"), _honor),
        "courses": _elements(pv.get("courseView"), _course),
        "organizations": _elements(pv.get("organizationView"), _organization),
        "contact": parse_contact(contact) if contact else None,
        "fetched_at": int(time.time()),
    }
    return out


def parse_contact(c: dict) -> dict:
    return {
        "public_profile_url": c.get("vanityName") and
                              f"https://www.linkedin.com/in/{c['vanityName']}/",
        "email": c.get("emailAddress"),
        "birthday": _date(c.get("birthDateOn")),
        "websites": [{"url": w.get("url"),
                      "label": ((w.get("type") or {}).get(
                          "com.linkedin.voyager.identity.profile.StandardWebsite") or {}
                      ).get("category")
                      or ((w.get("type") or {}).get(
                          "com.linkedin.voyager.identity.profile.CustomWebsite") or {}
                      ).get("label")}
                     for w in c.get("websites") or []],
        "twitter": [t.get("name") for t in c.get("twitterHandles") or []],
        "phone_numbers": [{"number": n.get("number"), "type": n.get("type")}
                          for n in c.get("phoneNumbers") or []],
    }


# --- client ------------------------------------------------------------------

class Voyager:
    """Authenticated by reusing a browser session cookie (li_at + JSESSIONID)."""

    def __init__(self, li_at: str, jsessionid: str, timeout: float = 25.0):
        if not li_at or not jsessionid:
            raise LinkedInError(500, "LI_AT / JSESSIONID not configured on the server")
        csrf = jsessionid.strip().strip('"')
        self.client = httpx.Client(
            base_url=BASE,
            timeout=timeout,
            follow_redirects=False,
            cookies={"li_at": li_at, "JSESSIONID": f'"{csrf}"'},
            headers={
                "csrf-token": csrf,
                "user-agent": UA,
                "accept-language": "en-US,en;q=0.9",
                "x-restli-protocol-version": "2.0.0",
                "x-li-lang": "en_US",
                "x-li-track": ('{"clientVersion":"1.13.9","mpVersion":"1.13.9",'
                               '"osName":"web","timezoneOffset":0,"timezone":"UTC",'
                               '"deviceFormFactor":"DESKTOP","mpName":"voyager-web"}'),
                "referer": "https://www.linkedin.com/feed/",
            },
        )

    def close(self):
        self.client.close()

    def _get(self, path: str, accept: str | None = None, **params):
        headers = {"accept": accept} if accept else None
        try:
            r = self.client.get(path, params=params, headers=headers)
        except httpx.HTTPError as e:
            raise LinkedInError(502, f"Upstream request failed: {e}")
        if r.status_code in (401, 403):
            raise LinkedInError(401, "LinkedIn rejected the session cookie — refresh LI_AT/JSESSIONID")
        if r.status_code == 404:
            raise LinkedInError(404, "Profile not found or not visible to this account")
        if r.status_code in (429, 999):
            raise LinkedInError(429, "Throttled by LinkedIn — back off and retry later")
        if r.status_code >= 300:
            raise LinkedInError(502, f"Unexpected upstream status {r.status_code}")
        try:
            return r.json()
        except ValueError:
            raise LinkedInError(502, "Upstream returned non-JSON (session likely invalid)")

    # endpoints
    def profile_view(self, vanity: str) -> dict:
        return self._get(f"/identity/profiles/{vanity}/profileView")

    def skills(self, vanity: str) -> list:
        data = self._get(f"/identity/profiles/{vanity}/skills", count=100)
        return [e.get("name") for e in data.get("elements", []) if e.get("name")]

    def contact_info(self, vanity: str) -> dict:
        return self._get(f"/identity/profiles/{vanity}/profileContactInfo")

    def dash_profile(self, vanity: str) -> dict:
        """Fallback for accounts where the legacy profileView route is disabled."""
        return self._get(
            "/identity/dash/profiles",
            accept="application/vnd.linkedin.normalized+json+2.1",
            q="memberIdentity", memberIdentity=vanity,
            decorationId="com.linkedin.voyager.dash.deco.identity.profile."
                         "FullProfileWithEntities-101",
        )

    def fetch(self, url_or_vanity: str) -> dict:
        vanity = vanity_from_url(url_or_vanity)
        try:
            pv = self.profile_view(vanity)
        except LinkedInError as e:
            if e.status not in (404, 502):
                raise
            return parse_dash(self.dash_profile(vanity), vanity)
        # best-effort extras: never fail the whole request over them
        skills = contact = None
        try:
            skills = self.skills(vanity)
        except LinkedInError:
            pass
        try:
            contact = self.contact_info(vanity)
        except LinkedInError:
            pass
        return parse_profile_view(pv, contact, skills)


def parse_dash(data: dict, vanity: str) -> dict:
    """Minimal mapping of the dash/normalized shape (basics only)."""
    els = data.get("elements") or data.get("data", {}).get("elements") or []
    inc = data.get("included") or []
    p = els[0] if els and isinstance(els[0], dict) and els[0].get("firstName") else next(
        (i for i in inc if i.get("$type", "").endswith("dash.identity.profile.Profile")), {})
    first, last = p.get("firstName") or "", p.get("lastName") or ""
    return {
        "public_id": p.get("publicIdentifier") or vanity,
        "profile_url": f"https://www.linkedin.com/in/{p.get('publicIdentifier') or vanity}/",
        "urn": p.get("entityUrn"),
        "first_name": first or None,
        "last_name": last or None,
        "full_name": f"{first} {last}".strip() or None,
        "headline": p.get("headline"),
        "about": (p.get("summary") or None),
        "location": (p.get("geoLocation") or {}).get("postalCode")
                    or (p.get("location") or {}).get("countryCode"),
        "country": None, "industry": None, "student": None,
        "profile_picture": _img((p.get("profilePicture") or {}).get("displayImageReference", {}).get("vectorImage")),
        "background_image": None,
        "experience": [], "education": [], "skills": [], "certifications": [],
        "languages": [], "volunteering": [], "projects": [], "publications": [],
        "honors": [], "courses": [], "organizations": [], "contact": None,
        "partial": True,  # legacy profileView unavailable for this session
        "fetched_at": int(time.time()),
    }
