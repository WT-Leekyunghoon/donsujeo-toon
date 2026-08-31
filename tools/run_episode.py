"""run_episode.py — 돈수저툰 GitHub Actions 러너 (큐 방식, LLM 불필요)

매 회차:
  queue/ 에서 spec 하나 꺼냄 → 4컷 렌더 → 이미지 커밋 → Threads 캐러셀 게시
  → 댓글 규칙 처리(정형 답글 + 스팸 숨김) → history.json 갱신 → 커밋.

시작 시 Threads 실제 게시물과 history 를 대조(reconcile)해서
이전 회차가 "게시는 됐는데 상태 저장 실패"한 경우를 자동 복구한다.

문제가 생기면 repo 에 이슈를 만들어 알린다 (GitHub 알림 메일).
토큰은 환경변수(Secrets)로만 받고 어디에도 출력하지 않는다.
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
        safe = {k: v for k, v in data.items()}
        log(f"[api] {method} {path} -> {r.status_code} {safe}")
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
    p = ROOT / "state" / "history.json"
    p.write_text(json.dumps(hist, ensure_ascii=False, indent=1), encoding="utf-8")


# ---------- 상태 대조 ----------

def reconcile(hist: dict):
    """Threads 실제 게시물에서 '#돈수저툰 EP.N' 을 찾아 history 누락분을 복구."""
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


# ---------- 에피소드 ----------

def pick_slot(hist: dict) -> str:
    now = datetime.now(KST)
    cur = now.hour * 60 + now.minute

    def dist(s):
        h, m = map(int, s.split(":"))
        return abs(cur - (h * 60 + m))

    return min(hist.get("schedule_kst", ["09:00"]), key=dist)


def recent_topics(hist: dict) -> list[str]:
    return [(e.get("topic", "") + " " + e.get("title", "")) for e in hist["episodes"][-10:]]


def pick_queue_spec(hist: dict):
    files = sorted((ROOT / "queue").glob("q*.json"))
    recents = recent_topics(hist)
    for f in files:
        spec = json.loads(f.read_text(encoding="utf-8"))
        topic = spec.get("topic", "")
        key = topic.split()[0] if topic else ""
        if key and any(key in r for r in recents):
            log(f"[queue] {f.name} 은 최근 10편과 소재 겹침 → 보류")
            continue
        return f, spec
    return None, None


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
    creation = d["id"]
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


# ---------- 댓글 ----------

def handle_comments(hist: dict):
    replied = set(hist.get("replied", []))
    hidden = set(hist.get("hidden", []))
    n_replied = n_hidden = 0
    me = hist["account"]["username"]
    posts = [e for e in hist["episodes"] if e.get("post_id")][-15:]
    for e in posts:
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
    note_parts = []

    reconcile(hist)

    # 계정 확인 + 쿼터
    _, me = api("GET", "me", fields="id,username")
    if me.get("username") != hist["account"]["username"]:
        notify("돈수저툰: 토큰/계정 확인 필요",
               f"GET /me 결과가 예상 계정과 다릅니다: {me.get('username')} "
               f"(error: {me.get('error')})")
        sys.exit(1)
    _, q = api("GET", f"{UID}/threads_publishing_limit",
               fields="quota_usage,config")
    quota = (q.get("data") or [{}])[0]
    if quota.get("quota_usage", 0) >= quota.get("config", {}).get("quota_total", 250) - 5:
        note_parts.append("쿼터 임박 → 게시 생략")
        posted = None
    else:
        posted = True

    ep_line = "게시 없음"
    if posted:
        qfile, spec = pick_queue_spec(hist)
        if qfile is None:
            notify("돈수저툰: 큐가 비었습니다",
                   "queue/ 에 남은 에피소드 spec 이 없어 이번 회차 게시를 건너뜁니다. "
                   "Cowork 에서 큐를 보충해 주세요.")
            note_parts.append("큐 비어 게시 생략")
        else:
            n = hist["next_episode"]
            date = datetime.now(KST).date().isoformat()
            slot = pick_slot(hist)
            img_rel = f"images/{date}/ep{n:02d}"
            out_dir = ROOT / img_rel
            if not render_episode(spec, n, out_dir):
                notify(f"돈수저툰: EP.{n} 렌더 실패",
                       f"{qfile.name} 렌더가 실패해 이번 회차를 건너뜁니다.")
                note_parts.append("렌더 실패")
            else:
                git_push(f"EP.{n} images")
                urls = [f"{RAW}{img_rel}/{i:02d}.png" for i in range(1, 5)]
                if not wait_raw(urls):
                    notify(f"돈수저툰: EP.{n} raw 이미지 확인 실패",
                           "푸시한 이미지가 raw URL 에서 확인되지 않습니다.")
                    note_parts.append("raw 확인 실패, 게시 생략")
                else:
                    body = spec.get("body", "").replace("{N}", str(n))
                    post_id, err = publish_carousel(urls, body)
                    if err:
                        time.sleep(20)
                        post_id, err = publish_carousel(urls, body)  # 1회 재시도
                    if err:
                        notify(f"돈수저툰: EP.{n} 게시 실패", str(err))
                        note_parts.append(f"게시 실패: {err}")
                    else:
                        _, pd = api("GET", post_id, fields="permalink")
                        permalink = pd.get("permalink", "")
                        hist["episodes"].append({
                            "ep": n, "date": date, "slot": slot,
                            "title": spec.get("title", ""),
                            "topic": spec.get("topic", ""),
                            "post_id": post_id, "permalink": permalink,
                            "images": img_rel,
                        })
                        hist["next_episode"] = n + 1
                        done = ROOT / "queue" / "done"
                        done.mkdir(exist_ok=True)
                        shutil.move(str(qfile), str(done / qfile.name))
                        ep_line = f"EP.{n} 게시 {permalink}"
                        log("[post]", ep_line)

    n_rep, n_hid = handle_comments(hist)

    # 큐 잔량 경고
    left = len(list((ROOT / "queue").glob("q*.json")))
    if left <= 4:
        notify("돈수저툰: 큐 잔량 부족",
               f"queue/ 에 {left}편 남았습니다. Cowork 에서 보충해 주세요.")

    token_note = maybe_refresh_token(hist)
    if token_note:
        note_parts.append(token_note)
        notify("돈수저툰: 토큰 갱신 필요", token_note)

    hist.setdefault("runs", []).append({
        "time": datetime.now(KST).isoformat(timespec="minutes"),
        "ep": ep_line, "replies": n_rep, "hidden": n_hid,
        "note": "; ".join(note_parts) or "ok", "queue_left": left,
    })
    hist["runs"] = hist["runs"][-100:]
    save_history(hist)
    git_push(f"state update ({ep_line}, r{n_rep}/h{n_hid})")
    log(f"[done] {ep_line} / 답글 {n_rep} · 숨김 {n_hid} / 큐 {left}편 남음")


if __name__ == "__main__":
    main()
