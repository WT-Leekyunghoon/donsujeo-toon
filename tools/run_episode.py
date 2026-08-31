"""run_episode.py — 돈수저툰 GitHub Actions 러너 v2 (큐 방식, LLM 불필요)

하루 5회 (KST):
  10:00  그림툰 ① (4컷 캐러셀)
  12:00  툰① 보충 설명·팁 (글 + 툰 패널 1장 첨부)
  14:00  그날의 경제 뉴스 해설 (글)
  17:00  그림툰 ② (4컷 캐러셀)
  19:00  툰② 보충 설명·팁 (글 + 툰 패널 1장 첨부)

콘텐츠 소스:
  queue/daily/YYYY-MM-DD/HHMM.json  ← 날짜 지정 콘텐츠 (예약 작업이 매일 생성)
  queue/q*.json                     ← 상시(에버그린) 툰 큐 — 툰 슬롯의 폴백

날짜 파일이 없으면: 툰 슬롯은 에버그린 큐에서 꺼내고, 팁·뉴스 슬롯은 건너뛴다.
시작 시 Threads 실제 게시물과 history 를 대조(reconcile)해 누락 회차를 복구한다.
문제가 생기면 repo 이슈로 알린다. 토큰은 Secrets 로만 받고 어디에도 출력하지 않는다.
"""
from __future__ import annotations
import asyncio, json, os, re, shutil, subprocess, sys, time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "tools"))
import render_toon  # noqa: E402

API = "https://graph.threads.net/v1.0"
TOKEN = os.environ["THREADS_ACCESS_TOKEN"].strip()
UID = os.environ["THREADS_USER_ID"].strip()
REPO = os.environ.get("GITHUB_REPOSITORY", "WT-Leekyunghoon/donsujeo-toon")
RAW = f"https://raw.githubusercontent.com/{REPO}/main/"
KST = ZoneInfo("Asia/Seoul")

SLOT_TYPE = {"10:00": "toon", "12:00": "tip", "14:00": "news",
             "17:00": "toon", "19:00": "tip"}
TIP_SOURCE = {"12:00": "10:00", "19:00": "17:00"}  # 팁 슬롯 → 원본 툰 슬롯

SPAM = ["대출", "리딩", "코인", "텔레그램", "오픈채팅", "오픈챗", "디엠", "dm",
        "수익인증", "수익 인증", "투자방", "종목방", "http://", "https://",
        "bit.ly", "무료상담", "부업", "재테크방", "단톡"]
ASK_PICK = ["뭐 사", "뭐사", "사도 돼", "사도돼", "사도 되", "사도되",
            "추천해", "추천 좀", "추천좀", "살까", "매수해도", "픽 좀"]
PICK_REPLY = "종목 픽은 내가 안 해 🥲 대신 구성종목·총보수·거래량 3개는 꼭 보고 골라봐!"
MAX_REPLIES = 15
MAX_HIDES = 15


# ---------- 유틸 ----------

def log(*a):
    print(*a, flush=True)


def api(method: str, path: str, **params):
    params.setdefault("access_token", TOKEN)
    try:
        r = requests.request(method, f"{API}/{path}", params=params, timeout=30)
    except requests.RequestException as e:
        return 0, {"error": str(e)}
    try:
        data = r.json()
    except Exception:
        data = {"raw": r.text[:300]}
    if r.status_code >= 400:
        log(f"[api] {method} {path} -> {r.status_code} {data}")
    return r.status_code, data


def sh(*args, check=True, **kw):
    log("+", " ".join(args))
    return subprocess.run(args, check=check, cwd=ROOT, **kw)


def git_push(msg: str):
    sh("git", "add", "-A")
    if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT).returncode == 0:
        return
    sh("git", "commit", "-m", msg)
    for _ in range(3):
        if subprocess.run(["git", "push"], cwd=ROOT).returncode == 0:
            return
        sh("git", "pull", "--rebase", check=False)
    sh("git", "push")


def notify(title: str, body: str = ""):
    """repo 이슈로 알림 (같은 제목의 열린 이슈가 있으면 생략)."""
    env = {**os.environ, "GH_TOKEN": os.environ.get("GITHUB_TOKEN", "")}
    try:
        out = subprocess.run(["gh", "issue", "list", "--state", "open",
                              "--search", title, "--json", "title"],
                             capture_output=True, text=True, env=env, cwd=ROOT)
        if title in (out.stdout or ""):
            return
        subprocess.run(["gh", "issue", "create", "--title", title,
                        "--body", body or title], env=env, cwd=ROOT, check=False)
    except Exception as e:
        log("[notify]", e)


def save_history(hist: dict):
    (ROOT / "state" / "history.json").write_text(
        json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------- 상태 대조 ----------

def reconcile(hist: dict):
    """Threads 게시물의 '#돈수저툰 EP.N' 을 찾아 history 누락 회차를 복구."""
    _, d = api("GET", f"{UID}/threads", fields="id,text,permalink,timestamp", limit="25")
    if "data" not in d:
        return
    known = {e["ep"] for e in hist["episodes"]}
    changed = False
    for p in d["data"]:
        m = re.search(r"#돈수저툰\s*EP\.?\s*(\d+)", p.get("text") or "")
        if not m:
            continue
        n = int(m.group(1))
        if n in known:
            continue
        first = ((p.get("text") or "").strip().splitlines() or [""])[0]
        hist["episodes"].append({
            "ep": n, "date": (p.get("timestamp") or "")[:10], "slot": "reconciled",
            "title": first, "topic": "", "post_id": p["id"],
            "permalink": p.get("permalink", ""), "images": "",
        })
        known.add(n)
        changed = True
        log(f"[reconcile] EP.{n} 을 Threads 에서 복구")
    if changed:
        hist["episodes"].sort(key=lambda e: e["ep"])
    hist["next_episode"] = max(hist.get("next_episode", 1), max(known, default=0) + 1)


# ---------- 슬롯·큐 ----------

def pick_slot(hist: dict) -> str:
    now = datetime.now(KST)
    cur = now.hour * 60 + now.minute

    def dist(s):
        h, m = map(int, s.split(":"))
        return abs(cur - (h * 60 + m))

    return min(hist.get("schedule_kst", list(SLOT_TYPE)), key=dist)


def daily_file(date: str, slot: str) -> Path:
    return ROOT / "queue" / "daily" / date / (slot.replace(":", "") + ".json")


def recent_topics(hist: dict) -> list[str]:
    return [(e.get("topic", "") + " " + e.get("title", "")) for e in hist["episodes"][-10:]]


def pick_evergreen(hist: dict):
    recents = recent_topics(hist)
    for f in sorted((ROOT / "queue").glob("q*.json")):
        spec = json.loads(f.read_text(encoding="utf-8"))
        key = (spec.get("topic", "").split() or [""])[0]
        if key and any(key in r for r in recents):
            log(f"[queue] {f.name} 은 최근 10편과 소재 겹침 → 보류")
            continue
        return f, spec
    return None, None


# ---------- 렌더·게시 ----------

def render_episode(spec: dict, n: int, out_dir: Path) -> bool:
    spec = dict(spec)
    spec["episode"] = f"EP.{n}"
    spec.setdefault("series", "돈수저툰")
    tmp = ROOT / "state" / "_spec_tmp.json"
    tmp.write_text(json.dumps(spec, ensure_ascii=False), encoding="utf-8")
    try:
        asyncio.run(render_toon.render(tmp, out_dir))
    except Exception as e:
        log("[render] 실패:", e)
        return False
    finally:
        tmp.unlink(missing_ok=True)
    pngs = sorted(out_dir.glob("*.png"))
    if len(pngs) != 4 or any(p.stat().st_size < 20000 for p in pngs):
        log("[render] 산출물 이상:", [(p.name, p.stat().st_size) for p in pngs])
        return False
    return True


def wait_raw(urls: list[str], timeout=150) -> bool:
    t0 = time.time()
    pending = list(urls)
    while pending and time.time() - t0 < timeout:
        pending = [u for u in pending
                   if requests.head(u, timeout=15).status_code != 200]
        if pending:
            time.sleep(8)
    return not pending


def _publish_container(creation: str):
    for _ in range(10):
        time.sleep(10)
        _, s = api("GET", creation, fields="status,error_message")
        st = s.get("status")
        if st == "FINISHED":
            break
        if st == "ERROR":
            return None, f"컨테이너 ERROR: {s.get('error_message')}"
    _, d = api("POST", f"{UID}/threads_publish", creation_id=creation)
    if "id" not in d:
        return None, f"publish 실패: {d.get('error')}"
    return d["id"], None


def publish_carousel(image_urls: list[str], text: str):
    children = []
    for u in image_urls:
        _, d = api("POST", f"{UID}/threads", media_type="IMAGE",
                   image_url=u, is_carousel_item="true")
        if "id" not in d:
            return None, f"이미지 컨테이너 실패: {d.get('error')}"
        children.append(d["id"])
        time.sleep(2)
    _, d = api("POST", f"{UID}/threads", media_type="CAROUSEL",
               children=",".join(children), text=text)
    if "id" not in d:
        return None, f"캐러셀 컨테이너 실패: {d.get('error')}"
    return _publish_container(d["id"])


def publish_post(text: str, image_url: str | None = None):
    """글 게시 (선택적으로 이미지 1장 첨부)."""
    if image_url:
        _, d = api("POST", f"{UID}/threads", media_type="IMAGE",
                   image_url=image_url, text=text)
    else:
        _, d = api("POST", f"{UID}/threads", media_type="TEXT", text=text)
    if "id" not in d:
        return None, f"컨테이너 실패: {d.get('error')}"
    return _publish_container(d["id"])


# ---------- 슬롯별 처리 ----------

def already_posted(hist: dict, date: str, slot: str) -> bool:
    rows = hist["episodes"] + hist.get("posts", [])
    return any(r.get("date") == date and r.get("slot") == slot for r in rows)


def do_toon(hist: dict, date: str, slot: str, note: list[str]) -> str:
    df = daily_file(date, slot)
    qfile = None
    if df.exists():
        spec = json.loads(df.read_text(encoding="utf-8"))
    else:
        qfile, spec = pick_evergreen(hist)
        if spec is None:
            notify("돈수저툰: 큐가 비었습니다",
                   f"{date} {slot} 툰 슬롯에 쓸 콘텐츠가 없습니다 (daily 파일 X, 에버그린 큐 X).")
            note.append("툰 큐 없음 → 게시 생략")
            return "게시 없음"
    n = hist["next_episode"]
    img_rel = f"images/{date}/ep{n:02d}"
    if not render_episode(spec, n, ROOT / img_rel):
        notify(f"돈수저툰: EP.{n} 렌더 실패", f"{date} {slot} 렌더 실패로 건너뜁니다.")
        note.append("렌더 실패")
        return "게시 없음"
    git_push(f"EP.{n} images")
    urls = [f"{RAW}{img_rel}/{i:02d}.png" for i in range(1, 5)]
    if not wait_raw(urls):
        notify(f"돈수저툰: EP.{n} raw 이미지 확인 실패", "푸시한 이미지가 raw URL 에서 안 보입니다.")
        note.append("raw 확인 실패")
        return "게시 없음"
    body = spec.get("body", "").replace("{N}", str(n))
    post_id, err = publish_carousel(urls, body)
    if err:
        time.sleep(20)
        post_id, err = publish_carousel(urls, body)
    if err:
        notify(f"돈수저툰: EP.{n} 게시 실패", str(err))
        note.append(f"게시 실패: {err}")
        return "게시 없음"
    _, pd = api("GET", post_id, fields="permalink")
    hist["episodes"].append({
        "ep": n, "date": date, "slot": slot, "title": spec.get("title", ""),
        "topic": spec.get("topic", ""), "post_id": post_id,
        "permalink": pd.get("permalink", ""), "images": img_rel,
    })
    hist["next_episode"] = n + 1
    if df.exists():
        df.rename(df.with_suffix(".done"))
    elif qfile:
        done = ROOT / "queue" / "done"
        done.mkdir(exist_ok=True)
        shutil.move(str(qfile), str(done / qfile.name))
    return f"EP.{n} 툰 게시 {pd.get('permalink', post_id)}"


def do_text(hist: dict, date: str, slot: str, kind: str, note: list[str]) -> str:
    df = daily_file(date, slot)
    if not df.exists():
        note.append(f"{slot} {kind} 파일 없음 → 생략")
        return "게시 없음"
    data = json.loads(df.read_text(encoding="utf-8"))
    body = data.get("body", "").strip()
    if not body:
        note.append(f"{slot} 본문 비어있음 → 생략")
        return "게시 없음"
    image_url = None
    if kind == "tip":
        src = TIP_SOURCE.get(slot)
        toon = next((e for e in reversed(hist["episodes"])
                     if e.get("date") == date and e.get("slot") == src
                     and e.get("images")), None)
        panel = data.get("attach_panel", 3)
        if toon:
            image_url = f"{RAW}{toon['images']}/{int(panel):02d}.png"
            body = body.replace("{PERMALINK}", toon.get("permalink", ""))
        elif "{PERMALINK}" in body:
            note.append(f"{slot} 원본 툰 없음 → 링크 없이 게시")
            body = body.replace("{PERMALINK}", "").strip()
    post_id, err = publish_post(body, image_url)
    if err:
        time.sleep(20)
        post_id, err = publish_post(body, image_url)
    if err:
        notify(f"돈수저툰: {date} {slot} {kind} 게시 실패", str(err))
        note.append(f"{kind} 게시 실패: {err}")
        return "게시 없음"
    _, pd = api("GET", post_id, fields="permalink")
    hist.setdefault("posts", []).append({
        "date": date, "slot": slot, "kind": kind, "title": data.get("title", ""),
        "post_id": post_id, "permalink": pd.get("permalink", ""),
    })
    df.rename(df.with_suffix(".done"))
    return f"{kind} 게시 {pd.get('permalink', post_id)}"


# ---------- 댓글 ----------

def handle_comments(hist: dict):
    replied = set(hist.get("replied", []))
    hidden = set(hist.get("hidden", []))
    n_replied = n_hidden = 0
    me = hist["account"]["username"]
    rows = [r for r in hist["episodes"] + hist.get("posts", []) if r.get("post_id")]
    for e in rows[-15:]:
        _, d = api("GET", f"{e['post_id']}/replies",
                   fields="id,text,username", limit="50")
        for rp in d.get("data", []):
            rid = rp.get("id")
            if not rid or rid in replied or rid in hidden:
                continue
            if rp.get("username") == me:
                continue
            txt = (rp.get("text") or "")
            low = txt.lower()
            if any(k in low for k in SPAM):
                if n_hidden < MAX_HIDES:
                    api("POST", f"{rid}/manage_reply", hide="true")
                    hidden.add(rid)
                    n_hidden += 1
                continue
            if any(k in txt for k in ASK_PICK) and n_replied < MAX_REPLIES:
                _, c = api("POST", f"{UID}/threads", media_type="TEXT",
                           text=PICK_REPLY, reply_to_id=rid)
                if "id" in c:
                    time.sleep(5)
                    _, pub = api("POST", f"{UID}/threads_publish",
                                 creation_id=c["id"])
                    if "id" in pub:
                        n_replied += 1
            replied.add(rid)  # 답 안 한 것도 재검토 방지
    hist["replied"] = sorted(replied)[-2000:]
    hist["hidden"] = sorted(hidden)[-2000:]
    return n_replied, n_hidden


# ---------- 토큰 ----------

def maybe_refresh_token(hist: dict):
    exp = hist["account"].get("token_expires_at")
    if not exp:
        return None
    try:
        days = (datetime.fromisoformat(exp).replace(tzinfo=KST)
                - datetime.now(KST)).days
    except ValueError:
        return None
    if days > 10:
        return None
    try:
        r = requests.get("https://graph.threads.net/refresh_access_token",
                         params={"grant_type": "th_refresh_token",
                                 "access_token": TOKEN}, timeout=30)
        d = r.json()
    except Exception as e:
        d = {"error": str(e)}
    if "access_token" not in d:
        return f"Threads 토큰 갱신 실패 — 만료 {exp}(D-{days}). 수동 재발급 필요."
    new_exp = (datetime.now(KST)
               + timedelta(seconds=d.get("expires_in", 5184000))).date().isoformat()
    pat = os.environ.get("GH_PAT")
    if not pat:
        return (f"Threads 토큰은 갱신됐지만 GH_PAT Secret 이 없어 저장 못 함 — "
                f"수동으로 재발급해 THREADS_ACCESS_TOKEN Secret 교체 필요 (만료 {exp}).")
    p = subprocess.run(["gh", "secret", "set", "THREADS_ACCESS_TOKEN",
                        "--repo", REPO],
                       input=d["access_token"], text=True,
                       env={**os.environ, "GH_TOKEN": pat}, cwd=ROOT)
    if p.returncode != 0:
        return f"토큰 갱신됐지만 Secret 저장 실패 — 수동 교체 필요 (만료 {exp})."
    hist["account"]["token_expires_at"] = new_exp
    log(f"[token] 갱신 완료, 새 만료일 {new_exp}")
    return None


# ---------- 메인 ----------

def main():
    hist = json.loads((ROOT / "state" / "history.json").read_text(encoding="utf-8"))
    note: list[str] = []

    reconcile(hist)

    _, me = api("GET", "me", fields="id,username")
    if me.get("username") != hist["account"]["username"]:
        notify("돈수저툰: 토큰/계정 확인 필요",
               f"GET /me 결과가 예상 계정과 다릅니다: {me.get('username')} "
               f"(error: {me.get('error')})")
        sys.exit(1)

    _, q = api("GET", f"{UID}/threads_publishing_limit", fields="quota_usage,config")
    quota = (q.get("data") or [{}])[0]
    can_post = quota.get("quota_usage", 0) < quota.get("config", {}).get("quota_total", 250) - 5
    if not can_post:
        note.append("쿼터 임박 → 게시 생략")

    date = datetime.now(KST).date().isoformat()
    slot = pick_slot(hist)
    kind = SLOT_TYPE.get(slot, "toon")
    ep_line = "게시 없음"
    if can_post:
        if already_posted(hist, date, slot):
            note.append(f"{date} {slot} 이미 게시됨 → 중복 방지 생략")
        elif kind == "toon":
            ep_line = do_toon(hist, date, slot, note)
        else:
            ep_line = do_text(hist, date, slot, kind, note)

    n_rep, n_hid = handle_comments(hist)

    left = len(list((ROOT / "queue").glob("q*.json")))
    tomorrow = (datetime.now(KST).date() + timedelta(days=1)).isoformat()
    if left <= 4 and not (ROOT / "queue" / "daily" / tomorrow).exists():
        notify("돈수저툰: 큐 잔량 부족",
               f"에버그린 큐 {left}편, 내일({tomorrow}) daily 콘텐츠 없음. 보충 필요.")

    token_note = maybe_refresh_token(hist)
    if token_note:
        note.append(token_note)
        notify("돈수저툰: 토큰 갱신 필요", token_note)

    hist.setdefault("runs", []).append({
        "time": datetime.now(KST).isoformat(timespec="minutes"),
        "slot": slot, "result": ep_line, "replies": n_rep, "hidden": n_hid,
        "note": "; ".join(note) or "ok", "evergreen_left": left,
    })
    hist["runs"] = hist["runs"][-150:]
    save_history(hist)
    git_push(f"state update ({date} {slot}: {ep_line}, r{n_rep}/h{n_hid})")
    log(f"[done] {slot} {ep_line} / 답글 {n_rep} · 숨김 {n_hid}")


if __name__ == "__main__":
    main()
