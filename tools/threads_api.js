// threads_api.js — 크롬 javascript_tool 에서 실행하는 Threads API 헬퍼.
// 사용법: 탭을 https://graph.threads.net/v1.0/ 로 이동한 뒤, 이 파일 내용 전체를 javascript_tool 로 한 번 실행하면
// window.TA 에 함수들이 생긴다. 이후 호출 예:
//   await TA.init(TOKEN, USER_ID)
//   await TA.publishCarousel(["https://raw.githubusercontent.com/.../01.png", ...], "본문 텍스트")
//   await TA.fetchInbox(["postId1","postId2"], alreadyRepliedIds)
//   await TA.reply(replyId, "답글")
//   await TA.hide(replyId)
// 결과 JSON 은 document.body.innerText 에도 기록되므로 get_page_text 로 읽을 수 있다
// (javascript_tool 반환값은 토큰/긴 문자열이 포함되면 [BLOCKED] 처리될 수 있음).

window.TA = (() => {
  let TOKEN = null, USER = null;
  const H = () => ({ Authorization: 'Bearer ' + TOKEN });
  const sleep = ms => new Promise(r => setTimeout(r, ms));
  const show = obj => { document.body.innerText = JSON.stringify(obj, null, 1); return obj; };

  async function get(path) {
    const r = await fetch(`/v1.0/${path}`, { headers: H() });
    return r.json();
  }
  async function post(path, params) {
    const r = await fetch(`/v1.0/${path}`, { method: 'POST', headers: H(), body: new URLSearchParams(params) });
    return r.json();
  }

  async function init(token, user) {
    TOKEN = token; USER = user;
    const me = await get('me?fields=id,username');
    const lim = await get('me/threads_publishing_limit?fields=quota_usage,config,reply_quota_usage,reply_config');
    return show({ me, limit: lim.data && lim.data[0] });
  }

  async function waitContainer(id, tries = 12) {
    for (let i = 0; i < tries; i++) {
      await sleep(5000);
      const s = await get(`${id}?fields=status,error_message`);
      if (s.status === 'FINISHED') return s;
      if (s.status === 'ERROR' || s.error) return s;
    }
    return { status: 'TIMEOUT' };
  }

  // 4장 캐러셀 게시. 반환: {post_id, permalink} 또는 {error}
  async function publishCarousel(imageUrls, text) {
    const kids = [];
    for (const u of imageUrls) {
      const r = await post(`${USER}/threads`, { media_type: 'IMAGE', image_url: u, is_carousel_item: 'true' });
      if (!r.id) return show({ error: 'item container failed', r, url: u });
      kids.push(r.id);
    }
    const car = await post(`${USER}/threads`, { media_type: 'CAROUSEL', children: kids.join(','), text });
    if (!car.id) return show({ error: 'carousel container failed', car });
    const st = await waitContainer(car.id);
    if (st.status !== 'FINISHED') return show({ error: 'container not finished', st });
    const pub = await post(`${USER}/threads_publish`, { creation_id: car.id });
    if (!pub.id) return show({ error: 'publish failed', pub });
    const info = await get(`${pub.id}?fields=id,permalink,timestamp`);
    return show({ post_id: pub.id, permalink: info.permalink, timestamp: info.timestamp });
  }

  // 텍스트만 게시
  async function publishText(text) {
    const c = await post(`${USER}/threads`, { media_type: 'TEXT', text });
    if (!c.id) return show({ error: 'container failed', c });
    await sleep(3000);
    const pub = await post(`${USER}/threads_publish`, { creation_id: c.id });
    const info = pub.id ? await get(`${pub.id}?fields=id,permalink`) : {};
    return show({ post_id: pub.id, permalink: info.permalink, pub });
  }

  // 내 게시물들의 답글 중 '아직 내가 응답하지 않은 최상위 답글' 수집
  async function fetchInbox(postIds, repliedIds = []) {
    const done = new Set(repliedIds);
    const inbox = [];
    for (const pid of postIds) {
      const c = await get(`${pid}/conversation?fields=id,text,username,timestamp,is_reply_owned_by_me,has_replies,replied_to,hide_status&reverse=false`);
      const rows = (c.data || []);
      const mineUnder = new Set(rows.filter(r => r.is_reply_owned_by_me && r.replied_to).map(r => r.replied_to.id));
      for (const r of rows) {
        if (r.is_reply_owned_by_me) continue;
        if (r.hide_status && r.hide_status !== 'NOT_HUSHED') continue;
        if (r.replied_to && r.replied_to.id !== pid) continue; // 대댓글은 제외 (최상위만)
        if (done.has(r.id) || mineUnder.has(r.id)) continue;
        inbox.push({ post_id: pid, reply_id: r.id, username: r.username, text: r.text, timestamp: r.timestamp });
      }
    }
    return show({ count: inbox.length, inbox });
  }

  async function reply(replyId, text) {
    const c = await post(`${USER}/threads`, { media_type: 'TEXT', text, reply_to_id: replyId });
    if (!c.id) return show({ error: 'reply container failed', c });
    await sleep(2500);
    const pub = await post(`${USER}/threads_publish`, { creation_id: c.id });
    return show({ reply_to: replyId, my_reply_id: pub.id, pub });
  }

  async function hide(replyId) {
    return show(await post(`${replyId}/manage_reply`, { hide: 'true' }));
  }

  // 장기 토큰 갱신 (만료 10일 전부터). 반환 access_token 은 화면에 그대로 찍히므로 get_page_text 로 읽고 update_trigger 로 프롬프트 갱신
  async function refreshToken() {
    const r = await fetch(`/refresh_access_token?grant_type=th_refresh_token&access_token=${encodeURIComponent(TOKEN)}`);
    return show(await r.json());
  }

  return { init, publishCarousel, publishText, fetchInbox, reply, hide, refreshToken, get, post };
})();
'TA ready';
