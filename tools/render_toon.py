"""
render_toon.py — 돈수저 4컷 카드툰 렌더러

사용법:
    python render_toon.py spec.json out_dir/
    → out_dir/01.png ~ 04.png (1080x1080, 스레드 캐러셀용)

spec.json 형식 (예시는 sample_spec.json 참고):
{
  "series": "돈수저툰",
  "episode": "EP.1",
  "title": "국내 ETF, 이름만 보고 사면 큰일나!",
  "panels": [
    {"heading": "...", "bubble": "...", "caption": "...", "face": "happy|surprised|think|wink|sad|cool", "prop": "chart_up|chart_down|coin|piggy|doc|magnifier|calendar|none"},
    ... 4개
  ],
  "footer": "저장해두고 다시 보기"
}
"""
from __future__ import annotations
import json, sys, asyncio
from pathlib import Path
from playwright.async_api import async_playwright

HERE = Path(__file__).parent

FACES = {
    "happy":     '<path d="M-22 6 Q0 26 22 6" stroke="#3b2f1e" stroke-width="5" fill="none" stroke-linecap="round"/><circle cx="-24" cy="-8" r="6" fill="#3b2f1e"/><circle cx="24" cy="-8" r="6" fill="#3b2f1e"/><circle cx="-40" cy="10" r="9" fill="#f5a6a0" opacity=".7"/><circle cx="40" cy="10" r="9" fill="#f5a6a0" opacity=".7"/>',
    "surprised": '<ellipse cx="0" cy="12" rx="12" ry="15" fill="#3b2f1e"/><ellipse cx="0" cy="16" rx="7" ry="8" fill="#e4746a"/><circle cx="-24" cy="-10" r="8" fill="#3b2f1e"/><circle cx="24" cy="-10" r="8" fill="#3b2f1e"/><circle cx="-21" cy="-13" r="3" fill="#fff"/><circle cx="27" cy="-13" r="3" fill="#fff"/>',
    "think":     '<path d="M-18 12 Q0 4 18 12" stroke="#3b2f1e" stroke-width="5" fill="none" stroke-linecap="round"/><circle cx="-24" cy="-8" r="6" fill="#3b2f1e"/><circle cx="24" cy="-8" r="6" fill="#3b2f1e"/><path d="M-34 -18 L-14 -26" stroke="#3b2f1e" stroke-width="5" stroke-linecap="round"/><path d="M14 -26 L34 -18" stroke="#3b2f1e" stroke-width="5" stroke-linecap="round"/><circle cx="52" cy="-70" r="7" fill="#3b2f1e" opacity=".5"/><circle cx="66" cy="-92" r="10" fill="#3b2f1e" opacity=".35"/>',
    "wink":      '<path d="M-22 6 Q0 26 22 6" stroke="#3b2f1e" stroke-width="5" fill="none" stroke-linecap="round"/><circle cx="-24" cy="-8" r="6" fill="#3b2f1e"/><path d="M14 -8 Q24 -16 34 -8" stroke="#3b2f1e" stroke-width="5" fill="none" stroke-linecap="round"/><circle cx="-40" cy="10" r="9" fill="#f5a6a0" opacity=".7"/><circle cx="40" cy="10" r="9" fill="#f5a6a0" opacity=".7"/>',
    "sad":       '<path d="M-20 18 Q0 2 20 18" stroke="#3b2f1e" stroke-width="5" fill="none" stroke-linecap="round"/><circle cx="-24" cy="-8" r="6" fill="#3b2f1e"/><circle cx="24" cy="-8" r="6" fill="#3b2f1e"/><path d="M-36 -22 L-14 -16" stroke="#3b2f1e" stroke-width="5" stroke-linecap="round"/><path d="M14 -16 L36 -22" stroke="#3b2f1e" stroke-width="5" stroke-linecap="round"/><path d="M30 0 q4 10 0 18 q-6 -6 0 -18" fill="#7cc4f2"/>',
    "cool":      '<path d="M-18 10 Q0 22 22 8" stroke="#3b2f1e" stroke-width="5" fill="none" stroke-linecap="round"/><rect x="-38" y="-16" width="30" height="18" rx="6" fill="#3b2f1e"/><rect x="8" y="-16" width="30" height="18" rx="6" fill="#3b2f1e"/><path d="M-8 -10 L8 -10" stroke="#3b2f1e" stroke-width="4"/>',
}

PROPS = {
    "none": "",
    "chart_up":   '<g transform="translate(0,0)"><rect x="-70" y="-60" width="140" height="120" rx="14" fill="#fff" stroke="#3b2f1e" stroke-width="4"/><polyline points="-50,40 -20,10 5,25 45,-30" fill="none" stroke="#e0503f" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/><polygon points="45,-30 28,-28 42,-14" fill="#e0503f"/></g>',
    "chart_down": '<g><rect x="-70" y="-60" width="140" height="120" rx="14" fill="#fff" stroke="#3b2f1e" stroke-width="4"/><polyline points="-50,-30 -20,0 5,-12 45,40" fill="none" stroke="#3a7bd5" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/><polygon points="45,40 28,38 42,24" fill="#3a7bd5"/></g>',
    "coin":       '<g><circle cx="0" cy="0" r="58" fill="#f3c34d" stroke="#3b2f1e" stroke-width="4"/><circle cx="0" cy="0" r="42" fill="none" stroke="#c9952a" stroke-width="4"/><text x="0" y="16" text-anchor="middle" font-size="44" font-weight="900" fill="#3b2f1e">₩</text></g>',
    "piggy":      '<g><ellipse cx="0" cy="8" rx="64" ry="48" fill="#f7b6c2" stroke="#3b2f1e" stroke-width="4"/><circle cx="-56" cy="0" r="18" fill="#f7b6c2" stroke="#3b2f1e" stroke-width="4"/><circle cx="-60" cy="-2" r="3" fill="#3b2f1e"/><circle cx="-52" cy="-2" r="3" fill="#3b2f1e"/><circle cx="-30" cy="-12" r="4" fill="#3b2f1e"/><rect x="-14" y="-46" width="28" height="8" rx="4" fill="#3b2f1e"/><rect x="-40" y="44" width="14" height="18" fill="#f7b6c2" stroke="#3b2f1e" stroke-width="4"/><rect x="26" y="44" width="14" height="18" fill="#f7b6c2" stroke="#3b2f1e" stroke-width="4"/></g>',
    "doc":        '<g><rect x="-50" y="-64" width="100" height="128" rx="10" fill="#fff" stroke="#3b2f1e" stroke-width="4"/><rect x="-32" y="-40" width="64" height="10" rx="5" fill="#3b2f1e"/><rect x="-32" y="-16" width="50" height="8" rx="4" fill="#bbb"/><rect x="-32" y="4" width="58" height="8" rx="4" fill="#bbb"/><rect x="-32" y="24" width="40" height="8" rx="4" fill="#bbb"/><circle cx="30" cy="40" r="16" fill="#e0503f"/><path d="M22 40 l6 6 l12 -14" stroke="#fff" stroke-width="4" fill="none"/></g>',
    "magnifier":  '<g><circle cx="-12" cy="-12" r="42" fill="#dff0ff" stroke="#3b2f1e" stroke-width="8"/><path d="M18 18 L56 56" stroke="#3b2f1e" stroke-width="14" stroke-linecap="round"/></g>',
    "calendar":   '<g><rect x="-60" y="-50" width="120" height="110" rx="12" fill="#fff" stroke="#3b2f1e" stroke-width="4"/><rect x="-60" y="-50" width="120" height="30" rx="12" fill="#e0503f"/><rect x="-60" y="-32" width="120" height="12" fill="#e0503f"/><rect x="-36" y="-62" width="10" height="24" rx="5" fill="#3b2f1e"/><rect x="26" y="-62" width="10" height="24" rx="5" fill="#3b2f1e"/><text x="0" y="36" text-anchor="middle" font-size="44" font-weight="900" fill="#3b2f1e">D-1</text></g>',
}


def mascot(face: str, scale: float = 1.0, tilt: int = 0) -> str:
    f = FACES.get(face, FACES["happy"])
    return f'''
<svg viewBox="-120 -170 240 340" width="{int(240*scale)}" height="{int(340*scale)}" xmlns="http://www.w3.org/2000/svg">
  <g transform="rotate({tilt})">
    <!-- handle -->
    <path d="M-30 20 L-22 140 Q0 160 22 140 L30 20 Z" fill="#f2c85b" stroke="#3b2f1e" stroke-width="6" stroke-linejoin="round"/>
    <path d="M-10 40 L-6 120" stroke="#fff" stroke-width="7" stroke-linecap="round" opacity=".8"/>
    <!-- leaf -->
    <path d="M16 108 q28 -10 34 16 q-28 10 -34 -16z" fill="#6fbf5a" stroke="#3b2f1e" stroke-width="4"/>
    <path d="M18 110 q14 4 30 12" stroke="#3b2f1e" stroke-width="3" fill="none"/>
    <!-- bowl -->
    <ellipse cx="0" cy="-60" rx="88" ry="98" fill="#f5cd63" stroke="#3b2f1e" stroke-width="6"/>
    <ellipse cx="0" cy="-60" rx="70" ry="80" fill="#f7d77a"/>
    <path d="M-40 -130 q40 -14 62 8" stroke="#fff" stroke-width="10" fill="none" stroke-linecap="round" opacity=".9"/>
    <!-- face -->
    <g transform="translate(0,-52)">{f}</g>
  </g>
</svg>'''


TEMPLATE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<style>
  @page { margin:0 }
  html,body{margin:0;padding:0}
  body{width:1080px;height:1080px;background:#fff7e6;font-family:"Noto Sans CJK KR","Noto Sans KR",sans-serif;color:#3b2f1e;position:relative;overflow:hidden}
  .frame{position:absolute;inset:34px;background:#fffdf7;border:6px solid #3b2f1e;border-radius:38px;box-shadow:12px 12px 0 #3b2f1e}
  .badge{position:absolute;top:-26px;left:50px;background:#e0503f;color:#fff;font-weight:900;font-size:30px;padding:8px 26px;border-radius:999px;border:5px solid #3b2f1e;letter-spacing:1px}
  .ep{position:absolute;top:-22px;right:50px;background:#f5cd63;color:#3b2f1e;font-weight:900;font-size:26px;padding:6px 22px;border-radius:999px;border:5px solid #3b2f1e}
  .no{position:absolute;bottom:26px;right:40px;font-weight:900;font-size:30px;color:#3b2f1e;opacity:.55}
  .heading{position:absolute;left:70px;right:70px;top:80px;font-size:{{HSIZE}}px;line-height:1.22;font-weight:900;text-align:center;word-break:keep-all}
  .heading em{font-style:normal;color:#e0503f;background:linear-gradient(transparent 55%,#ffe27a 55%)}
  .bubble{position:absolute;left:80px;right:80px;top:{{BTOP}}px;background:#fff;border:5px solid #3b2f1e;border-radius:30px;padding:30px 36px;font-size:{{BSIZE}}px;line-height:1.4;font-weight:700;text-align:center;word-break:keep-all;box-shadow:8px 8px 0 #f5cd63}
  .bubble:after{content:"";position:absolute;left:50%;bottom:-30px;margin-left:-20px;border:20px solid transparent;border-top-color:#3b2f1e;border-bottom:0}
  .bubble:before{content:"";position:absolute;left:50%;bottom:-22px;margin-left:-16px;border:16px solid transparent;border-top-color:#fff;border-bottom:0;z-index:2}
  .stage{position:absolute;left:0;right:0;bottom:70px;height:420px;display:flex;align-items:flex-end;justify-content:center;gap:40px}
  .caption{position:absolute;left:80px;right:80px;bottom:44px;text-align:center;font-size:30px;font-weight:700;color:#7a6a4d}
  .ground{position:absolute;left:120px;right:120px;bottom:88px;height:22px;background:#f5cd63;border-radius:999px;opacity:.6}
  .prop{margin-bottom:14px}
  .footer{position:absolute;left:80px;right:80px;bottom:40px;text-align:center;font-size:34px;font-weight:900;color:#e0503f}
</style></head><body>
<div class="frame">
  <div class="badge">{{SERIES}}</div>
  <div class="ep">{{EP}}</div>
  <div class="heading">{{HEADING}}</div>
  {{BUBBLE}}
  <div class="ground"></div>
  <div class="stage">{{PROP}}{{MASCOT}}</div>
  {{CAPTION}}
  {{FOOTER}}
  <div class="no">{{NO}}/4</div>
</div>
</body></html>"""


def esc(s: str) -> str:
    return (s or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace("\n", "<br>")


def highlight(s: str) -> str:
    # *강조* 문법 → <em>
    out, parts = [], esc(s).split("*")
    for i, p in enumerate(parts):
        out.append(f"<em>{p}</em>" if i % 2 else p)
    return "".join(out)


def build_html(spec: dict, idx: int) -> str:
    p = spec["panels"][idx]
    heading = highlight(p.get("heading", ""))
    hlen = len(p.get("heading", ""))
    hsize = 64 if hlen <= 14 else 54 if hlen <= 22 else 46
    bubble_txt = p.get("bubble", "")
    blen = len(bubble_txt)
    bsize = 40 if blen <= 30 else 34 if blen <= 55 else 30
    btop = 290 if hlen else 140
    bubble = f'<div class="bubble">{esc(bubble_txt)}</div>' if bubble_txt else ""
    prop = PROPS.get(p.get("prop", "none"), "")
    prop_html = f'<svg class="prop" viewBox="-80 -80 160 160" width="220" height="220">{prop}</svg>' if prop else ""
    caption = f'<div class="caption">{esc(p["caption"])}</div>' if p.get("caption") else ""
    footer = f'<div class="footer">{esc(spec.get("footer",""))}</div>' if (idx == 3 and spec.get("footer") and not p.get("caption")) else ""
    html = TEMPLATE
    for k, v in {
        "{{SERIES}}": esc(spec.get("series", "돈수저툰")),
        "{{EP}}": esc(spec.get("episode", "")),
        "{{HEADING}}": heading, "{{HSIZE}}": str(hsize),
        "{{BUBBLE}}": bubble, "{{BTOP}}": str(btop), "{{BSIZE}}": str(bsize),
        "{{PROP}}": prop_html,
        "{{MASCOT}}": mascot(p.get("face", "happy"), scale=1.15, tilt=p.get("tilt", 0)),
        "{{CAPTION}}": caption, "{{FOOTER}}": footer, "{{NO}}": str(idx + 1),
    }.items():
        html = html.replace(k, v)
    return html


async def render(spec_path: Path, out_dir: Path) -> list[Path]:
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    assert len(spec["panels"]) == 4, "panels는 정확히 4개여야 합니다"
    out_dir.mkdir(parents=True, exist_ok=True)
    outs = []
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        page = await browser.new_page(viewport={"width": 1080, "height": 1080}, device_scale_factor=1)
        for i in range(4):
            await page.set_content(build_html(spec, i), wait_until="load")
            await page.wait_for_timeout(150)
            out = out_dir / f"{i+1:02d}.png"
            await page.screenshot(path=str(out), type="png", full_page=False)
            outs.append(out)
        await browser.close()
    return outs


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    outs = asyncio.run(render(Path(sys.argv[1]), Path(sys.argv[2])))
    for o in outs:
        print(o)
