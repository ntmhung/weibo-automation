import json
import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import JSONResponse

from scraper import scrape

APP_SECRET = os.getenv("SCRAPE_TOKEN", "change_me")
ACCOUNTS_FILE = "/app/accounts.json"
AUTH_STATE = "/data/weibo_auth.json"
STATE_FILE = "/data/state.json"

app = FastAPI(title="Weibo Playwright (m.weibo.cn) service", version="1.2")


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/status")
def status():
    return {
        "auth_state_exists": os.path.exists(AUTH_STATE),
        "state_exists": os.path.exists(STATE_FILE),
        "auth_state_path": AUTH_STATE,
        "state_path": STATE_FILE,
    }


@app.get("/scrape")
async def scrape_endpoint(token: str = Query(...)):
    if token != APP_SECRET:
        raise HTTPException(status_code=403, detail="Forbidden")

    if not os.path.exists(ACCOUNTS_FILE):
        raise HTTPException(status_code=500, detail="accounts.json not found")

    with open(ACCOUNTS_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)

    accounts = cfg.get("accounts", [])
    max_pages = int(cfg.get("max_pages_per_account", 1))
    max_posts = int(cfg.get("max_posts_per_account", 5))

    result = await scrape(accounts, max_pages=max_pages, max_posts=max_posts)

    # Force UTF-8 JSON output to clients like n8n
    return JSONResponse(
        content=result,
        media_type="application/json; charset=utf-8",
    )
