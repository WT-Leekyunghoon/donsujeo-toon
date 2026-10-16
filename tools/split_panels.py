"""split_panels.py — 4컷 툰 한 장(가로 1줄 또는 2×2)을 휴대폰용 4장(4:5 세로)으로 나눈다.

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
    """제목 띠와 컷 상자 목록을 찾는다. 가로 1줄 4컷과 2×2(2줄 2칸) 둘 다 지원 (2026-10-16)."""
    g = img.convert("L")
    w, h = g.size
    px = g.load()
    dark = lambda x, y: px[x, y] < 235
    row = [sum(dark(x, y) for x in range(0, w, 2)) / (w / 2) for y in range(h)]
    bands = runs([r > 0.01 for r in row], 8)
    tallest = max(b[1] - b[0] for b in bands)
    rows = [b for b in bands if b[1] - b[0] >= tallest * 0.6]      # 컷 줄(1줄 또는 2줄)
    title = [b for b in bands if b[1] <= rows[0][0]]
    title_box = (title[0][0], title[-1][1]) if title else None
    boxes = []
    for y0, y1 in rows:
        col = [sum(dark(x, y) for y in range(y0, y1, 2)) / ((y1 - y0) / 2) for x in range(w)]
        for x0, x1 in runs([c > 0.05 for c in col], w // 12):
            boxes.append((x0, y0, x1, y1))
    return title_box, boxes


def split(src: Path) -> list[Path]:
    img = Image.open(src).convert("RGB")
    title_box, boxes = detect(img)
    if len(boxes) != 4:
        raise SystemExit(f"컷 {len(boxes)}개 탐지 — 4컷이 아니라 나누지 않음: {boxes}")
    title = None
    if title_box:
        t0, t1 = max(0, title_box[0] - 10), min(img.height, title_box[1] + 10)
        title = img.crop((0, t0, img.width, t1))
        title = title.resize((W, round(title.height * W / title.width)), Image.LANCZOS)
        if title.height > 140:                     # 세로 그림이면 제목 띠가 너무 커지지 않게
            title = title.resize((round(title.width * 140 / title.height), 140), Image.LANCZOS)
    outs = []
    for i, (x0, y0, x1, y1) in enumerate(boxes, 1):
        pad = 4
        panel = img.crop((max(0, x0 - pad), max(0, y0 - pad), min(img.width, x1 + pad), min(img.height, y1 + pad)))
        canvas = Image.new("RGB", (W, H), BG)
        top = 30
        if title:
            canvas.paste(title, ((W - title.width) // 2, top))
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
