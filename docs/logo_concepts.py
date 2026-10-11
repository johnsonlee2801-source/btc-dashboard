import math
def pt(cx, cy, r, deg):
    a = math.radians(deg); return cx + r*math.cos(a), cy + r*math.sin(a)
CX, CY, R = 32, 33.5, 21
x1, y1 = pt(CX, CY, R, 135); x2, y2 = pt(CX, CY, R, 45); mx, my = pt(CX, CY, R, 270)
DEFS = ('<linearGradient id="fhBg" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#1d1d29"/><stop offset="1" stop-color="#0a0a0f"/></linearGradient>'
        '<linearGradient id="fhArc" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#00d4aa"/><stop offset=".5" stop-color="#f7c948"/><stop offset=".78" stop-color="#f7931a"/><stop offset="1" stop-color="#ff4466"/></linearGradient>')
ARC = (f'<path d="M{x1:.2f} {y1:.2f}A{R} {R} 0 1 1 {x2:.2f} {y2:.2f}" fill="none" stroke="url(#fhArc)" stroke-width="6" stroke-linecap="round"/>'
       f'<circle cx="{mx:.2f}" cy="{my:.2f}" r="4.4" fill="#FFF6E9" stroke="#12121a" stroke-width="2.2"/>')
# ₿：主体粗线 + 平头细刻度，避免小尺寸下端点糊成一团
BTC = ('<g fill="none" stroke="#FFF6E9" stroke-linejoin="round">'
       '<path d="M27 25.5V43.5M27 25.5H33.6a4.5 4.5 0 0 1 0 9H27M27 34.5H34.4a4.5 4.5 0 0 1 0 9H27" stroke-width="3.4" stroke-linecap="round"/>'
       '<path d="M29.6 22.4V25.5M33 22.4V25.5M29.6 43.5V46.6M33 43.5V46.6" stroke-width="2.2" stroke-linecap="butt"/></g>')
ETH = ('<g stroke-linejoin="round"><path d="M32 21.5L40 35L32 39.6L24 35Z" fill="#FFF6E9"/>'
       '<path d="M32 41.6L40 37L32 47.5L24 37Z" fill="#FFF6E9" opacity=".75"/></g>')
def mark(glyph, rx=15):
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64"><defs>{DEFS}</defs><rect width="64" height="64" rx="{rx}" fill="url(#fhBg)"/>{ARC}{glyph}</svg>'
open('fh-btc.svg','w').write(mark(BTC)); open('fh-eth.svg','w').write(mark(ETH)); open('fh-btc-square.svg','w').write(mark(BTC, rx=0))
sizes=(16,24,32,48,64,180)
rows=''
for n in ('fh-btc','fh-eth'):
    cells=''.join(f'<div class="c"><img src="{n}.svg" width="{z}" height="{z}"><span>{z}px</span></div>' for z in sizes)
    rows+=f'<div class="row"><div class="bg dark">{cells}</div><div class="bg light">{cells}</div></div>'
# header mock
rows+='''<div class="row"><div class="bg dark hdr"><img src="fh-btc.svg" width="48" height="48"><div><div class="t">FlowHunt｜流程猎人</div><div class="s">BTC 风险温度仪表盘 · 链上数据 / 宏观流动性 / 周期观察</div></div></div>
<div class="bg dark hdr"><img src="fh-eth.svg" width="48" height="48"><div><div class="t">ETH 链上观察</div><div class="s">供给集中度 / 交易所净流量 / 质押结构</div></div></div></div>
<div class="row"><div class="bg tab"><img src="fh-btc.svg" width="16" height="16"> BTC 风险温度仪表盘｜FlowHunt <span style="opacity:.4">×</span></div><div class="bg tab"><img src="fh-eth.svg" width="16" height="16"> ETH 链上观察｜FlowHunt <span style="opacity:.4">×</span></div></div>'''
open('final.html','w').write(f'''<html><head><meta charset="utf-8"><style>
body{{margin:0;padding:24px;background:#222;font-family:'PingFang SC';color:#eee}} .row{{display:flex;gap:16px;align-items:center;margin-bottom:16px}}
.bg{{display:flex;gap:22px;align-items:flex-end;padding:18px 22px;border-radius:12px}} .dark{{background:#0a0a0f}} .light{{background:#f3f3f5;color:#333}}
.c{{display:flex;flex-direction:column;align-items:center;gap:6px;font-size:11px}} .hdr{{align-items:center;gap:14px;width:520px}}
.t{{font-size:20px;font-weight:800}} .s{{font-size:12px;color:#888899;margin-top:3px}} .tab{{background:#35363a;color:#ddd;font-size:13px;align-items:center;gap:8px;padding:9px 14px;border-radius:9px 9px 0 0}}
</style></head><body>{rows}</body></html>''')
