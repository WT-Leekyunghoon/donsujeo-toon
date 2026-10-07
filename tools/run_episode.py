"""run_episode.py — 하마의 ETF 도전기 GitHub Actions 러너 v3 (큐 방식, LLM 불필요)

2026-10-06 새 계정·새 캐릭터(하마)로 재시작. 하루 3회 (KST):
  09:50  ETF 상식 글 (아침 경제 이슈 접목) — 2026-10-07~ (전엔 10:00)
  12:00  하마 4컷툰 (Gemini로 미리 만든 완성 이미지 1장 + 글)
  17:00  ETF 상식 글 (오늘 경제 이슈 접목)

연달아 게시 금지: 한 번 실행에 1편만, 직전 게시(Threads 실제 최신 글 기준)로부터
MIN_GAP_MINUTES 안 지났으면 이번 실행은 게시하지 않는다. 밀린 회차는 다음 실행에서.

콘텐츠 소스: queue/daily/YYYY-MM-DD/HHMM.json (+ 툰은 같은 폴더의 1200.png)
  — 예약 작업(Claude)이 미리 만든다. 파일이 없으면 그 슬롯은 건너뛴다(폴백 없음).
시작 시 Threads 실제 게시물과 history 를 대조(reconcile)해 누락 회차를 복구한다.
문제가 생기면 repo 이슈로 알린다. 토큰은 Secrets 로만 받고 어디에도 출력하지 않는다.
사용자 ID 는 토큰으로 GET /me 해서 자동 확인한다 (THREADS_USER_ID Secret 불필요).
"""
from __future__ import annotations
import json, os, re, subprocess, sys, time
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

ROOT = Path(__file__).resolve().parent.parent

API = "https://graph.threads.net/v1.0"
TOKEN = os.environ["THREADS_ACCESS_TOKEN"].strip()
UID = "me"   # main() 에서 GET /me 결과로 실제 숫자 ID 로 교체
REPO = os.environ.get("GITHUB_REPOSITORY", "WT-Leekyunghoon/donsujeo-toon")
RAW = f"https://raw.githubusercontent.com/{REPO}/main/"
KST = ZoneInfo("Asia/Seoul")

SLOT_TYPE = {"09:50": "news", "12:00": "toon", "17:00": "news"}   # 2026-10-06~ 하루 3회
TIP_SOURCE: dict[str, str] = {}        # 팁 슬롯 없음 (v3)
SERIES_TAG = "하마의ETF도전기"          # (옛 형식) 해시태그 회차 표기 — 2026-10-06 부터 해시태그 금지, 회차는 history 로만 추적

SPAM = ["대출", "리딩", "코인", "텔레그램", "오픈채팅", "오픈챗", "디엠", "dm",
        "수익인증", "수익 인증", "투자방", "종목방", "http://", "https://",
        "bit.ly", "무료상담", "부업", "재테크방", "단톡"]
ASK_PICK = ["뭐 사", "뭐사", "사도 돼", "사도돼", "사도 되", "사도되",
            "추천해", "추천 좀", "추천좀", "살까", "매수해도", "픽 좀"]
PICK_REPLY = "종목 픽은 내가 안 해 🥲 대신 구성종목·총보수·거래량 3개는 꼭 보고 골라봐!"
MAX_REPLIES = 15
MAX_HIDES = 15
MAX_POSTS_PER_RUN = 1      # 한 번 실행에서 최대 1편 — 연달아 게시 금지. 밀린 슬롯은 다음 실행(30분 뒤)에서
MIN_GAP_MINUTES = 100      # 직전 게시로부터 최소 간격(분). 안 지났으면 이번 실행은 게시 자체를 건너뛴다
CATCHUP_MINUTES = 540      # 슬롯 시각보다 이만큼(분) 넘게 늦으면 그 회차는 포기
CATCHUP_LAST_HOUR = 23     # KST 이 시각 이후에는 밀린 회차를 게시하지 않는다


# ---------- 유틸 ----------

def strip_hashtags(text: str) -> str:
    """해시태그·출처 줄 금지(2026-10-06 사용자 요청) — 본문에서 #단어·출처 줄을 지우고 빈 줄 정리."""
    text = re.sub(r"(?<![\w&])#[^\s#]+", "", text)
    # 출처 표기 금지(2026-10-06 사용자 요청) — "(출처: …)" / "출처: …" 줄 삭제
    lines = [ln.rstrip() for ln in text.splitlines()
             if not re.match(r"^\s*[(\[]?\s*출처\s*[:：]", ln)]
    out = "\n".join(lines)
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


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
    """Threads 게시물의 '#하마의ETF도전기 EP.N' 을 찾아 history 누락 회차를 복구."""
    _, d = api("GET", f"{UID}/threads", fields="id,text,permalink,timestamp", limit="25")
    if "data" not in d:
        return
    known = {e["ep"] for e in hist["episodes"]}
    changed = False
    for p in d["data"]:
        m = re.search(r"#?하마의\s?ETF\s?도전기\s*EP\.?\s*(\d+)", p.get("text") or "")
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


def minutes_since_last_post() -> int | None:
    """Threads 계정의 실제 최신 게시물 시각 기준 경과 분. 조회 실패 시 None."""
    _, d = api("GET", f"{UID}/threads", fields="timestamp", limit="1")
    rows = d.get("data") or []
    ts = rows[0].get("timestamp") if rows else None
    if not ts:
        return None
    try:
        last = datetime.strptime(ts, "%Y-%m-%dT%H:%M:%S%z")
    except ValueError:
        return None
    return int((datetime.now(KST) - last.astimezone(KST)).total_seconds() // 60)


# ---------- 슬롯·큐 ----------

def slot_minutes(slot: str) -> int:
    h, m = map(int, slot.split(":"))
    return h * 60 + m


def pick_slot(hist: dict) -> str:
    """가장 가까운 슬롯 (기록용 폴백)."""
    cur = datetime.now(KST).hour * 60 + datetime.now(KST).minute
    return min(hist.get("schedule_kst", list(SLOT_TYPE)),
               key=lambda s: abs(cur - slot_minutes(s)))


def slot_due(hist: dict, date: str, slot: str) -> tuple[bool, str]:
    """지금 이 슬롯을 게시해야 하는가. (가능여부, 사유)

    GitHub Actions 의 cron 은 지연·누락이 잦다. '지금 시각에 제일 가까운 슬롯'
    하나만 고르면 늦게 돈 실행이 엉뚱한 슬롯을 잡고 놓친 회차는 영영 복구되지
    않으므로, 시각이 지난 미게시 슬롯을 순서대로 따라잡는다.
    """
    now = datetime.now(KST)
    late = now.hour * 60 + now.minute - slot_minutes(slot)
    if late < 0 and slot != os.environ.get("FORCE_SLOT", "").strip():   # 수동 실행에서 지정한 슬롯은 시각 전이라도 게시
        return False, "아직 시각 전"
    if already_posted(hist, date, slot):
        return False, "이미 게시됨"
    if late > CATCHUP_MINUTES or now.hour >= CATCHUP_LAST_HOUR:
        return False, f"{late // 60}시간 지연 → 이 회차 포기"
    kind = SLOT_TYPE.get(slot, "toon")
    if not daily_file(date, slot).exists():
        return False, "콘텐츠 파일 없음"
    if kind == "tip":
        src = TIP_SOURCE.get(slot)
        if src and not already_posted(hist, date, src):
            return False, f"원본 툰({src}) 미게시 → 팁만 따로 올리지 않음"
    return True, ""


def daily_file(date: str, slot: str) -> Path:
    return ROOT / "queue" / "daily" / date / (slot.replace(":", "") + ".json")


# ---------- 렌더·게시 ----------

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
    """완성된 4컷 이미지(같은 폴더의 HHMM.png 또는 json 의 "image")를 글과 함께 게시."""
    df = daily_file(date, slot)
    spec = json.loads(df.read_text(encoding="utf-8"))
    img_rel = Path(spec.get("image") or df.with_suffix(".png").relative_to(ROOT).as_posix())
    img_path = (ROOT / img_rel).resolve()
    if img_rel.is_absolute() or not img_path.is_relative_to(ROOT.resolve()) or not img_path.is_file():
        notify(f"하마툰: {date} 툰 이미지 없음", f"{img_rel} 파일이 없어 {slot} 툰을 건너뜁니다.")
        note.append("툰 이미지 없음 → 생략")
        return "게시 없음"
    n = hist["next_episode"]
    url = f"{RAW}{img_rel.as_posix()}"
    if not wait_raw([url]):
        notify(f"하마툰: EP.{n} raw 이미지 확인 실패", f"{url} 이 raw URL 에서 안 보입니다.")
        note.append("raw 확인 실패")
        return "게시 없음"
    body = strip_hashtags(spec.get("body", "").replace("{N}", str(n)))
    post_id, err = publish_post(body, url)
    if err:
        time.sleep(20)
        post_id, err = publish_post(body, url)
    if err:
        notify(f"하마툰: EP.{n} 게시 실패", str(err))
        note.append(f"게시 실패: {err}")
        return "게시 없음"
    _, pd = api("GET", post_id, fields="permalink")
    hist["episodes"].append({
        "ep": n, "date": date, "slot": slot, "title": spec.get("title", ""),
        "topic": spec.get("topic", ""), "post_id": post_id,
        "permalink": pd.get("permalink", ""), "images": img_rel.as_posix(),
    })
    hist["next_episode"] = n + 1
    df.rename(df.with_suffix(".done"))
    return f"EP.{n} 툰 게시 {pd.get('permalink', post_id)}"


def do_text(hist: dict, date: str, slot: str, kind: str, note: list[str]) -> str:
    df = daily_file(date, slot)
    if not df.exists():
        note.append(f"{slot} {kind} 파일 없음 → 생략")
        return "게시 없음"
    data = json.loads(df.read_text(encoding="utf-8"))
    body = strip_hashtags(data.get("body", ""))
    if not body:
        note.append(f"{slot} 본문 비어있음 → 생략")
        return "게시 없음"
    image_url = None
    if kind == "news" and data.get("image"):
        image_rel = Path(data["image"])
        image_path = (ROOT / image_rel).resolve()
        if image_rel.is_absolute() or not image_path.is_relative_to(ROOT.resolve()) or not image_path.is_file():
            note.append(f"{slot} 첨부 이미지 없음 → 생략")
            return "게시 없음"
        image_url = f"{RAW}{image_rel.as_posix()}"
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
        notify(f"하마툰: {date} {slot} {kind} 게시 실패", str(err))
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

    global UID
    _, me = api("GET", "me", fields="id,username")
    expected = hist["account"].get("username")
    if not me.get("id") or (expected and me.get("username") != expected):
        notify("하마툰: 토큰/계정 확인 필요",
               f"GET /me 결과가 예상 계정({expected})과 다릅니다: {me.get('username')} "
               f"(error: {me.get('error')})")
        sys.exit(1)
    UID = me["id"]
    if not expected or not hist["account"].get("user_id"):   # 새 계정 첫 실행 — 계정 정보 기록
        hist["account"].update({"username": me["username"], "user_id": UID})
        log(f"[account] 계정 확인: @{me['username']}")
    if not hist["account"].get("token_expires_at"):
        # 새 토큰 첫 사용일 기준 보수적으로 55일 뒤로 기록 → 만료 10일 전부터 자동 갱신 시도
        hist["account"]["token_expires_at"] = (datetime.now(KST).date() + timedelta(days=55)).isoformat()

    reconcile(hist)

    _, q = api("GET", f"{UID}/threads_publishing_limit", fields="quota_usage,config")
    quota = (q.get("data") or [{}])[0]
    can_post = quota.get("quota_usage", 0) < quota.get("config", {}).get("quota_total", 250) - 5
    if not can_post:
        note.append("쿼터 임박 → 게시 생략")

    hist["schedule_kst"] = list(SLOT_TYPE)   # 코드가 기준 (19:00 폐지 반영)
    gap = minutes_since_last_post()
    if can_post and gap is not None and gap < MIN_GAP_MINUTES:
        can_post = False
        note.append(f"직전 게시 {gap}분 전 → {MIN_GAP_MINUTES}분 간격 미달, 이번 실행 게시 건너뜀")

    date = datetime.now(KST).date().isoformat()
    results: list[str] = []
    posted = 0
    if can_post:
        for slot in sorted(SLOT_TYPE, key=slot_minutes):
            if posted >= MAX_POSTS_PER_RUN:
                note.append(f"{slot} 이후는 다음 실행에서 이어서")
                break
            ok, why = slot_due(hist, date, slot)
            if not ok:
                if why not in ("아직 시각 전", "이미 게시됨"):
                    note.append(f"{slot} {why}")
                continue
            kind = SLOT_TYPE.get(slot, "toon")
            if kind == "toon":
                r = do_toon(hist, date, slot, note)
            else:
                r = do_text(hist, date, slot, kind, note)
            results.append(f"{slot} {r}")
            save_history(hist)
            if r != "게시 없음":
                posted += 1
                time.sleep(30)
    slot = results[0].split(" ", 1)[0] if results else pick_slot(hist)
    ep_line = " | ".join(results) or "게시 없음"

    n_rep, n_hid = handle_comments(hist)

    left = 0

    token_note = maybe_refresh_token(hist)
    if token_note:
        note.append(token_note)
        notify("하마툰: 토큰 갱신 필요", token_note)

    hist.setdefault("runs", []).append({
        "time": datetime.now(KST).isoformat(timespec="minutes"),
        "slot": slot, "result": ep_line, "replies": n_rep, "hidden": n_hid,
        "note": "; ".join(note) or "ok", 
    })
    hist["runs"] = hist["runs"][-150:]
    save_history(hist)
    git_push(f"state update ({date} {slot}: {ep_line}, r{n_rep}/h{n_hid})")
    log(f"[done] {slot} {ep_line} / 답글 {n_rep} · 숨김 {n_hid}")


if __name__ == "__main__":
    main()
