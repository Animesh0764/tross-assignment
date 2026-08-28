import os
import time

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import JSONResponse

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


def _client() -> Voyager:
    return Voyager(os.getenv("LI_AT", ""), os.getenv("JSESSIONID", ""))


@app.get("/", include_in_schema=False)
def root():
    return {"service": "linkedin-profile-api", "docs": "/docs",
            "usage": "GET /profile?url=https://www.linkedin.com/in/<vanity>/"}


@app.get("/health")
def health():
    return {"ok": True, "configured": bool(os.getenv("LI_AT") and os.getenv("JSESSIONID")),
            "cached": len(_cache)}


@app.get("/profile")
def profile(
    url: str = Query(..., description="LinkedIn profile URL or vanity name"),
    refresh: bool = Query(False, description="Bypass the cache"),
    x_api_key: str | None = Header(None),
):
    if API_KEY and x_api_key != API_KEY:
        raise HTTPException(401, "Invalid or missing X-API-Key")

    key = vanity_from_url(url).lower()
    hit = _cache.get(key)
    if hit and not refresh and time.time() - hit[0] < CACHE_TTL:
        return {"cached": True, "data": hit[1]}

    client = _client()
    try:
        data = client.fetch(url)
    finally:
        client.close()

    _cache[key] = (time.time(), data)
    return {"cached": False, "data": data}


@app.exception_handler(LinkedInError)
def _linkedin_error(_, exc: LinkedInError):
    return JSONResponse(status_code=exc.status, content={"error": exc.message})
