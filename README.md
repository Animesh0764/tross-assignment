# LinkedIn Profile API

Give it a LinkedIn profile URL, get the profile back as structured JSON.

No browser, no headless Chrome, no Puppeteer. The service talks directly to LinkedIn's
internal **Voyager** REST API over HTTPS, authenticating with a session cookie from a
logged-in account.

```
GET /profile?url=https://www.linkedin.com/in/williamhgates/
```

---

## Approach

LinkedIn's web app is a client-side SPA. Everything the profile page renders comes from a
JSON API at `https://www.linkedin.com/voyager/api/...`, which the browser calls with the
same cookies the page was loaded with. So there is nothing to scrape from HTML — you just
have to speak Voyager's dialect.

Three things make a Voyager call succeed:

| Requirement | How it's satisfied |
|---|---|
| `li_at` session cookie | copied from a logged-in browser session, injected server-side |
| CSRF token | Voyager requires `csrf-token` to equal the `JSESSIONID` cookie value (minus quotes) |
| Rest.li protocol header | `x-restli-protocol-version: 2.0.0`, plus a plausible `x-li-track` client fingerprint and a browser UA |

Get those right and the endpoints answer with plain JSON.

**Request flow** (`linkedin.py`):

1. `vanity_from_url()` pulls the vanity slug out of the URL (`/in/<vanity>`, country
   subdomains and `?trk=` tracking params included).
2. `GET /identity/profiles/{vanity}/profileView` — one call, the bulk of the payload:
   name, headline, summary, location, industry, images, and the `positionView`,
   `educationView`, `certificationView`, `languageView`, `volunteerExperienceView`,
   `projectView`, `publicationView`, `honorView`, `courseView`, `organizationView`
   collections.
3. `GET /identity/profiles/{vanity}/skills?count=100` — `profileView` truncates skills to
   the top few; this returns the full list.
4. `GET /identity/profiles/{vanity}/profileContactInfo` — websites, Twitter, email/phone
   where the member has made them visible.

Steps 3 and 4 are best-effort: if either fails the profile is still returned.

Images arrive as LinkedIn `VectorImage` records — a `rootUrl` plus artifacts at several
resolutions. `_img()` concatenates the root with the largest artifact so you get a usable
absolute URL rather than a fragment.

Results are cached in memory per vanity (`CACHE_TTL`, default 1h). One profile fetched
twice is one round trip to LinkedIn — the point is to keep request volume off the account,
since throttling is the real failure mode here.

**Fallback.** On accounts where the legacy `profileView` route is disabled, the client
falls back to the Rest.li `dash` route
(`/identity/dash/profiles?q=memberIdentity&decorationId=...FullProfileWithEntities-101`)
and returns basics with `"partial": true`. See *Known limitations*.

---

## Frontend

`GET /` serves a one-file demo page (`static/index.html`, no build step, no framework):
paste a profile URL and a session's `li_at` / `JSESSIONID`, get the JSON back rendered in
the page. It exists so the hosted link is self-contained — no `curl` needed to try it.

Cookies typed into the page are sent as `X-LI-AT` / `X-JSESSIONID` request headers and
used for that one request only; the server holds nothing in a database. Deliberately not
using the server's own configured account for public traffic — see `/profile` below and
*Known limitations*.

## API

### `GET /profile`

| Param | In | Required | Description |
|---|---|---|---|
| `url` | query | yes | Profile URL (`https://www.linkedin.com/in/<vanity>/`) or a bare vanity |
| `refresh` | query | no | `true` bypasses the cache |
| `X-API-Key` | header | only if `API_KEY` is set on the server | Shared secret |
| `X-LI-AT`, `X-JSESSIONID` | header | no | Caller-supplied session, overrides the server's `LI_AT`/`JSESSIONID` for this request. Responses using caller-supplied cookies skip the shared cache. |

**200**

```json
{
  "cached": false,
  "data": {
    "public_id": "williamhgates",
    "profile_url": "https://www.linkedin.com/in/williamhgates/",
    "urn": "urn:li:fs_miniProfile:ACoAAA8BYqEB...",
    "first_name": "Bill",
    "last_name": "Gates",
    "full_name": "Bill Gates",
    "headline": "Chair, Gates Foundation and Founder, Breakthrough Energy",
    "about": "Co-chair of the Bill & Melinda Gates Foundation...",
    "location": "Seattle, Washington, United States",
    "country": "United States",
    "industry": "Philanthropy",
    "student": false,
    "profile_picture": "https://media.licdn.com/dms/image/.../profile-displayphoto-shrink_800_800.jpg",
    "background_image": "https://media.licdn.com/dms/image/.../profile-displaybackgroundimage-shrink_350_1400.jpg",
    "experience": [
      {
        "title": "Co-chair",
        "company": "Bill & Melinda Gates Foundation",
        "company_url": "https://www.linkedin.com/company/1206579/",
        "company_logo": "https://media.licdn.com/dms/image/.../logo.png",
        "employment_type": null,
        "location": "Seattle, Washington",
        "description": "...",
        "start_date": "2000-01",
        "end_date": null,
        "is_current": true
      }
    ],
    "education": [
      {
        "school": "Harvard University",
        "school_logo": "https://media.licdn.com/dms/image/.../logo.png",
        "degree": null,
        "field_of_study": null,
        "grade": null,
        "activities": null,
        "description": null,
        "start_date": "1973",
        "end_date": "1975",
        "is_current": false
      }
    ],
    "skills": ["Philanthropy", "Public Speaking"],
    "certifications": [
      {"name": "...", "authority": "...", "license_number": null, "url": null,
       "start_date": "2021-05", "end_date": null, "is_current": true}
    ],
    "languages": [{"name": "English", "proficiency": "NATIVE_OR_BILINGUAL"}],
    "volunteering": [],
    "projects": [],
    "publications": [],
    "honors": [],
    "courses": [],
    "organizations": [],
    "contact": {
      "public_profile_url": "https://www.linkedin.com/in/williamhgates/",
      "email": null,
      "birthday": null,
      "websites": [{"url": "https://www.gatesnotes.com", "label": "PERSONAL"}],
      "twitter": ["BillGates"],
      "phone_numbers": []
    },
    "fetched_at": 1756400000
  }
}
```

Every field is nullable — LinkedIn omits whatever the member hasn't filled in, and list
fields come back as `[]` rather than disappearing, so consumers don't need defensive
checks.

**Errors** — `{"error": "..."}` with a meaningful status:

| Status | Meaning |
|---|---|
| 400 | `url` isn't a LinkedIn profile URL |
| 401 | Missing/invalid `X-API-Key`, or LinkedIn rejected the session cookie (expired `li_at`) |
| 404 | Profile doesn't exist, or isn't visible to the backing account |
| 429 | LinkedIn is throttling this account — back off |
| 502 | Upstream unreachable or returned something unparseable |

### `GET /health`

`{"ok": true, "configured": true, "cached": 3}` — `configured` reports whether cookies are
present, without leaking them. Use it as the platform health check.

Interactive docs (Swagger) are at `/docs`.

---

## Setup

```bash
git clone <repo> && cd tross-linkedin-api
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                              # then fill in the two cookies
uvicorn main:app --reload --env-file .env
```

`--env-file` is what loads the cookies (uvicorn reads it via python-dotenv, bundled with
`uvicorn[standard]`). On a host like Render or Fly you set real environment variables
instead and drop the flag.

```bash
curl "http://localhost:8000/profile?url=https://www.linkedin.com/in/williamhgates/"
python test_parse.py     # parser check, no network, no pytest
```

### Getting the cookies

In a browser logged into LinkedIn: **DevTools → Application → Cookies →
`https://www.linkedin.com`**, and copy two values into `.env`:

- `li_at` → `LI_AT` — the session token.
- `JSESSIONID` → `JSESSIONID` — copy it **without** the surrounding quotes; the code
  re-adds them for the cookie and reuses the bare value as the `csrf-token` header.

Use a throwaway or secondary account. Cookies live only in the environment — `.env` is
gitignored and nothing is committed.

### Environment

| Var | Required | Default | Purpose |
|---|---|---|---|
| `LI_AT` | yes | — | LinkedIn session cookie |
| `JSESSIONID` | yes | — | Doubles as the CSRF token |
| `API_KEY` | no | unset | If set, `/profile` requires `X-API-Key` |
| `CACHE_TTL` | no | `3600` | Per-profile cache lifetime, seconds |
| `PORT` | no | `8000` | Injected by most hosts |

---

## Deploy

The `Dockerfile` is the whole deployment story; it binds `$PORT` and every platform below
terminates TLS for you.

**Render** — New → Web Service → connect the repo → Docker → add `LI_AT`, `JSESSIONID`,
`API_KEY` as environment variables (mark them secret) → health check path `/health`.

**Fly.io** — `fly launch --no-deploy`, then
`fly secrets set LI_AT=... JSESSIONID=... API_KEY=...`, then `fly deploy`.

**Railway / Cloud Run** — same shape: point at the Dockerfile, set the three variables as
secrets, deploy.

Run a single instance, or move the cache to Redis: the in-process dict isn't shared across
workers, so N workers means up to N times the LinkedIn traffic.

---

## Known limitations

- **This uses a private, undocumented LinkedIn API.** LinkedIn's User Agreement §8.2
  prohibits scraping and unauthorized automated access; using it, even with your own
  cookies, risks that account being rate-limited or restricted. Use a throwaway account,
  not your primary one — the demo page says so, but it bears repeating here.
- **The account is the rate limit.** Voyager is metered per member. A few hundred profile
  views an hour is fine; sustained bulk traffic gets the account soft-blocked (HTTP 429/999
  → the API returns 429). The cache exists to make repeat lookups free; anything
  high-volume needs a pool of accounts and a scheduler, which is out of scope here.
- **Cookies expire.** `li_at` lasts roughly a year but dies early on password change or
  logout-everywhere, and `JSESSIONID` rotates faster. Expiry surfaces as a 401 with an
  explicit message; the fix is to re-copy both values. A refresh loop that re-authenticates
  from credentials is doable but adds a CAPTCHA/2FA path I deliberately left out.
- **Visibility is the backing account's visibility.** Out-of-network profiles can return
  fewer fields or 404, exactly as they would in that account's browser. Nothing here
  bypasses privacy settings — it reads what the logged-in member can already see.
- **`profileView` is legacy.** It's the richest single call and still serves most sessions,
  but LinkedIn is migrating to GraphQL (`/voyager/api/graphql?queryId=...`) whose query IDs
  rotate with each web release and would need re-pinning to stay current. The `dash`
  fallback covers sessions where `profileView` is already off, returning basics with
  `"partial": true` — that's the honest ceiling of a fixed fallback, and full parity would
  mean tracking the GraphQL query IDs.
- **Recommendations, posts/activity, follower counts, and endorsement counts** aren't
  included — separate endpoints, and not in the requested field list.
- **In-memory cache** dies with the process and isn't shared between instances.
- Written for the assignment. Scraping conflicts with LinkedIn's ToS; use it on an account
  you're willing to lose.
