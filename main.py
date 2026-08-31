import os
import time

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse, JSONResponse

from linkedin import LinkedInError, Voyager, vanity_from_url

API_KEY = os.getenv("API_KEY")
CACHE_TTL = int(os.getenv("CACHE_TTL", "3600"))
_cache: dict[str, tuple[float, dict]] = {}  # ponytail: in-process dict; swap for Redis if >1 worker

app = FastAPI(
    title="LinkedIn Profile API",
    description="Give it a LinkedIn profile URL, get structured JSON. "
                "Reverse-engineered Voyager endpoints, no browser.",
    version="1.0.0",
)


@app.get("/", include_in_schema=False)
def root():
    return FileResponse("static/index.html")


@app.get("/health")
def health():
    return {"ok": True, "configured": bool(os.getenv("LI_AT") and os.getenv("JSESSIONID")),
            "cached": len(_cache)}


@app.get("/profile")
def profile(
    url: str = Query(..., description="LinkedIn profile URL or vanity name"),
    refresh: bool = Query(False, description="Bypass the cache"),
    x_api_key: str | None = Header(None),
    x_li_at: str | None = Header(None, description="Caller-supplied li_at cookie, overrides server default"),
    x_jsessionid: str | None = Header(None, description="Caller-supplied JSESSIONID, overrides server default"),
):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(401, "Invalid or missing X-API-Key")

    # A caller-supplied session never touches the server's own account, and its
    # results aren't pooled into the shared cache (different sessions can see
    # different visibility of the same profile).
    byo_creds = bool(x_li_at and x_jsessionid)
    li_at = x_li_at or os.getenv("LI_AT", "")
    jsessionid = x_jsessionid or os.getenv("JSESSIONID", "")

    key = vanity_from_url(url).lower()
    if not byo_creds:
        hit = _cache.get(key)
        if hit and not refresh and time.time() - hit[0] < CACHE_TTL:
            return {"cached": True, "data": hit[1]}

    client = Voyager(li_at, jsessionid)
    try:
        data = client.fetch(url)
    finally:
        client.close()

    if not byo_creds:
        _cache[key] = (time.time(), data)
    return {"cached": False, "data": data}


@app.exception_handler(LinkedInError)
def _linkedin_error(_, exc: LinkedInError):
    return JSONResponse(status_code=exc.status, content={"error": exc.message})
