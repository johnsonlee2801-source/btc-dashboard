#!/usr/bin/env python3
"""Render the share images (1200x630) from their HTML sources with headless Chrome via Playwright."""
import asyncio, io, pathlib
from playwright.async_api import async_playwright
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parents[1]

# HTML source in docs/ -> image at the site root
IMAGES = {"og-image.html": "og-image.jpg", "og-eth.html": "og-eth.jpg", "og-halving.html": "og-halving.jpg"}

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome")
        page = await browser.new_page(viewport={"width": 1200, "height": 630}, device_scale_factor=1)
        for src, out in IMAGES.items():
            await page.goto((ROOT / "docs" / src).as_uri(), wait_until="load")
            png = await page.screenshot(type="png")
            Image.open(io.BytesIO(png)).convert("RGB").save(ROOT / out, "JPEG", quality=88, optimize=True, progressive=True)
            print("wrote", out, (ROOT / out).stat().st_size, "bytes")
        await browser.close()

asyncio.run(main())
