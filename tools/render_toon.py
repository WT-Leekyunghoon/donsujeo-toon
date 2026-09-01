"""
render_toon.py — 돈수저 4컷 카드툰 렌더러 (v4 — 그림체 디벨롭)

사용법:
    python render_toon.py spec.json out_dir/
    → out_dir/01.png ~ 04.png (1080x1080, 스레드 캐러셀용)

spec.json 형식은 v2 와 동일 (sample_spec.json 참고) — 러너 인터페이스 변경 없음.
v3 변경점(그림만): 그라데이션 음영, 팔 포즈, 바닥 그림자, 배경 도트 패턴,
눈 하이라이트, 소품 입체감(drop-shadow), 말풍선·타이포 다듬기.
"""
from __future__ import annotations
import json, sys, asyncio
from pathlib import Path
from playwright.async_api import async_playwright

HERE = Path(__file__).parent

# 눈: 하이라이트 포함. 컷마다 감정 흐름 표현.
_EYE = '<circle cx="{x}" cy="{y}" r="6.5" fill="#3b2f1e"/><circle cx="{hx}" cy="{hy}" r="2.4" fill="#fff"/>'


def _eyes(y=-8):
    return (_EYE.format(x=-24, y=y, hx=-22, hy=y - 2.5) +
            _EYE.format(x=24, y=y, hx=26, hy=y - 2.5))


FACES = {
    "happy":     _eyes() + '<path d="M-22 6 Q0 26 22 6" stroke="#3b2f1e" stroke-width="5.5" fill="none" stroke-linecap="round"/><path d="M-30 -20 Q-24 -25 -17 -21 M17 -21 Q24 -25 30 -20" stroke="#3b2f1e" stroke-width="4" fill="none" stroke-linecap="round"/><circle cx="-40" cy="10" r="10" fill="#f5a6a0" opacity=".65"/><circle cx="40" cy="10" r="10" fill="#f5a6a0" opacity=".65"/>',
    "surprised": '<ellipse cx="0" cy="12" rx="12" ry="15" fill="#3b2f1e"/><ellipse cx="0" cy="16" rx="7" ry="8" fill="#e4746a"/><circle cx="-24" cy="-10" r="8.5" fill="#3b2f1e"/><circle cx="24" cy="-10" r="8.5" fill="#3b2f1e"/><circle cx="-21" cy="-13" r="3.2" fill="#fff"/><circle cx="27" cy="-13" r="3.2" fill="#fff"/><path d="M-32 -26 Q-24 -31 -16 -27 M16 -27 Q24 -31 32 -26" stroke="#3b2f1e" stroke-width="4" fill="none" stroke-linecap="round"/>',
    "think":     _eyes() + '<path d="M-18 12 Q0 4 18 12" stroke="#3b2f1e" stroke-width="5.5" fill="none" stroke-linecap="round"/><path d="M-34 -18 L-14 -26" stroke="#3b2f1e" stroke-width="5" stroke-linecap="round"/><path d="M14 -26 L34 -18" stroke="#3b2f1e" stroke-width="5" stroke-linecap="round"/><circle cx="70" cy="-88" r="7" fill="#3b2f1e" opacity=".45"/><circle cx="88" cy="-112" r="10" fill="#3b2f1e" opacity=".3"/>',
    "wink":      _EYE.format(x=-24, y=-8, hx=-22, hy=-10.5) + '<path d="M-22 6 Q0 26 22 6" stroke="#3b2f1e" stroke-width="5.5" fill="none" stroke-linecap="round"/><path d="M14 -8 Q24 -16 34 -8" stroke="#3b2f1e" stroke-width="5.5" fill="none" stroke-linecap="round"/><circle cx="-40" cy="10" r="10" fill="#f5a6a0" opacity=".65"/><circle cx="40" cy="10" r="10" fill="#f5a6a0" opacity=".65"/>',
    "sad":       _eyes() + '<path d="M-20 18 Q0 2 20 18" stroke="#3b2f1e" stroke-width="5.5" fill="none" stroke-linecap="round"/><path d="M-36 -22 L-14 -16" stroke="#3b2f1e" stroke-width="5" stroke-linecap="round"/><path d="M14 -16 L36 -22" stroke="#3b2f1e" stroke-width="5" stroke-linecap="round"/><path d="M30 0 q4 10 0 18 q-6 -6 0 -18" fill="#7cc4f2"/>',
    "cool":      '<path d="M-18 10 Q0 22 22 8" stroke="#3b2f1e" stroke-width="5.5" fill="none" stroke-linecap="round"/><rect x="-38" y="-16" width="30" height="18" rx="6" fill="#3b2f1e"/><rect x="8" y="-16" width="30" height="18" rx="6" fill="#3b2f1e"/><path d="M-32 -12 l8 4" stroke="#7a92ad" stroke-width="3" stroke-linecap="round"/><path d="M14 -12 l8 4" stroke="#7a92ad" stroke-width="3" stroke-linecap="round"/><path d="M-8 -10 L8 -10" stroke="#3b2f1e" stroke-width="4"/>',
    "excited":   '<path d="M-30 4 Q-22 -6 -14 4" stroke="#3b2f1e" stroke-width="5.5" fill="none" stroke-linecap="round"/><path d="M14 4 Q22 -6 30 4" stroke="#3b2f1e" stroke-width="5.5" fill="none" stroke-linecap="round"/><path d="M-16 12 Q0 30 16 12 Z" fill="#3b2f1e"/><path d="M-9 20 Q0 26 9 20 Z" fill="#e4746a"/><circle cx="-42" cy="12" r="10" fill="#f5a6a0" opacity=".65"/><circle cx="42" cy="12" r="10" fill="#f5a6a0" opacity=".65"/>',
    "angry":     _eyes(-6) + '<path d="M-20 16 Q0 4 20 16" stroke="#3b2f1e" stroke-width="5.5" fill="none" stroke-linecap="round"/><path d="M-36 -26 L-14 -18" stroke="#3b2f1e" stroke-width="5" stroke-linecap="round"/><path d="M14 -18 L36 -26" stroke="#3b2f1e" stroke-width="5" stroke-linecap="round"/><path d="M46 -34 l6 -10 M52 -22 l10 -6 M50 -46 l2 -12" stroke="#e0503f" stroke-width="4" stroke-linecap="round"/>',
    "sleepy":    '<path d="M-30 -6 Q-24 2 -16 -4" stroke="#3b2f1e" stroke-width="5.5" fill="none" stroke-linecap="round"/><path d="M16 -4 Q24 2 30 -6" stroke="#3b2f1e" stroke-width="5.5" fill="none" stroke-linecap="round"/><ellipse cx="0" cy="14" rx="7" ry="9" fill="#3b2f1e"/><text x="44" y="-40" font-size="30" font-weight="900" fill="#8a7a5c">z</text><text x="58" y="-62" font-size="24" font-weight="900" fill="#8a7a5c">z</text>',
    "love":      '<path d="M-22 8 Q0 26 22 8" stroke="#3b2f1e" stroke-width="5.5" fill="none" stroke-linecap="round"/><path d="M-24 -14 c-6 -8 -18 -2 -14 6 c3 6 10 8 14 12 c4 -4 11 -6 14 -12 c4 -8 -8 -14 -14 -6z" fill="#e0503f"/><path d="M24 -14 c-6 -8 -18 -2 -14 6 c3 6 10 8 14 12 c4 -4 11 -6 14 -12 c4 -8 -8 -14 -14 -6z" fill="#e0503f"/><circle cx="-27" cy="-16" r="2.6" fill="#fff" opacity=".85"/><circle cx="21" cy="-16" r="2.6" fill="#fff" opacity=".85"/><circle cx="-42" cy="12" r="10" fill="#f5a6a0" opacity=".65"/><circle cx="42" cy="12" r="10" fill="#f5a6a0" opacity=".65"/>',
}

# 감정별 팔 포즈 (그릇 양옆에서 나오는 짧은 팔 + 손)
_HAND = 'fill="#f7d77a" stroke="#3b2f1e" stroke-width="5"'
ARMS = {
    "up":    f'<path d="M-82 -50 Q-112 -66 -122 -96" stroke="#3b2f1e" stroke-width="12" fill="none" stroke-linecap="round"/><circle cx="-124" cy="-100" r="13" {_HAND}/>'
             f'<path d="M82 -50 Q112 -66 122 -96" stroke="#3b2f1e" stroke-width="12" fill="none" stroke-linecap="round"/><circle cx="124" cy="-100" r="13" {_HAND}/>',
    "down":  f'<path d="M-84 -36 Q-104 -18 -108 4" stroke="#3b2f1e" stroke-width="12" fill="none" stroke-linecap="round"/><circle cx="-109" cy="9" r="13" {_HAND}/>'
             f'<path d="M84 -36 Q104 -18 108 4" stroke="#3b2f1e" stroke-width="12" fill="none" stroke-linecap="round"/><circle cx="109" cy="9" r="13" {_HAND}/>',
    "chin":  f'<path d="M-84 -36 Q-104 -18 -108 4" stroke="#3b2f1e" stroke-width="12" fill="none" stroke-linecap="round"/><circle cx="-109" cy="9" r="13" {_HAND}/>'
             f'<path d="M84 -40 Q108 -44 96 -66" stroke="#3b2f1e" stroke-width="12" fill="none" stroke-linecap="round"/><circle cx="93" cy="-72" r="13" {_HAND}/>',
    "wave":  f'<path d="M-84 -36 Q-104 -18 -108 4" stroke="#3b2f1e" stroke-width="12" fill="none" stroke-linecap="round"/><circle cx="-109" cy="9" r="13" {_HAND}/>'
             f'<path d="M82 -50 Q112 -66 122 -96" stroke="#3b2f1e" stroke-width="12" fill="none" stroke-linecap="round"/><circle cx="124" cy="-100" r="13" {_HAND}/>',
}
FACE_ARMS = {"happy": "wave", "excited": "up", "love": "up", "wink": "wave",
             "surprised": "up", "think": "chin", "sad": "down", "cool": "down",
             "angry": "down", "sleepy": "down"}

PROPS = {
    "none": "",
    "chart_up":   '<g><rect x="-70" y="-60" width="140" height="120" rx="14" fill="#fff" stroke="#3b2f1e" stroke-width="4"/><path d="M-56 -30 h112 M-56 0 h112 M-56 30 h112" stroke="#eee6d4" stroke-width="2"/><polyline points="-50,40 -20,10 5,25 45,-30" fill="none" stroke="#e0503f" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/><polygon points="45,-30 28,-28 42,-14" fill="#e0503f"/></g>',
    "chart_down": '<g><rect x="-70" y="-60" width="140" height="120" rx="14" fill="#fff" stroke="#3b2f1e" stroke-width="4"/><path d="M-56 -30 h112 M-56 0 h112 M-56 30 h112" stroke="#eee6d4" stroke-width="2"/><polyline points="-50,-30 -20,0 5,-12 45,40" fill="none" stroke="#3a7bd5" stroke-width="7" stroke-linecap="round" stroke-linejoin="round"/><polygon points="45,40 28,38 42,24" fill="#3a7bd5"/></g>',
    "coin":       '<g><circle cx="0" cy="0" r="58" fill="url(#gCoin)" stroke="#3b2f1e" stroke-width="4"/><circle cx="0" cy="0" r="42" fill="none" stroke="#c9952a" stroke-width="4"/><path d="M-34 -34 q22 -14 44 -6" stroke="#fff" stroke-width="7" fill="none" stroke-linecap="round" opacity=".8"/><text x="0" y="16" text-anchor="middle" font-size="44" font-weight="900" fill="#3b2f1e">₩</text></g>',
    "piggy":      '<g><ellipse cx="0" cy="8" rx="64" ry="48" fill="#f7b6c2" stroke="#3b2f1e" stroke-width="4"/><path d="M-36 -22 q30 -16 62 -2" stroke="#fff" stroke-width="7" fill="none" stroke-linecap="round" opacity=".65"/><circle cx="-56" cy="0" r="18" fill="#f7b6c2" stroke="#3b2f1e" stroke-width="4"/><circle cx="-60" cy="-2" r="3" fill="#3b2f1e"/><circle cx="-52" cy="-2" r="3" fill="#3b2f1e"/><circle cx="-30" cy="-12" r="4" fill="#3b2f1e"/><rect x="-14" y="-46" width="28" height="8" rx="4" fill="#3b2f1e"/><rect x="-40" y="44" width="14" height="18" fill="#f7b6c2" stroke="#3b2f1e" stroke-width="4"/><rect x="26" y="44" width="14" height="18" fill="#f7b6c2" stroke="#3b2f1e" stroke-width="4"/></g>',
    "doc":        '<g><rect x="-50" y="-64" width="100" height="128" rx="10" fill="#fff" stroke="#3b2f1e" stroke-width="4"/><rect x="-32" y="-40" width="64" height="10" rx="5" fill="#3b2f1e"/><rect x="-32" y="-16" width="50" height="8" rx="4" fill="#cfc6b2"/><rect x="-32" y="4" width="58" height="8" rx="4" fill="#cfc6b2"/><rect x="-32" y="24" width="40" height="8" rx="4" fill="#cfc6b2"/><circle cx="30" cy="40" r="16" fill="#e0503f"/><path d="M22 40 l6 6 l12 -14" stroke="#fff" stroke-width="4" fill="none"/></g>',
    "magnifier":  '<g><circle cx="-12" cy="-12" r="42" fill="#dff0ff" stroke="#3b2f1e" stroke-width="8"/><path d="M-34 -30 q14 -14 34 -8" stroke="#fff" stroke-width="7" fill="none" stroke-linecap="round" opacity=".9"/><path d="M18 18 L56 56" stroke="#3b2f1e" stroke-width="14" stroke-linecap="round"/></g>',
    "calendar":   '<g><rect x="-60" y="-50" width="120" height="110" rx="12" fill="#fff" stroke="#3b2f1e" stroke-width="4"/><rect x="-60" y="-50" width="120" height="30" rx="12" fill="#e0503f"/><rect x="-60" y="-32" width="120" height="12" fill="#e0503f"/><rect x="-36" y="-62" width="10" height="24" rx="5" fill="#3b2f1e"/><rect x="26" y="-62" width="10" height="24" rx="5" fill="#3b2f1e"/><text x="0" y="36" text-anchor="middle" font-size="44" font-weight="900" fill="#3b2f1e">D-1</text></g>',
    "wallet":     '<g><rect x="-62" y="-40" width="124" height="84" rx="14" fill="#a97c50" stroke="#3b2f1e" stroke-width="4"/><rect x="-62" y="-40" width="124" height="26" rx="13" fill="#8a6440"/><rect x="18" y="-12" width="44" height="30" rx="8" fill="#f5cd63" stroke="#3b2f1e" stroke-width="4"/><circle cx="40" cy="3" r="6" fill="#3b2f1e"/></g>',
    "phone":      '<g><rect x="-36" y="-64" width="72" height="128" rx="14" fill="#fff" stroke="#3b2f1e" stroke-width="5"/><rect x="-26" y="-44" width="52" height="70" rx="6" fill="#eaf4fd"/><polyline points="-18,8 -6,-8 4,0 20,-24" fill="none" stroke="#e0503f" stroke-width="5" stroke-linecap="round" stroke-linejoin="round"/><circle cx="0" cy="46" r="7" fill="#3b2f1e"/></g>',
    "newspaper":  '<g transform="rotate(-4)"><rect x="-64" y="-48" width="128" height="96" rx="8" fill="#fff" stroke="#3b2f1e" stroke-width="4"/><rect x="-52" y="-36" width="60" height="14" rx="4" fill="#3b2f1e"/><rect x="-52" y="-12" width="46" height="7" rx="3" fill="#cfc6b2"/><rect x="-52" y="2" width="52" height="7" rx="3" fill="#cfc6b2"/><rect x="-52" y="16" width="40" height="7" rx="3" fill="#cfc6b2"/><rect x="16" y="-12" width="36" height="36" rx="4" fill="#f5cd63" stroke="#3b2f1e" stroke-width="3"/></g>',
    "bell":       '<g><path d="M0 -58 C-34 -58 -40 -26 -40 6 L-52 26 L52 26 L40 6 C40 -26 34 -58 0 -58 Z" fill="#f5cd63" stroke="#3b2f1e" stroke-width="5" stroke-linejoin="round"/><path d="M-22 -44 q18 -10 36 -2" stroke="#fff" stroke-width="6" fill="none" stroke-linecap="round" opacity=".8"/><circle cx="0" cy="42" r="12" fill="#f3c34d" stroke="#3b2f1e" stroke-width="4"/><rect x="-6" y="-70" width="12" height="14" rx="6" fill="#3b2f1e"/></g>',
    "clock":      '<g><circle cx="0" cy="0" r="54" fill="#fff" stroke="#3b2f1e" stroke-width="6"/><path d="M0 -44 v8 M0 36 v8 M-44 0 h8 M36 0 h8" stroke="#cfc6b2" stroke-width="4" stroke-linecap="round"/><path d="M0 0 L0 -34 M0 0 L24 12" stroke="#3b2f1e" stroke-width="6" stroke-linecap="round"/><circle cx="0" cy="0" r="6" fill="#e0503f"/><path d="M-44 -44 l-12 -10 M44 -44 l12 -10" stroke="#3b2f1e" stroke-width="8" stroke-linecap="round"/></g>',
    "cart":       '<g><path d="M-58 -44 L-40 -44 L-26 18 L38 18 L52 -26 L-34 -26" fill="none" stroke="#3b2f1e" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/><circle cx="-16" cy="40" r="10" fill="#f5cd63" stroke="#3b2f1e" stroke-width="4"/><circle cx="28" cy="40" r="10" fill="#f5cd63" stroke="#3b2f1e" stroke-width="4"/></g>',
    "lightbulb":  '<g><circle cx="0" cy="-16" r="40" fill="url(#gBulb)" stroke="#3b2f1e" stroke-width="5"/><path d="M-14 20 L-10 40 L10 40 L14 20" fill="#ddd" stroke="#3b2f1e" stroke-width="4"/><path d="M-58 -16 l-14 0 M58 -16 l14 0 M-42 -54 l-10 -10 M42 -54 l10 -10 M0 -72 l0 -14" stroke="#f3c34d" stroke-width="6" stroke-linecap="round"/></g>',
    "moneybag":   '<g><path d="M-16 -52 L16 -52 L28 -34 C48 -18 54 6 48 26 C40 50 -40 50 -48 26 C-54 6 -48 -18 -28 -34 Z" fill="#c9a86a" stroke="#3b2f1e" stroke-width="5" stroke-linejoin="round"/><path d="M-30 -22 q16 -12 38 -6" stroke="#fff" stroke-width="6" fill="none" stroke-linecap="round" opacity=".55"/><path d="M-18 -52 Q0 -62 18 -52" fill="none" stroke="#3b2f1e" stroke-width="5" stroke-linecap="round"/><text x="0" y="22" text-anchor="middle" font-size="42" font-weight="900" fill="#3b2f1e">₩</text></g>',
    "scale":      '<g><path d="M0 -56 L0 34" stroke="#3b2f1e" stroke-width="6"/><path d="M-52 -38 L52 -38" stroke="#3b2f1e" stroke-width="6" stroke-linecap="round"/><path d="M-52 -38 L-64 -6 L-40 -6 Z M52 -38 L40 -6 L64 -6 Z" fill="#f5cd63" stroke="#3b2f1e" stroke-width="4" stroke-linejoin="round"/><rect x="-26" y="34" width="52" height="12" rx="6" fill="#3b2f1e"/></g>',
    "umbrella":   '<g><path d="M-58 0 C-58 -44 58 -44 58 0 C38 -12 20 -12 0 0 C-20 -12 -38 -12 -58 0 Z" fill="#7cc4f2" stroke="#3b2f1e" stroke-width="5" stroke-linejoin="round"/><path d="M-40 -26 q20 -12 44 -8" stroke="#fff" stroke-width="6" fill="none" stroke-linecap="round" opacity=".7"/><path d="M0 -34 L0 -6 M0 -6 L0 40 Q0 52 12 52" fill="none" stroke="#3b2f1e" stroke-width="6" stroke-linecap="round"/></g>',
}

_DEFS = '''<defs>
<radialGradient id="gBowl" cx=".38" cy=".3" r="1.1"><stop offset="0" stop-color="#fce8a8"/><stop offset=".55" stop-color="#f5cd63"/><stop offset="1" stop-color="#eab944"/></radialGradient>
<radialGradient id="gBowlIn" cx=".4" cy=".32" r="1"><stop offset="0" stop-color="#fbe49b"/><stop offset="1" stop-color="#f4cf6b"/></radialGradient>
<linearGradient id="gHandle" x1="0" y1="0" x2="1" y2="0"><stop offset="0" stop-color="#f6d372"/><stop offset=".5" stop-color="#f2c85b"/><stop offset="1" stop-color="#e2ae3e"/></linearGradient>
<linearGradient id="gLeaf" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#8ed07a"/><stop offset="1" stop-color="#5ba548"/></linearGradient>
<radialGradient id="gCoin" cx=".38" cy=".3" r="1.1"><stop offset="0" stop-color="#f9d76e"/><stop offset="1" stop-color="#eab63c"/></radialGradient>
<radialGradient id="gBulb" cx=".4" cy=".35" r="1"><stop offset="0" stop-color="#fff3b8"/><stop offset="1" stop-color="#ffe27a"/></radialGradient>
<radialGradient id="gPink" cx=".38" cy=".3" r="1.1"><stop offset="0" stop-color="#fbd3de"/><stop offset="1" stop-color="#f3a8bf"/></radialGradient>
</defs>'''


def mascot(face: str, scale: float = 1.0, tilt: int = 0, flip: bool = False) -> str:
    f = FACES.get(face, FACES["happy"])
    arms = ARMS[FACE_ARMS.get(face, "wave")]
    sx = -1 if flip else 1
    return f'''
<svg viewBox="-150 -175 300 345" width="{int(300*scale)}" height="{int(345*scale)}" xmlns="http://www.w3.org/2000/svg">
  {_DEFS}
  <ellipse cx="0" cy="158" rx="96" ry="14" fill="#3b2f1e" opacity=".13"/>
  <g transform="scale({sx},1) rotate({tilt})">
    <!-- handle -->
    <path d="M-30 20 L-22 140 Q0 160 22 140 L30 20 Z" fill="url(#gHandle)" stroke="#3b2f1e" stroke-width="6.5" stroke-linejoin="round"/>
    <path d="M-10 40 L-6 120" stroke="#fff" stroke-width="7" stroke-linecap="round" opacity=".75"/>
    <!-- leaf -->
    <path d="M16 108 q28 -10 34 16 q-28 10 -34 -16z" fill="url(#gLeaf)" stroke="#3b2f1e" stroke-width="4"/>
    <path d="M18 110 q14 4 30 12" stroke="#3b2f1e" stroke-width="3" fill="none"/>
    <!-- arms -->
    <g transform="translate(0,-40)">{arms}</g>
    <!-- bowl -->
    <ellipse cx="0" cy="-60" rx="88" ry="98" fill="url(#gBowl)" stroke="#3b2f1e" stroke-width="6.5"/>
    <ellipse cx="0" cy="-60" rx="70" ry="80" fill="url(#gBowlIn)"/>
    <path d="M-40 -130 q40 -14 62 8" stroke="#fff" stroke-width="10" fill="none" stroke-linecap="round" opacity=".9"/>
    <path d="M-62 -8 q56 26 124 0" stroke="#d9a83c" stroke-width="5" fill="none" opacity=".35" transform="translate(0,-30)"/>
    <!-- face -->
    <g transform="translate(0,-52)">{f}</g>
  </g>
</svg>'''


BGS = {  # 컷 내부(frame) 배경 — [바탕색, 도트 패턴색]
    "cream": ["#fffdf7", "#f1e8cd"], "mint": ["#eef9ef", "#d6efdb"],
    "sky": ["#eaf4fd", "#d2e6f7"], "pink": ["#fdf1f4", "#f7dce4"],
    "lemon": ["#fdf8e2", "#f4ebbe"], "lavender": ["#f3effd", "#e2daf6"],
}


def friend_svg(kind: str, face: str = "happy") -> str:
    """조연 캐릭터: coin(동전이), pink(핑크 숟가락 친구), piggy_pet(저금통)"""
    f = FACES.get(face, FACES["happy"])
    if kind == "coin":
        return f'''<svg viewBox="-95 -95 190 210" width="170" height="188" xmlns="http://www.w3.org/2000/svg">
{_DEFS}
<ellipse cx="0" cy="88" rx="66" ry="10" fill="#3b2f1e" opacity=".13"/>
<circle cx="0" cy="0" r="70" fill="url(#gCoin)" stroke="#3b2f1e" stroke-width="6"/>
<circle cx="0" cy="0" r="54" fill="#f7d77a"/>
<path d="M-30 -50 q30 -12 48 6" stroke="#fff" stroke-width="8" fill="none" stroke-linecap="round" opacity=".9"/>
<g transform="translate(0,4) scale(.78)">{f}</g>
<text x="0" y="96" text-anchor="middle" font-size="26" font-weight="900" fill="#8a7a5c">동전이</text></svg>'''
    if kind == "pink":
        return f'''<svg viewBox="-120 -170 240 340" width="200" height="283" xmlns="http://www.w3.org/2000/svg">
{_DEFS}
<ellipse cx="0" cy="146" rx="72" ry="11" fill="#3b2f1e" opacity=".13"/>
<g><path d="M-26 18 L-19 122 Q0 140 19 122 L26 18 Z" fill="#f2a7bb" stroke="#3b2f1e" stroke-width="6" stroke-linejoin="round"/>
<path d="M-9 36 L-5 104" stroke="#fff" stroke-width="6" stroke-linecap="round" opacity=".8"/>
<ellipse cx="0" cy="-52" rx="76" ry="84" fill="url(#gPink)" stroke="#3b2f1e" stroke-width="6"/>
<ellipse cx="0" cy="-52" rx="60" ry="68" fill="#f9c9d6"/>
<path d="M-34 -112 q34 -12 53 7" stroke="#fff" stroke-width="9" fill="none" stroke-linecap="round" opacity=".9"/>
<path d="M-52 -122 l-6 -18 l16 10z M52 -122 l6 -18 l-16 10z" fill="#f6b8c9" stroke="#3b2f1e" stroke-width="4"/>
<g transform="translate(0,-46) scale(.86)">{f}</g></g></svg>'''
    if kind == "piggy_pet":
        return '''<svg viewBox="-90 -70 180 155" width="180" height="155" xmlns="http://www.w3.org/2000/svg">
<ellipse cx="0" cy="76" rx="70" ry="9" fill="#3b2f1e" opacity=".13"/>
<ellipse cx="0" cy="8" rx="70" ry="52" fill="#f7b6c2" stroke="#3b2f1e" stroke-width="5"/>
<path d="M-40 -24 q32 -16 66 -4" stroke="#fff" stroke-width="7" fill="none" stroke-linecap="round" opacity=".6"/>
<circle cx="-60" cy="0" r="20" fill="#f7b6c2" stroke="#3b2f1e" stroke-width="5"/>
<circle cx="-66" cy="-3" r="3.5" fill="#3b2f1e"/><circle cx="-56" cy="-3" r="3.5" fill="#3b2f1e"/>
<circle cx="-30" cy="-14" r="4" fill="#3b2f1e"/><circle cx="-6" cy="-14" r="4" fill="#3b2f1e"/>
<path d="M-24 -2 Q-18 4 -12 -2" stroke="#3b2f1e" stroke-width="4" fill="none" stroke-linecap="round"/>
<rect x="-12" y="-52" width="30" height="9" rx="4.5" fill="#3b2f1e"/>
<rect x="-42" y="50" width="15" height="20" fill="#f7b6c2" stroke="#3b2f1e" stroke-width="5"/>
<rect x="28" y="50" width="15" height="20" fill="#f7b6c2" stroke="#3b2f1e" stroke-width="5"/></svg>'''
    return ""


DECOS = [
    '<svg width="70" height="70" viewBox="-35 -35 70 70" style="position:absolute;top:26%;left:9%"><path d="M0 -22 L5 -5 L22 0 L5 5 L0 22 L-5 5 L-22 0 L-5 -5 Z" fill="#f5cd63" opacity=".8"/></svg>',
    '<svg width="52" height="52" viewBox="-26 -26 52 52" style="position:absolute;top:33%;right:10%"><circle r="9" fill="none" stroke="#f2a7bb" stroke-width="5" opacity=".8"/></svg>',
    '<svg width="60" height="60" viewBox="-30 -30 60 60" style="position:absolute;top:24%;right:14%"><path d="M-16 6 Q0 -18 16 6" stroke="#a9d8f5" stroke-width="6" fill="none" stroke-linecap="round" opacity=".9"/></svg>',
    '<svg width="46" height="46" viewBox="-23 -23 46 46" style="position:absolute;top:22%;left:13%"><path d="M0 -15 L3.5 -3.5 L15 0 L3.5 3.5 L0 15 L-3.5 3.5 L-15 0 L-3.5 -3.5 Z" fill="#a9d8f5" opacity=".85"/></svg>',
]


TEMPLATE = """<!doctype html><html lang="ko"><head><meta charset="utf-8">
<style>
  @page { margin:0 }
  html,body{margin:0;padding:0}
  body{width:1080px;height:1080px;background:#fff3da;font-family:"Noto Sans CJK KR","Noto Sans KR",sans-serif;color:#3b2f1e;position:relative;overflow:hidden}
  .frame{position:absolute;inset:34px;border:6px solid #3b2f1e;border-radius:38px;box-shadow:12px 12px 0 #3b2f1e;
    background:
      linear-gradient(180deg, rgba(255,255,255,.55), rgba(255,255,255,0) 26%),
      radial-gradient({{DOT}} 2.6px, transparent 2.6px),
      {{BG}};
    background-size:auto, 46px 46px, auto}
  .badge{position:absolute;top:-26px;left:50px;background:#e0503f;color:#fff;font-weight:900;font-size:30px;padding:8px 26px;border-radius:999px;border:5px solid #3b2f1e;letter-spacing:1px;box-shadow:4px 4px 0 rgba(59,47,30,.9)}
  .ep{position:absolute;top:-22px;right:50px;background:#f5cd63;color:#3b2f1e;font-weight:900;font-size:26px;padding:6px 22px;border-radius:999px;border:5px solid #3b2f1e;box-shadow:4px 4px 0 rgba(59,47,30,.9)}
  .no{position:absolute;bottom:26px;right:40px;font-weight:900;font-size:30px;color:#3b2f1e;opacity:.55}
  .heading{position:absolute;left:70px;right:70px;top:80px;font-size:{{HSIZE}}px;line-height:1.22;font-weight:900;text-align:center;word-break:keep-all;letter-spacing:-.5px;text-shadow:0 3px 0 rgba(255,255,255,.85)}
  .heading em{font-style:normal;color:#e0503f;background:linear-gradient(transparent 55%,#ffe27a 55%)}
  .bubble{position:absolute;left:80px;right:80px;top:{{BTOP}}px;background:#fff;border:5px solid #3b2f1e;border-radius:32px;padding:30px 36px;font-size:{{BSIZE}}px;line-height:1.42;font-weight:700;text-align:center;word-break:keep-all;box-shadow:8px 8px 0 rgba(245,205,99,.95)}
  .bubble:after{content:"";position:absolute;left:50%;bottom:-30px;margin-left:-20px;border:20px solid transparent;border-top-color:#3b2f1e;border-bottom:0}
  .bubble:before{content:"";position:absolute;left:50%;bottom:-22px;margin-left:-16px;border:16px solid transparent;border-top-color:#fff;border-bottom:0;z-index:2}
  .stage{position:absolute;left:0;right:0;bottom:70px;height:430px;display:flex;align-items:flex-end;justify-content:center;gap:36px}
  .stage svg{filter:drop-shadow(0 6px 0 rgba(59,47,30,.10))}
  .caption{position:absolute;left:0;right:0;bottom:40px;text-align:center}
  .caption span{display:inline-block;background:rgba(255,255,255,.85);border:3px solid #3b2f1e;border-radius:999px;padding:8px 30px;font-size:29px;font-weight:800;color:#5f5138;box-shadow:4px 4px 0 rgba(59,47,30,.85)}
  .ground{position:absolute;left:120px;right:120px;bottom:88px;height:22px;background:linear-gradient(180deg,#f7d77a,#eec258);border-radius:999px;opacity:.75}
  .prop{margin-bottom:18px}
  .footer{position:absolute;left:80px;right:80px;bottom:40px;text-align:center;font-size:34px;font-weight:900;color:#e0503f;text-shadow:0 3px 0 rgba(255,255,255,.9)}
</style></head><body>
<div class="frame">
  <div class="badge">{{SERIES}}</div>
  <div class="ep">{{EP}}</div>
  <div class="heading">{{HEADING}}</div>
  {{BUBBLE}}
  <div class="ground"></div>
  {{DECO}}
  <div class="stage">{{LEFT}}{{PROP}}{{MASCOT}}{{RIGHT}}</div>
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
    prop_html = f'<svg class="prop" viewBox="-80 -80 160 160" width="220" height="220">{_DEFS}{prop}</svg>' if prop else ""
    caption = f'<div class="caption"><span>{esc(p["caption"])}</span></div>' if p.get("caption") else ""
    footer = f'<div class="footer">{esc(spec.get("footer",""))}</div>' if (idx == 3 and spec.get("footer") and not p.get("caption")) else ""
    html = TEMPLATE
    bg, dot = BGS.get(p.get("bg", ""), BGS["cream"])
    friend = p.get("friend", "")
    fr_html = friend_svg(friend, p.get("friend_face", "happy")) if friend else ""
    side = p.get("friend_side", "left")
    deco = DECOS[idx % len(DECOS)] if p.get("deco", idx % 2 == 1) else ""
    for k, v in {
        "{{BG}}": bg, "{{DOT}}": dot,
        "{{DECO}}": deco,
        "{{LEFT}}": fr_html if side == "left" else "",
        "{{RIGHT}}": fr_html if side == "right" else "",
        "{{SERIES}}": esc(spec.get("series", "돈수저툰")),
        "{{EP}}": esc(spec.get("episode", "")),
        "{{HEADING}}": heading, "{{HSIZE}}": str(hsize),
        "{{BUBBLE}}": bubble, "{{BTOP}}": str(btop), "{{BSIZE}}": str(bsize),
        "{{PROP}}": prop_html,
        "{{MASCOT}}": mascot(p.get("face", "happy"), scale=float(p.get("mascot_scale", 1.15)), tilt=int(p.get("tilt", 0)), flip=bool(p.get("flip", False))),
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
