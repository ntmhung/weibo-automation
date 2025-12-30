import asyncio
from playwright.async_api import async_playwright

AUTH_STATE = "weibo_auth.json"
LOGIN_URL = "https://passport.weibo.com/sso/signin"


async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        ctx = await browser.new_context()
        page = await ctx.new_page()
        await page.goto(LOGIN_URL, wait_until="domcontentloaded")

        print("================================================")
        print("1) Log in to Weibo in the opened browser window.")
        print("2) After you see you're fully logged in,")
        print("   press ENTER here.")
        print("================================================")
        input()

        await ctx.storage_state(path=AUTH_STATE)
        print(f"✅ Saved auth state to: {AUTH_STATE}")
        await browser.close()


asyncio.run(main())
