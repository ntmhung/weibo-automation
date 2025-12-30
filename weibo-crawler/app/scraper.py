import json
import os
import re
import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from playwright.async_api import async_playwright, Browser, BrowserContext

AUTH_STATE = "/data/weibo_auth.json"
STATE_FILE = "/data/state.json"

API_BASE = "https://m.weibo.cn/api/container/getIndex"

# Rate limiting (seconds)
WEIBO_SLEEP_REQUEST = float(os.getenv("WEIBO_SLEEP_REQUEST", "1.2"))
WEIBO_SLEEP_ACCOUNT = float(os.getenv("WEIBO_SLEEP_ACCOUNT", "2.5"))


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


async def polite_sleep(seconds: float) -> None:
    if seconds and seconds > 0:
        await asyncio.sleep(seconds)


def strip_html(s: str) -> str:
    s = s or ""
    s = re.sub(r"<br\s*/?>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", "", s)
    return re.sub(r"\n{3,}", "\n\n", s).strip()


def load_json(path: str, default: Any) -> Any:
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def save_json(path: str, data: Any) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


async def new_context(browser: Browser) -> BrowserContext:
    # Mobile-ish UA improves consistency.
    ua = (
        "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) "
        "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 "
        "Mobile/15E148 Safari/604.1"
    )

    if os.path.exists(AUTH_STATE):
        try:
            return await browser.new_context(
                storage_state=AUTH_STATE,
                user_agent=ua,
                viewport={"width": 390, "height": 844},
                locale="en-US",
            )
        except Exception:
            pass

    return await browser.new_context(
        user_agent=ua,
        viewport={"width": 390, "height": 844},
        locale="en-US",
    )


async def api_get_json(
    ctx: BrowserContext, url: str, retries: int = 3
) -> Dict[str, Any]:
    last_err: Optional[Exception] = None

    for i in range(retries):
        try:
            resp = await ctx.request.get(
                url,
                headers={
                    "Accept": "application/json, text/plain, */*",
                    "Referer": "https://m.weibo.cn/",
                },
                timeout=30000,
            )

            # Read raw bytes to avoid Playwright utf-8 decoding crashes
            raw = await resp.body()

            if not raw:
                raise RuntimeError(f"Empty response (status={resp.status})")

            # Quick HTML / captcha detection
            prefix = raw[:200].decode("utf-8", errors="ignore").lstrip()
            if prefix.startswith("<"):
                raise RuntimeError(f"Non-JSON HTML response (status={resp.status})")

            # Detect charset from headers
            ctype = (resp.headers.get("content-type") or "").lower()
            m = re.search(r"charset=([a-z0-9_\-]+)", ctype)
            charset = m.group(1) if m else None

            # Decode with fallbacks (Weibo sometimes returns GBK/GB18030)
            candidates = []
            if charset:
                candidates.append(charset)
            candidates.extend(["utf-8", "utf-8-sig", "gb18030", "gbk"])

            text: Optional[str] = None
            for enc in candidates:
                try:
                    text = raw.decode(enc)
                    break
                except UnicodeDecodeError:
                    continue

            # Absolute last resort
            if text is None:
                text = raw.decode("utf-8", errors="replace")

            text_stripped = text.lstrip()
            if not text_stripped or text_stripped.startswith("<"):
                raise RuntimeError(
                    f"Non-JSON response after decode (status={resp.status})"
                )

            data = json.loads(text)

            # polite pacing after successful request
            await polite_sleep(WEIBO_SLEEP_REQUEST)
            return data

        except Exception as e:
            last_err = e
            if i < retries - 1:
                await asyncio.sleep(1.2 * (2**i))

    raise RuntimeError(f"API request failed after retries: {last_err}")


def extract_containerid(profile_json: Dict[str, Any], uid: str) -> str:
    """
    Usually 107603<uid>. We also try to read from tabs.
    """
    guess = f"107603{uid}"
    data = profile_json.get("data") or {}

    tabs = (data.get("tabsInfo") or {}).get("tabs") or []
    for t in tabs:
        cid = t.get("containerid")
        if isinstance(cid, str) and "107603" in cid:
            return cid

    return guess


def parse_cards(cards: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    posts: List[Dict[str, Any]] = []
    for c in cards:
        mblog = c.get("mblog")
        if not isinstance(mblog, dict):
            continue

        post_id = str(mblog.get("id") or "")
        text_html = mblog.get("text") or ""
        text_cn = strip_html(text_html)
        created_at = mblog.get("created_at") or ""
        scheme = mblog.get("scheme") or ""

        permalink = f"https://m.weibo.cn/detail/{post_id}" if post_id else ""

        # Sometimes empty text due to pinned cards, ads, etc.
        if not text_cn.strip():
            continue

        posts.append(
            {
                "post_id": post_id,
                "created_at": created_at,
                "text_cn": text_cn,
                "text_html": text_html,
                "scheme_url": scheme,
                "permalink": permalink,
                "raw": mblog,
            }
        )
    return posts


async def fetch_posts_for_uid(
    ctx: BrowserContext, uid: str, max_pages: int
) -> Tuple[str, List[Dict[str, Any]], int]:
    profile_url = f"{API_BASE}?type=uid&value={uid}"
    profile_json = await api_get_json(ctx, profile_url)
    containerid = extract_containerid(profile_json, uid)

    all_posts: List[Dict[str, Any]] = []
    pages_fetched = 0

    for page in range(1, max_pages + 1):
        url = f"{API_BASE}?containerid={containerid}&page={page}"
        data = await api_get_json(ctx, url)
        cards = (data.get("data") or {}).get("cards") or []
        posts = parse_cards(cards)
        pages_fetched += 1

        if not posts:
            break

        all_posts.extend(posts)

        # extra pacing between pages (in addition to api_get_json pacing)
        await polite_sleep(WEIBO_SLEEP_REQUEST)

    return containerid, all_posts, pages_fetched


def apply_incremental(
    account_key: str, posts: List[Dict[str, Any]], state: Dict[str, Any], max_posts: int
):
    """
    Returns (new_posts, newest_post_id, last_seen_before).
    - last_seen is per account_key
    - stop when we hit last_seen (so we don't resend)
    - update state to the newest post_id from current feed
    """
    last_seen_map = state.get("last_seen_post_id") or {}
    last_seen = last_seen_map.get(account_key)

    new_posts: List[Dict[str, Any]] = []
    newest_post_id: Optional[str] = None

    for p in posts:
        pid = p.get("post_id") or ""
        if not newest_post_id and pid:
            newest_post_id = pid

        if last_seen and pid == last_seen:
            break

        new_posts.append(p)
        if len(new_posts) >= max_posts:
            break

    return new_posts, newest_post_id, last_seen


async def scrape(
    accounts: List[Dict[str, str]], max_pages: int, max_posts: int
) -> Dict[str, Any]:
    state = load_json(STATE_FILE, default={"last_seen_post_id": {}, "updated_at": None})

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await new_context(browser)

        results: List[Dict[str, Any]] = []

        for acc in accounts:
            key = acc.get("key", "unknown")
            uid = str(acc.get("uid", "")).strip()

            if not uid:
                results.append(
                    {
                        "account_key": key,
                        "uid": uid,
                        "fetched_at": utc_now_iso(),
                        "error": "Missing uid",
                        "posts": [],
                    }
                )
                # pacing between accounts even on invalid config
                await polite_sleep(WEIBO_SLEEP_ACCOUNT)
                continue

            try:
                containerid, posts, pages_fetched = await fetch_posts_for_uid(
                    ctx, uid, max_pages=max_pages
                )

                new_posts, newest_post_id, last_seen_before = apply_incremental(
                    account_key=key,
                    posts=posts,
                    state=state,
                    max_posts=max_posts,
                )

                # Update state marker to newest post_id (if available)
                if newest_post_id:
                    state.setdefault("last_seen_post_id", {})[key] = newest_post_id

                results.append(
                    {
                        "account_key": key,
                        "uid": uid,
                        "containerid": containerid,
                        "fetched_at": utc_now_iso(),
                        "pages_fetched": pages_fetched,
                        "last_seen_before": last_seen_before,
                        "newest_post_id": newest_post_id,
                        "posts": new_posts,
                    }
                )

            except Exception as e:
                results.append(
                    {
                        "account_key": key,
                        "uid": uid,
                        "fetched_at": utc_now_iso(),
                        "error": str(e),
                        "posts": [],
                    }
                )

            # pacing between accounts (success or fail)
            await polite_sleep(WEIBO_SLEEP_ACCOUNT)

        await ctx.close()
        await browser.close()

    state["updated_at"] = utc_now_iso()
    save_json(STATE_FILE, state)

    return {"items": results, "generated_at": utc_now_iso()}
