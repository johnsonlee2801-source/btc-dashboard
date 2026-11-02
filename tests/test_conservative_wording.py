import pathlib
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
PAGES = ("index.html", "eth.html", "distribution-radar.html", "halving.html", "positioning-radar.html",
         "assets/observatory.js")
# 站点只描述公开数据的冷热，不给操作指令。这些词以前出现在首页（「突破 6 → 减仓50%」等）
FORBIDDEN = ("减仓", "加仓", "建仓", "清仓", "抄底", "买入机会", "投资建议由", "持仓监控", "定投", "目标 <", "目标 ≥")


class ConservativeWordingTests(unittest.TestCase):
    def test_pages_do_not_issue_trading_instructions(self):
        for page in PAGES:
            html = (ROOT / page).read_text(encoding="utf-8")
            for word in FORBIDDEN:
                with self.subTest(page=page, word=word):
                    self.assertNotIn(word, html)


if __name__ == "__main__":
    unittest.main()
