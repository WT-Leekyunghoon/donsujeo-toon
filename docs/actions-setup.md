# 돈수저툰 — GitHub Actions 무인 운영 (v2, 큐 방식)

컴퓨터가 꺼져 있어도 GitHub Actions가 매일 5회 자동 게시한다.

| KST | 슬롯 | 내용 |
|---|---|---|
| 10:00 | toon | 그림툰 ① (4컷 캐러셀) |
| 12:00 | tip | 툰①에 대한 보충 설명·팁 (글 + 툰 패널 1장 첨부) |
| 14:00 | news | 그날의 경제 뉴스 해설 (글) — 토·일·공휴일은 그 주 소식 정리(주간 리캡) |
| 17:00 | toon | 그림툰 ② (4컷 캐러셀) |
| 19:00 | tip | 툰②에 대한 보충 설명·팁 (글 + 패널 첨부) |

콘텐츠는 Cowork 예약 작업(Claude)이 매일 아침 `queue/daily/YYYY-MM-DD/` 에
미리 만들어 둔다 — 평일엔 당일치, **금요일엔 주말치까지, 공휴일 전날엔
공휴일치까지** (절차: `docs/generation-runbook.md`). Actions 는 매 슬롯에
해당 날짜 파일을 꺼내 게시만 한다.

## 폴백 규칙 (daily 파일이 없을 때)

- 툰 슬롯: 에버그린 큐 `queue/q*.json` 에서 순서대로 꺼내 게시 (소재가 직전
  10편과 겹치면 건너뜀).
- 팁·뉴스 슬롯: 게시 생략 (툰 없는 팁, 뉴스 없는 뉴스는 안 올린다).

## 1회 설정 (Settings → Secrets and variables → Actions)

| Secret | 값 |
|---|---|
| `THREADS_ACCESS_TOKEN` | threads_auth.txt 의 토큰 (필수) |
| `THREADS_USER_ID` | `28417624194530447` (필수) |
| `GH_PAT` | repo 권한 PAT — 토큰 자동 갱신 시 Secret 자동 교체용 (선택) |

설정 후 Actions 탭 → donsujeo-toon → **Run workflow** 로 1회 수동 실행해 확인.
Secrets 미설정 상태에서는 워크플로가 아무 것도 하지 않고 조용히 끝난다.

## 파일 형식

- 툰(`1000.json`/`1700.json`): `docs/sample_spec.json` 과 동일 + `topic`,
  `title`, `body`(`{N}` → 회차 번호 치환). EP 번호는 러너가 게시 시점에 부여.
- 팁(`1200.json`/`1900.json`): `{"type":"tip","title":"...","body":"...","attach_panel":3}`
  — 같은 날 원본 툰(12시→10시, 19시→17시)의 해당 패널 PNG 를 첨부. body 의
  `{PERMALINK}` 는 원본 툰 링크로 치환.
- 뉴스(`1400.json`): `{"type":"news","title":"...","body":"..."}` — 텍스트만.
- 게시 완료된 daily 파일은 `.done` 으로 이름이 바뀐다.

## 러너가 알아서 하는 것

- Threads 실제 게시물과 history.json 대조 → 누락 회차 자동 복구.
- 같은 날 같은 슬롯 중복 게시 방지 (재실행 안전).
- 스팸 댓글 숨김, "뭐 사요?"류 정형 답글, 그 외 댓글은 기록만 (회차당 15개 제한).
- 쿼터 임박 시 게시 생략. 토큰 만료 10일 전 자동 갱신(GH_PAT 있을 때).
- 실패·큐 부족·토큰 문제는 repo 이슈 생성 → GitHub 알림 메일.

## 주의

- 예전 방식(브라우저로 직접 게시하는 예약 작업)과 동시에 켜두면 **중복 게시**된다.
  예약 작업은 콘텐츠 생성 전용(generation-runbook.md)으로만 운영할 것.
- Actions cron 은 몇 분(최대 15분 안팎) 지연될 수 있다.
