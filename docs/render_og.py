#!/usr/bin/env python3
"""Render docs/og-image.html to og-image.jpg (1200x630) with headless Chrome via Playwright."""
import asyncio, io, pathlib
from playwright.async_api import async_playwright
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome")
        page = await browser.new_page(viewport={"width": 1200, "height": 630}, device_scale_factor=1)
        await page.goto((ROOT / "docs" / "og-image.html").as_uri(), wait_until="load")
        png = await page.screenshot(type="png")
        await browser.close()
    Image.open(io.BytesIO(png)).convert("RGB").save(ROOT / "og-image.jpg", "JPEG", quality=88, optimize=True, progressive=True)
    print("wrote og-image.jpg", (ROOT / "og-image.jpg").stat().st_size, "bytes")

asyncio.run(main())
