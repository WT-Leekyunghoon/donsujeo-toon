# 하마의 ETF 도전기 — GitHub Actions 무인 운영 (v3, 2026-10-06)

컴퓨터가 꺼져 있어도 GitHub Actions가 매일 3회 자동 게시한다.
한 번 실행에 1편만 올리고, 직전 게시로부터 100분 안 지났으면 게시하지 않는다 (연달아 게시 금지).
(2026-10-06 새 계정·하마 캐릭터로 재시작. 옛 @etfspoon 자료는 `archive/etfspoon/`.)

| KST | 슬롯 | 파일 | 내용 |
|---|---|---|---|
| 10:00 | news | `1000.json` | 오전 경제 동향 (글) |
| 12:00 | toon | `1200.json` + `1200.png` | 하마 4컷툰 완성 이미지 1장 + 글 |
| 17:00 | news | `1700.json` | 오후 경제 뉴스 (글) |

콘텐츠는 예약 작업(Claude)이 `queue/daily/YYYY-MM-DD/` 에 미리 만든다 (`docs/generation-runbook.md`).
파일이 없으면 그 슬롯은 건너뛴다 (폴백 큐 없음).

## 1회 설정 (Settings → Secrets and variables → Actions)

| Secret | 값 |
|---|---|
| `THREADS_ACCESS_TOKEN` | 새 계정의 Threads 액세스 토큰 (필수) |
| `GH_PAT` | repo 권한 PAT — 토큰 자동 갱신 시 Secret 자동 교체용 (선택) |

사용자 ID 는 토큰으로 자동 확인한다 (`THREADS_USER_ID` 불필요 — 있어도 무시).
첫 실행 때 `state/history.json` 의 account 에 새 계정 아이디가 기록되고, 이후엔 그 계정이 아니면 게시하지 않는다.

## 파일 형식
- 툰: `{"type":"toon","title":"...","topic":"...","body":"... #하마의ETF도전기 EP.{N} ..."}` — 같은 폴더의 `1200.png` 첨부
  (다른 경로면 `"image":"저장소 상대경로"`). `{N}` 은 회차 번호로 치환.
- 뉴스: `{"type":"news","title":"...","body":"..."}` — 필요하면 `"image":"저장소 상대경로"` 로 한 장 첨부.
- 본문 500자 초과 시 Threads 가 거부 → 475자 이하로.
- 게시 완료된 json 은 `.done` 으로 이름이 바뀐다.

## 러너가 알아서 하는 것
- Threads 실제 게시물과 history 대조 → 누락 회차 복구, 같은 슬롯 중복 게시 방지.
- 스팸 댓글 숨김, "뭐 사요?"류 정형 답글.
- 쿼터 임박 시 게시 생략, 실패·토큰 문제는 repo 이슈 → GitHub 알림 메일.

## 주의
- Actions cron 은 지연·누락이 잦아 KST 10~22시 30분 간격(11·41분)으로 돌며 밀린 슬롯을 따라잡는다. 게시 시각이 수십 분 늦을 수 있다.
