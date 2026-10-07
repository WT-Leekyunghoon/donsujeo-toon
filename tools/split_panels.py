"""split_panels.py — 가로 4컷 툰 한 장을 휴대폰용 4장(4:5 세로)으로 나눈다.

사용: python tools/split_panels.py queue/daily/2026-10-07/1200.png
  → 같은 폴더에 1200-1.png ~ 1200-4.png 생성, 1200.json 에 "panels" 목록 기록.
각 장 = 위쪽에 원본 제목 띠 + 아래에 해당 컷 확대. 칸 경계는 흰 여백으로 자동 탐지.
"""
from __future__ import annotations
import json, sys
from pathlib import Path
from PIL import Image

W, H = 1080, 1350          # Threads 세로 4:5
BG = (255, 255, 255)


def runs(flags, min_len):
    out, start = [], None
    for i, f in enumerate(list(flags) + [False]):
        if f and start is None:
            start = i
        elif not f and start is not None:
            if i - start >= min_len:
                out.append((start, i))
            start = None
    return out


def detect(img: Image.Image):
    g = img.convert("L")
    w, h = g.size
    px = g.load()
    dark = lambda x, y: px[x, y] < 235
    # 행별 '안 흰' 비율 → 컷 띠(가장 긴 구간)와 제목(그 위 구간)
    row = [sum(dark(x, y) for x in range(0, w, 2)) / (w / 2) for y in range(h)]
    bands = runs([r > 0.01 for r in row], 8)
    panel_band = max(bands, key=lambda b: b[1] - b[0])
    title = [b for b in bands if b[1] <= panel_band[0]]
    title_box = (title[0][0], title[-1][1]) if title else None
    y0, y1 = panel_band
    col = [sum(dark(x, y) for y in range(y0, y1, 2)) / ((y1 - y0) / 2) for x in range(w)]
    panels = runs([c > 0.05 for c in col], w // 12)
    return title_box, (y0, y1), panels


def split(src: Path) -> list[Path]:
    img = Image.open(src).convert("RGB")
    title_box, (y0, y1), cols = detect(img)
    if len(cols) != 4:
        raise SystemExit(f"컷 {len(cols)}개 탐지 — 4컷이 아니라 나누지 않음: {cols}")
    title = None
    if title_box:
        t0, t1 = max(0, title_box[0] - 10), min(img.height, title_box[1] + 10)
        title = img.crop((0, t0, img.width, t1))
        title = title.resize((W, round(title.height * W / title.width)), Image.LANCZOS)
    outs = []
    for i, (x0, x1) in enumerate(cols, 1):
        pad = 4
        panel = img.crop((max(0, x0 - pad), max(0, y0 - pad), min(img.width, x1 + pad), min(img.height, y1 + pad)))
        canvas = Image.new("RGB", (W, H), BG)
        top = 30
        if title:
            canvas.paste(title, (0, top))
            top += title.height + 20
        avail_w, avail_h = W - 80, H - top - 40
        s = min(avail_w / panel.width, avail_h / panel.height)
        p = panel.resize((round(panel.width * s), round(panel.height * s)), Image.LANCZOS)
        canvas.paste(p, ((W - p.width) // 2, top + (avail_h - p.height) // 2))
        out = src.with_name(f"{src.stem}-{i}.png")
        canvas.save(out, optimize=True)
        outs.append(out)
    return outs


if __name__ == "__main__":
    src = Path(sys.argv[1])
    outs = split(src)
    root = Path(__file__).resolve().parent.parent
    js = src.with_suffix(".json")
    if js.exists():
        d = json.loads(js.read_text(encoding="utf-8"))
        d["panels"] = [o.resolve().relative_to(root).as_posix() for o in outs]
        js.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("\n".join(str(o) for o in outs))
