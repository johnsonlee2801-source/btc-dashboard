#!/usr/bin/env python3
"""Set each sitemap <lastmod> to the date its page file was last committed, and drop duplicate <loc>s.

URL -> file follows vercel.json rewrites (and the stock host's "/" -> "/stock" redirect);
anything else maps to <path>/index.html. Run after editing pages:  python3 scripts/update_sitemap_lastmod.py
"""
import json, re, subprocess
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
SITEMAPS = ("sitemap.xml", "sitemap-stock.xml")


def page_file(path, rewrites):
    if path in ("", "/"):
        return "index.html"
    if path in rewrites:
        return rewrites[path].lstrip("/")
    return path.strip("/") + "/index.html"


def last_commit_date(rel):
    out = subprocess.run(["git", "-C", str(ROOT), "log", "-1", "--format=%cs", "--", rel],
                         capture_output=True, text=True).stdout.strip()
    return out or None


def main():
    rewrites = {r["source"]: r["destination"] for r in json.loads((ROOT / "vercel.json").read_text())["rewrites"]}
    for name in SITEMAPS:
        p = ROOT / name
        text = p.read_text(encoding="utf-8")
        seen, changed = set(), 0

        def fix(m):
            nonlocal changed
            block = m.group(0)
            loc = re.search(r"<loc>([^<]+)</loc>", block).group(1)
            if loc in seen:  # 重复的 <loc>：保留第一条（优先级更高的那条）
                changed += 1
                return ""
            seen.add(loc)
            rel = page_file(urlparse(loc).path, rewrites)
            date = last_commit_date(rel) if (ROOT / rel).exists() else None
            if not date:
                print(f"  ! {loc}: 找不到页面文件 {rel}，lastmod 保持不变")
                return block
            new = re.sub(r"<lastmod>[^<]*</lastmod>", f"<lastmod>{date}</lastmod>", block)
            changed += new != block
            return new

        text = re.sub(r"[ \t]*<url>.*?</url>\n?", fix, text, flags=re.S)
        p.write_text(text, encoding="utf-8")
        print(f"{name}: {len(seen)} URLs, {changed} changed")


if __name__ == "__main__":
    main()
