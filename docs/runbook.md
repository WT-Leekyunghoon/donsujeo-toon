# 돈수저툰 자동 게시 런북 (Cowork 예약 작업용)

매 회차(하루 5회)에 새 세션이 이 절차를 그대로 수행한다. 사람은 없다고 가정하고, 막히면 그 회차는 건너뛰고 사유만 남긴다.

## 0. 준비
- 크롬 도구 로드: `ToolSearch select:mcp__claude-in-chrome__tabs_context_mcp,navigate,javascript_tool,get_page_text,find,file_upload,computer`
- `tabs_context_mcp {createIfEmpty:true}` → 새 탭 사용.
- 상수: REPO = `WT-Leekyunghoon/donsujeo-toon`, RAW = `https://raw.githubusercontent.com/WT-Leekyunghoon/donsujeo-toon/main/`
- 토큰·유저ID는 예약 작업 프롬프트에 있음. 대화·로그·GitHub 어디에도 토큰을 적지 말 것.

## 1. 상태·가이드 읽기 (크롬으로 raw 파일 열어서 get_page_text)
- `RAW + state/history.json` → 그대로 파싱 (직전 10편 제목/주제, replied 목록, next_episode).
- `RAW + docs/persona.md` → 말투·구조·주제풀·금지사항.
- `RAW + tools/render_toon.py` → 샌드박스 `/home/claude/toon/render_toon.py` 로 저장 (get_page_text 결과를 그대로 Write).
- `RAW + tools/threads_api.js` → 내용 기억(3단계에서 javascript_tool 로 실행).
  ※ raw 페이지는 텍스트 그대로 보이므로 get_page_text 가 원문 그대로를 돌려준다. 잘렸으면 다시 읽는다.

## 2. 이번 편 만들기
- 회차 번호 N = history.next_episode. 날짜 D = 오늘(KST). 슬롯 = 현재 시각에 가장 가까운 schedule_kst.
- persona.md 주제풀에서 **직전 10편과 겹치지 않는** 국내 ETF 주제 1개 선택. 아침(09:00)엔 기초 개념, 낮(11:30·14:00)엔 지수/섹터·절세, 저녁(17:00·20:00)엔 습관·심리 쪽을 우선하면 하루 흐름이 자연스럽다.
- spec.json 작성 (docs/sample_spec.json 형식, panels 4개, episode "EP.N", 금지사항 점검).
- 렌더: `pip list | grep -i playwright` 확인 후 `python3 /home/claude/toon/render_toon.py spec.json /mnt/user-data/outputs/toon/D/epNN/` → 01~04.png
- 4장을 Read 로 한 번 훑어 글자 넘침·오타 확인. 문제 있으면 spec 고치고 재렌더.
- 본문 텍스트 작성 (persona.md "게시글 본문" 형식, 500바이트 이내).

## 3. 이미지 올리기 (GitHub 웹 업로드)
- navigate `https://github.com/WT-Leekyunghoon/donsujeo-toon/upload/main/images/D/epNN`
- find "file input (choose your files)" → file_upload 로 4장 업로드 → "Commit changes" 버튼 클릭 → 커밋 완료 확인(주소가 repo 트리로 바뀜).
- 이미지 URL = `RAW + images/D/epNN/01.png` … 04.png

## 4. 스레드 게시
- navigate `https://graph.threads.net/v1.0/` (빈 페이지 정상).
- javascript_tool 로 threads_api.js 전체 실행 → 'TA ready'.
- `await TA.init(TOKEN, USER_ID)` → get_page_text 로 me.username == etfspoon 확인. quota_usage 가 config.quota_total 에 가까우면 게시 중단.
- `await TA.publishCarousel([url1..url4], 본문)` → get_page_text 로 post_id, permalink 확보. error 면 1회만 재시도.

## 5. 댓글 처리
- postIds = history.episodes 최근 15편의 post_id.
- `await TA.fetchInbox(postIds, history.replied)` → inbox.
- 각 항목: persona.md 답글 규칙으로 분류 → 스팸/광고면 `TA.hide(reply_id)` 후 hidden 에 기록, 답할 가치 있으면 답글 작성 → `TA.reply(reply_id, 답글)` 후 replied 에 reply_id 추가. 답 안 하는 것도 replied 에 넣어 재검토 방지.
- 회차당 최대 15개.

## 6. 상태 저장
- history.json 갱신: episodes 에 이번 편 추가(ep, date, slot, title, topic, post_id, permalink, images), next_episode+1, replied/hidden 갱신, runs 에 {time, ep, replies, hidden, note} 한 줄.
- `/mnt/user-data/outputs/state/history.json` 로 저장 후 navigate `https://github.com/WT-Leekyunghoon/donsujeo-toon/upload/main/state` → file_upload → Commit changes (같은 이름이라 덮어써짐).

## 7. 토큰 갱신 (history.account.token_expires_at 까지 10일 이하일 때만)
- `await TA.refreshToken()` → get_page_text 로 access_token, expires_in 확보 → `mcp__claude-code-remote__list_triggers` 로 이 작업(이름 "돈수저툰 …") 찾아 `update_trigger` 로 프롬프트 안의 THREADS_ACCESS_TOKEN 값을 새 토큰으로 교체, history.account.token_expires_at 도 갱신.

## 8. 보고
- 마지막에 SendUserMessage 로 3줄: EP.N 제목 + permalink / 답글 n개·숨김 m개 / 문제 있으면 사유. 실패 시에도 반드시 보고.

## 실패 시 규칙
- 크롬 도구가 없거나 탭이 안 열림 → "PC/크롬 꺼짐"으로 보고하고 종료(다음 회차에 자동 재개).
- 렌더 실패 → spec 단순화 후 1회 재시도, 그래도 실패면 텍스트만 `TA.publishText` 로 게시하지 **말고** 건너뛴다(툰 없는 글은 컨셉 훼손).
- 게시는 됐는데 history 저장 실패 → 보고 메시지에 post_id/permalink 를 남겨 다음 회차가 복구할 수 있게 한다.
