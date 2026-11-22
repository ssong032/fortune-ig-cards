// Fortune IG approval bot: Telegram buttons -> Instagram publish at 06:00 KST.
//
// Flow
//   1. The nightly Claude routine pushes images/D/{*.jpg, manifest.json} to GitHub.
//   2. Cron (every 5 min) notices tomorrow's manifest and sends a Telegram preview + buttons.
//   3. The owner taps "approve" -> KV post:D marks the parts approved.
//   4. From 06:00 KST on day D, cron publishes approved parts to Instagram (one per tick),
//      then reports the permalink back in Telegram.
//
// Secrets (wrangler secret put): TELEGRAM_BOT_TOKEN, IG_ACCESS_TOKEN, WEBHOOK_SECRET
// KV binding: STATE

const RAW = "https://raw.githubusercontent.com/ssong032/fortune-ig-cards/main";
// New Meta apps use "API setup with Unified login": a Business-portfolio *system user* token
// (starts with "EAA", never expires) against graph.facebook.com. Older Instagram-Login tokens
// ("IGAA…", 60-day, refreshable) use graph.instagram.com. Both are supported.
const GRAPH_VER = "v23.0";
const igBase = (token) => (token.startsWith("IG") ? `https://graph.instagram.com/${GRAPH_VER}` : `https://graph.facebook.com/${GRAPH_VER}`);
const KST = 9 * 3600 * 1000;
const PUBLISH_HOUR = 6;
const NOTIFY_FROM_HOUR = 15; // look for tomorrow's cards from 15:00 KST (routine renders them at 14:30)
const REMIND_HOUR = 23;
const TOKEN_REFRESH_DAYS = 45;
// Videos come through jsDelivr (same repo): raw.githubusercontent serves .mp4 as
// application/octet-stream, which Instagram's video fetcher may reject; jsDelivr sends video/mp4.
const CDN = "https://cdn.jsdelivr.net/gh/ssong032/fortune-ig-cards@main";
const PARTS = {
  ddi: "🐭 띠별 카드", mbti: "🧠 MBTI 카드", reel_ddi: "🎬 띠별 릴스", reel_mbti: "🎬 MBTI 릴스",
  th_ddi: "🧵 띠별 쓰레드", th_mbti: "🧵 MBTI 쓰레드",
};
const CARDS = ["ddi", "mbti"], REELS = ["reel_ddi", "reel_mbti"], THREADS = ["th_ddi", "th_mbti"];
// Threads (cards only, user decision 2026-11-22). Token: THREADS_ACCESS_TOKEN secret, 60-day, auto-refreshed into KV.
const TH = "https://graph.threads.net/v1.0";
const TH_LIMIT = 500;
const REEL_TIMEOUT_MIN = 40; // give up on a reel container that never finishes processing
// Parts offered for a date: set from the manifest when notified; older posts had only the two carousels.
const partsOf = (p) => p.parts || CARDS;
const WD = ["일", "월", "화", "수", "목", "금", "토"];

// ---------- time helpers (all dates are KST calendar dates) ----------
function kstNow() { const d = new Date(Date.now() + KST); return { d, ymd: d.toISOString().slice(0, 10), hour: d.getUTCHours() }; }
function addDays(ymd, n) { const d = new Date(ymd + "T00:00:00Z"); d.setUTCDate(d.getUTCDate() + n); return d.toISOString().slice(0, 10); }
function label(ymd) { const d = new Date(ymd + "T00:00:00Z"); return `${d.getUTCMonth() + 1}/${d.getUTCDate()}(${WD[d.getUTCDay()]})`; }
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ---------- Telegram ----------
async function tg(env, method, payload) {
  const r = await fetch(`https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/${method}`, {
    method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(payload),
  });
  const j = await r.json();
  if (!j.ok) console.log("telegram error", method, JSON.stringify(j));
  return j;
}
async function owner(env) { return await env.STATE.get("owner_chat"); }
async function say(env, text, extra = {}) {
  const chat = await owner(env);
  if (chat) return tg(env, "sendMessage", { chat_id: chat, text, disable_web_page_preview: true, ...extra });
}

// ---------- state ----------
async function getPost(env, ymd) { return JSON.parse((await env.STATE.get(`post:${ymd}`)) || "{}"); }
async function putPost(env, ymd, p) { await env.STATE.put(`post:${ymd}`, JSON.stringify(p), { expirationTtl: 60 * 60 * 24 * 30 }); }
async function manifest(ymd) {
  const r = await fetch(`${RAW}/images/${ymd}/manifest.json?t=${Date.now()}`, { cf: { cacheTtl: 0 } });
  return r.ok ? r.json() : null;
}

// ---------- 부서 보고서 (brief/D.json · D.md · D_qa.md) ----------
async function rawText(path) {
  const r = await fetch(`${RAW}/${path}?t=${Date.now()}`, { cf: { cacheTtl: 0 } });
  return r.ok ? r.text() : null;
}
const CTA_KO = { save: "저장", share: "공유(DM)", follow: "팔로우", link: "프로필 링크" };
const isYmd = (v) => /^\d{4}-\d{2}-\d{2}$/.test(v || "") && !isNaN(new Date(v + "T00:00:00Z"));
const clip = (v, n = 60) => (typeof v === "string" && v.trim() ? (v.length > n ? v.slice(0, n) + "…" : v.trim()) : "");
// 검수표의 최종 판정: "ok" | "hold" | "unknown". 못 읽으면 절대 "ok" 로 보지 않는다.
function qaVerdict(qa) {
  const lines = qa.replace(/\r/g, "").split("\n");
  const idx = lines.findIndex((l) => /게시\s*가능\s*여부|최종\s*판정/.test(l));
  if (idx < 0) return "unknown";
  const clean = (l) => l.replace(/\(?\s*가능\s*\/\s*보류\s*\)?/g, " ").replace(/게시\s*가능\s*여부/g, " ").replace(/최종\s*판정/g, " ");
  for (const l of lines.slice(idx, idx + 3)) { // 판정 줄과 그 아래 2줄(제목 아래에 판정을 쓰는 경우)
    const m = clean(l).match(/(보류|불가|수정\s*후|조건부|\bhold\b|reject)|((?<!불)가능|\bpass\b|\bok\b)/i);
    if (m) return m[1] ? "hold" : "ok";
  }
  return "unknown";
}
function qaScore(qa) {
  const src = qa.split("\n").find((l) => /품질/.test(l) && /\d/.test(l)) || qa;
  const m = src.match(/(\d{1,3})\s*\/\s*100/) || src.match(/(\d{1,3})\s*점(?!\s*만점)/);
  return m && +m[1] <= 100 ? m[1] : null;
}
async function briefSummary(ymd) {
  const lines = [];
  let b = null;
  try { const t = await rawText(`brief/${ymd}.json`); b = t ? JSON.parse(t) : null; } catch (e) { b = null; }
  const mk = b && b.marketing && typeof b.marketing === "object" ? b.marketing : null;
  if (mk) {
    lines.push("📋 이번 기획 (조사·분석부 · 마케팅부)");
    if (clip(mk.theme)) lines.push(`🎯 테마: ${clip(mk.theme)}`);
    const h = mk.hook && typeof mk.hook === "object" ? mk.hook : {};
    if (clip(h.ddi, 30) || clip(h.mbti, 30)) lines.push(`🪝 후킹: 띠별 「${clip(h.ddi, 30) || "-"}」 · MBTI 「${clip(h.mbti, 30) || "-"}」`);
    const c = typeof mk.cta_focus === "string" ? mk.cta_focus.trim().split(/[\s(:,]/)[0].toLowerCase() : "";
    if (CTA_KO[c]) lines.push(`📣 강조: ${CTA_KO[c]}`);
  } else {
    lines.push("📋 이번에는 마케팅 브리프 없이 제작됐어요");
  }
  const qa = (await rawText(`brief/${ymd}_qa.md`)) || "";
  if (!qa.trim()) {
    lines.push("🔍 검수표가 아직 없어요 (보고서에서 확인)");
  } else {
    const v = qaVerdict(qa), sc = qaScore(qa);
    const vt = { ok: "게시 가능", hold: "⚠️ 검수 보류", unknown: "판정 확인 필요" }[v];
    lines.push(`🔍 검수 (검증·품질관리부): ${sc ? `품질 ${sc}점` : "점수 확인 필요"} · ${vt}`);
  }
  return lines.join("\n");
}
// 텔레그램 한 메시지 한도(4096자) 안에서, 줄바꿈 기준으로 자르고 이모지(서로게이트 쌍)가 갈라지지 않게 한다
function chunks(text, size = 3500) {
  const out = [];
  let rest = text;
  while (rest.length > size) {
    let cut = rest.lastIndexOf("\n", size);
    if (cut < size / 2) { cut = size; const c = rest.charCodeAt(cut - 1); if (c >= 0xd800 && c <= 0xdbff) cut -= 1; }
    out.push(rest.slice(0, cut));
    rest = rest.slice(cut).replace(/^\n/, "");
  }
  if (rest) out.push(rest);
  return out;
}
async function sendReport(env, ymd) {
  if (!isYmd(ymd)) return say(env, "보고서는 날짜가 있는 운세 회차에만 있어요. 예: /report 2026-11-24");
  const parts = [["📊 조사·분석부 · 마케팅부 보고", await rawText(`brief/${ymd}.md`)], ["🔍 검증·품질관리부 검수표", await rawText(`brief/${ymd}_qa.md`)]];
  if (!parts.some(([, t]) => t && t.trim())) return say(env, `${label(ymd)} 보고서가 아직 없어요. (브리프는 전날 13:30, 검수표는 전날 14:30 이후에 만들어져요)`);
  for (const [title, text] of parts) {
    if (!text || !text.trim()) { await say(env, `${title} · ${label(ymd)}\n(아직 없음)`); continue; }
    const cs = chunks(text.replace(/\r/g, ""));
    for (let n = 0; n < cs.length; n++) {
      await say(env, `${n ? `(${n + 1}/${cs.length}) ` : `${title} · ${label(ymd)}${cs.length > 1 ? ` (1/${cs.length})` : ""}\n\n`}${cs[n]}`);
    }
  }
}

function statusLine(p) {
  return partsOf(p).map((k) => {
    const s = p[k] || "대기";
    const icon = { approved: "✅ 승인(6시 게시 예정)", publishing: "⏳ 게시 중", processing: "⏳ 처리 중", published: "🎉 게시 완료", skipped: "⏭️ 건너뜀", error: "❌ 오류" }[s] || "⬜ 승인 전";
    return `${PARTS[k]}: ${icon}${p[k + "_link"] ? " " + p[k + "_link"] : ""}`;
  }).join("\n");
}
function keyboard(ymd, p) {
  const parts = partsOf(p);
  const anyApproved = parts.some((k) => p[k] === "approved");
  const anyError = parts.some((k) => p[k] === "error");
  const done = parts.every((k) => ["published", "skipped"].includes(p[k]));
  const reportRow = [{ text: "📊 부서 보고서 보기", callback_data: `B:${ymd}` }];
  if (done) return { inline_keyboard: [reportRow] };
  const rows = [];
  if (!anyApproved && !parts.some((k) => ["publishing", "processing", "published"].includes(p[k]))) {
    const hasReels = parts.some((k) => REELS.includes(k));
    rows.push([{ text: hasReels ? "✅ 전부 6시에 게시 (카드+릴스)" : "✅ 둘 다 6시에 게시", callback_data: `A:${ymd}:all` }]);
    if (hasReels) rows.push([{ text: "🖼 카드뉴스만", callback_data: `A:${ymd}:cards` }, { text: "🎬 릴스만", callback_data: `A:${ymd}:reels` }]);
    rows.push([{ text: "🐭 띠별만", callback_data: `A:${ymd}:ddi` }, { text: "🧠 MBTI만", callback_data: `A:${ymd}:mbti` }]);
    rows.push([{ text: "⏭️ 이번엔 건너뛰기", callback_data: `S:${ymd}` }]);
  } else if (anyApproved) {
    if (parts.some((k) => !p[k])) rows.push([{ text: "➕ 새로 추가된 것도 승인", callback_data: `A:${ymd}:all` }]);
    rows.push([{ text: "↩️ 승인 취소", callback_data: `C:${ymd}` }]);
  }
  if (anyError) rows.push([{ text: "🔁 오류 난 것 다시 시도", callback_data: `R:${ymd}` }]);
  rows.push(reportRow);
  return { inline_keyboard: rows };
}
async function refreshControl(env, ymd, p) {
  if (!p.msg_id) return;
  await tg(env, "editMessageText", {
    chat_id: await owner(env), message_id: p.msg_id, disable_web_page_preview: true,
    text: `${p.head}\n\n${statusLine(p)}`, reply_markup: keyboard(ymd, p),
  });
}

// ---------- Instagram ----------
async function igToken(env) {
  return (await env.STATE.get("ig_token")) || env.IG_ACCESS_TOKEN;
}
async function igCall(url, params, method = "POST") {
  const body = new URLSearchParams(params);
  const r = method === "POST" ? await fetch(url, { method, body }) : await fetch(`${url}?${body}`);
  const j = await r.json();
  if (j.error) {
    const e = j.error, extra = [e.error_user_title, e.error_user_msg].filter(Boolean).join(": ");
    throw new Error(`${e.message || "IG error"} (${e.code || r.status}${e.error_subcode ? "/" + e.error_subcode : ""})${extra ? " - " + extra : ""}`);
  }
  return j;
}
async function igUserId(env, token) {
  let id = env.IG_USER_ID || (await env.STATE.get("ig_user_id"));
  if (id) return id;
  const IG = igBase(token);
  if (token.startsWith("IG")) {
    const me = await igCall(`${IG}/me`, { fields: "user_id,username", access_token: token }, "GET");
    id = String(me.user_id || me.id);
    await env.STATE.put("ig_username", me.username || "");
  } else {
    // System user token: find the Instagram professional account behind the assigned Page(s).
    let pages = { data: [] };
    try { pages = await igCall(`${IG}/me/accounts`, { fields: "name,instagram_business_account{id,username}", access_token: token }, "GET"); } catch (e) { /* page token has no /me/accounts */ }
    let hit = (pages.data || []).find((p) => p.instagram_business_account);
    if (!hit) {
      // Page access token: /me is the Page itself.
      try {
        const me = await igCall(`${IG}/me`, { fields: "name,instagram_business_account{id,username}", access_token: token }, "GET");
        if (me.instagram_business_account) hit = me;
      } catch (e) { /* not a page token */ }
    }
    if (!hit) {
      let perms = "";
      try {
        const pr = await igCall(`${IG}/me/permissions`, { access_token: token }, "GET");
        perms = (pr.data || []).filter((x) => x.status === "granted").map((x) => x.permission).join(",");
      } catch (e) { perms = "? " + e.message; }
      const seen = (pages.data || []).map((p) => `${p.name}${p.instagram_business_account ? "(IG)" : "(no IG)"}`).join(", ") || "none";
      throw new Error(`no IG business account on token pages. pages=[${seen}] perms=[${perms}]`);
    }
    id = hit.instagram_business_account.id;
    await env.STATE.put("ig_username", hit.instagram_business_account.username || "");
  }
  await env.STATE.put("ig_user_id", id);
  return id;
}
async function publishCarousel(env, files, ymd, caption) {
  const token = await igToken(env);
  const IG = igBase(token);
  const uid = await igUserId(env, token);
  const children = [];
  for (const f of files) {
    const c = await igCall(`${IG}/${uid}/media`, { image_url: `${RAW}/images/${ymd}/${f}`, is_carousel_item: "true", access_token: token });
    children.push(c.id);
  }
  const car = await igCall(`${IG}/${uid}/media`, { media_type: "CAROUSEL", children: children.join(","), caption, access_token: token });
  for (let i = 0; i < 6; i++) {
    const s = await igCall(`${IG}/${car.id}`, { fields: "status_code", access_token: token }, "GET");
    if (s.status_code === "FINISHED") break;
    if (s.status_code === "ERROR" || s.status_code === "EXPIRED") throw new Error(`container ${s.status_code}`);
    await sleep(4000);
  }
  const pub = await igCall(`${IG}/${uid}/media_publish`, { creation_id: car.id, access_token: token });
  const m = await igCall(`${IG}/${pub.id}`, { fields: "permalink", access_token: token }, "GET");
  return m.permalink;
}
// Reels take a while to process, so they run across cron ticks:
// tick 1 creates the container, later ticks poll status_code and publish once FINISHED.
async function startReel(env, file, ymd, caption) {
  const token = await igToken(env);
  const uid = await igUserId(env, token);
  const c = await igCall(`${igBase(token)}/${uid}/media`, {
    media_type: "REELS", video_url: `${CDN}/images/${ymd}/${file}`, caption, share_to_feed: "true", access_token: token,
  });
  return c.id;
}
async function checkReel(env, cid) { // -> null while processing, permalink when published
  const token = await igToken(env);
  const IG = igBase(token);
  const s = await igCall(`${IG}/${cid}`, { fields: "status_code,status", access_token: token }, "GET");
  if (s.status_code === "ERROR" || s.status_code === "EXPIRED") throw new Error(`영상 처리 실패 (${s.status_code}${s.status ? ": " + s.status : ""})`);
  if (s.status_code !== "FINISHED") return null;
  const uid = await igUserId(env, token);
  const pub = await igCall(`${IG}/${uid}/media_publish`, { creation_id: cid, access_token: token });
  const m = await igCall(`${IG}/${pub.id}`, { fields: "permalink", access_token: token }, "GET");
  return m.permalink;
}
function approveSet(which, parts) {
  const pick = {
    all: parts, both: CARDS, cards: [...CARDS, ...THREADS], reels: REELS,
    ddi: ["ddi", "reel_ddi", "th_ddi"], mbti: ["mbti", "reel_mbti", "th_mbti"],
  }[which] || [];
  return pick.filter((k) => parts.includes(k));
}

// ---------- Threads ----------
async function thToken(env) { return (await env.STATE.get("th_token")) || env.THREADS_ACCESS_TOKEN || ""; }
// Threads posts max 500 chars and link only one topic tag, so drop the IG hashtag block and keep one tag.
function threadsText(caption) {
  const lines = caption.split("\n").filter((l) => !/^\s*(#\S+\s*)+$/.test(l)).map((l) => l.replace(/\s#\S+/g, ""));
  let text = lines.join("\n").replace(/\n{3,}/g, "\n\n").trim();
  const tail = "\n\n#오늘의운세";
  if (text.length + tail.length > TH_LIMIT) text = text.slice(0, TH_LIMIT - tail.length - 1).trimEnd() + "…";
  return text + tail;
}
async function thUserId(env, token) {
  let id = await env.STATE.get("th_user_id");
  if (id) return id;
  const me = await igCall(`${TH}/me`, { fields: "id,username", access_token: token }, "GET");
  await env.STATE.put("th_user_id", me.id);
  await env.STATE.put("th_username", me.username || "");
  return me.id;
}
async function thWait(cid, token) {
  for (let i = 0; i < 10; i++) {
    const s = await igCall(`${TH}/${cid}`, { fields: "status,error_message", access_token: token }, "GET");
    if (s.status === "FINISHED") return;
    if (s.status === "ERROR" || s.status === "EXPIRED") throw new Error(`쓰레드 처리 실패 (${s.error_message || s.status})`);
    await sleep(3000);
  }
}
// 1단계: 사진(캐러셀 아이템) 컨테이너만 만든다. 처리가 끝나기 전에 캐러셀로 묶으면 "Invalid parameter" 가 나기 때문.
async function startThreads(env, files, ymd) {
  const token = await thToken(env);
  if (!token) throw new Error("쓰레드 토큰 없음");
  const uid = await thUserId(env, token);
  const kids = [];
  for (const f of files.slice(0, 20)) {
    try {
      const c = await igCall(`${TH}/${uid}/threads`, { media_type: "IMAGE", image_url: `${RAW}/images/${ymd}/${f}`, is_carousel_item: "true", access_token: token });
      kids.push(c.id);
    } catch (e) { throw new Error(`쓰레드 사진 등록(${f}) 실패: ${e.message}`); }
  }
  return kids.join(",");
}
// 2단계: 사진이 모두 FINISHED 면 캐러셀을 만들어 게시하고 링크를 돌려준다. 아직 처리 중이면 null.
async function finishThreads(env, kids, caption) {
  const token = await thToken(env);
  const uid = await thUserId(env, token);
  for (const id of kids.split(",")) {
    const s = await igCall(`${TH}/${id}`, { fields: "status,error_message", access_token: token }, "GET");
    if (s.status === "ERROR" || s.status === "EXPIRED") throw new Error(`쓰레드 사진 처리 실패 (${s.error_message || s.status})`);
    if (s.status !== "FINISHED") return null;
  }
  let car;
  try { car = await igCall(`${TH}/${uid}/threads`, { media_type: "CAROUSEL", children: kids, text: threadsText(caption), access_token: token }); }
  catch (e) { throw new Error(`쓰레드 캐러셀 만들기 실패: ${e.message}`); }
  await thWait(car.id, token);
  let pub;
  try { pub = await igCall(`${TH}/${uid}/threads_publish`, { creation_id: car.id, access_token: token }); }
  catch (e) { throw new Error(`쓰레드 게시 실패: ${e.message}`); }
  // 게시는 이미 됐으므로 링크 조회만 실패해도 오류로 두지 않는다(재시도하면 중복 게시됨)
  try { const m = await igCall(`${TH}/${pub.id}`, { fields: "permalink", access_token: token }, "GET"); return m.permalink || "(링크 확인 실패 · 게시는 완료)"; }
  catch (e) { return "(링크 확인 실패 · 게시는 완료)"; }
}
async function publishThreads(env, files, ymd, caption) {
  const token = await thToken(env);
  if (!token) throw new Error("쓰레드 토큰 없음");
  const uid = await thUserId(env, token);
  const children = [];
  for (const f of files.slice(0, 20)) {
    const c = await igCall(`${TH}/${uid}/threads`, { media_type: "IMAGE", image_url: `${RAW}/images/${ymd}/${f}`, is_carousel_item: "true", access_token: token });
    children.push(c.id);
  }
  const car = await igCall(`${TH}/${uid}/threads`, { media_type: "CAROUSEL", children: children.join(","), text: threadsText(caption), access_token: token });
  await thWait(car.id, token);
  const pub = await igCall(`${TH}/${uid}/threads_publish`, { creation_id: car.id, access_token: token });
  const m = await igCall(`${TH}/${pub.id}`, { fields: "permalink", access_token: token }, "GET");
  return m.permalink;
}
// Parts offered for a date: carousels, reels if rendered, Threads copies of the carousels if a token is set.
async function partsFor(env, m) {
  const reels = (m && m.reels) || {};
  return [...CARDS, ...CARDS.filter((k) => reels[k]).map((k) => "reel_" + k), ...((await thToken(env)) ? THREADS : [])];
}

// ---------- cron ----------
async function maybeRefreshThreads(env) {
  const tok = await thToken(env);
  if (!tok) return;
  const ts = Number((await env.STATE.get("th_token_ts")) || 0);
  if (!ts) { await env.STATE.put("th_token_ts", String(Date.now())); return; }
  if (Date.now() - ts < TOKEN_REFRESH_DAYS * 86400e3) return;
  try {
    const j = await igCall("https://graph.threads.net/refresh_access_token", { grant_type: "th_refresh_token", access_token: tok }, "GET");
    await env.STATE.put("th_token", j.access_token);
    await env.STATE.put("th_token_ts", String(Date.now()));
    await say(env, "🔑 쓰레드 토큰을 자동 갱신했어요 (다음 60일 유효).");
  } catch (e) {
    await env.STATE.put("th_token_ts", String(Date.now() - (TOKEN_REFRESH_DAYS - 1) * 86400e3)); // retry tomorrow
    await say(env, `⚠️ 쓰레드 토큰 자동 갱신 실패: ${e.message}\n만료되면 쓰레드 게시만 멈춰요(인스타는 계속). Claude에게 "쓰레드 토큰 다시 발급"을 요청해 주세요.`);
  }
}
async function maybeRefreshToken(env) {
  await maybeRefreshThreads(env);
  if (!(await igToken(env)).startsWith("IG")) return; // system user tokens never expire
  const ts = Number((await env.STATE.get("ig_token_ts")) || 0);
  if (!ts) { await env.STATE.put("ig_token_ts", String(Date.now())); return; }
  if (Date.now() - ts < TOKEN_REFRESH_DAYS * 86400e3) return;
  try {
    const j = await igCall("https://graph.instagram.com/refresh_access_token",
      { grant_type: "ig_refresh_token", access_token: await igToken(env) }, "GET");
    await env.STATE.put("ig_token", j.access_token);
    await env.STATE.put("ig_token_ts", String(Date.now()));
    await say(env, "🔑 인스타 토큰을 자동 갱신했어요 (다음 60일 유효).");
  } catch (e) {
    await env.STATE.put("ig_token_ts", String(Date.now() - (TOKEN_REFRESH_DAYS - 1) * 86400e3)); // retry tomorrow
    await say(env, `⚠️ 인스타 토큰 자동 갱신 실패: ${e.message}\n토큰이 만료되면 게시가 멈춰요. Claude에게 "인스타 토큰 다시 발급"을 요청해 주세요.`);
  }
}

async function maybeNotify(env, now) {
  const target = now.hour >= NOTIFY_FROM_HOUR ? addDays(now.ymd, 1) : now.hour < PUBLISH_HOUR ? now.ymd : null;
  if (!target) return;
  const p = await getPost(env, target);
  if (p.msg_id) {
    if (now.hour === REMIND_HOUR && !p.reminded && !partsOf(p).some((k) => p[k])) {
      p.reminded = true; await putPost(env, target, p);
      await say(env, `⏰ ${label(target)} 운세가 아직 승인 전이에요. 위 메시지에서 승인해 주세요.`, { reply_to_message_id: p.msg_id });
    }
    return;
  }
  const m = await manifest(target);
  if (!m) return;
  const chat = await owner(env);
  if (!chat) return;
  for (const k of CARDS) {
    const media = (m[k] || []).slice(0, 10).map((f) => ({ type: "photo", media: `${RAW}/images/${target}/${f}` }));
    if (media.length) await tg(env, "sendMediaGroup", { chat_id: chat, media });
  }
  const reels = m.reels || {};
  const vids = CARDS.filter((k) => reels[k]).map((k) => ({ type: "video", media: `${CDN}/images/${target}/${reels[k]}`, caption: PARTS["reel_" + k] }));
  if (vids.length) await tg(env, "sendMediaGroup", { chat_id: chat, media: vids });
  p.parts = await partsFor(env, m);
  const cap = (s) => s.split("\n").slice(0, 3).join("\n");
  p.head = `📅 ${label(target)} 운세 준비 완료\n\n🐭 띠별 캡션\n${cap(m.captions.ddi)}\n\n🧠 MBTI 캡션\n${cap(m.captions.mbti)}\n\n${vids.length ? "릴스는 같은 캡션으로 올라가요. " : ""}승인하면 ${label(target)} 오전 6시에 인스타에 자동 게시돼요.`;
  try { const sum = await briefSummary(target); if (sum && (p.head.length + sum.length) < 3500) p.head += `\n\n${sum}`; } catch (e) { console.log("brief summary error", e.stack); }
  const sent = await tg(env, "sendMessage", { chat_id: chat, text: `${p.head}\n\n${statusLine(p)}`, reply_markup: keyboard(target, p), disable_web_page_preview: true });
  p.msg_id = sent.result && sent.result.message_id;
  await putPost(env, target, p);
}

async function maybePublish(env, now) {
  if (now.hour < PUBLISH_HOUR) return;
  const ymd = now.ymd;
  const p = await getPost(env, ymd);
  const parts = partsOf(p);
  const fail = async (part, e) => {
    p[part] = "error"; p[part + "_err"] = e.message; delete p[part + "_cid"]; delete p[part + "_kids"]; await putPost(env, ymd, p);
    await say(env, `❌ ${PARTS[part]} 게시 실패: ${e.message}\n아래 메시지의 '다시 시도'를 누르면 5분 안에 다시 올려요.`, { reply_to_message_id: p.msg_id });
    await refreshControl(env, ymd, p);
  };
  const done = async (part, link) => {
    p[part] = "published"; p[part + "_link"] = link; delete p[part + "_cid"]; delete p[part + "_kids"];
    await putPost(env, ymd, p);
    await say(env, `🎉 ${PARTS[part]} 운세 게시 완료!\n${link}`);
    await refreshControl(env, ymd, p);
  };
  // 1) Reels / Threads already uploaded: poll, publish when ready.
  let threadsDone = false, heavy = false, mf = null;
  for (const part of parts.filter((k) => p[k] === "processing")) {
    try {
      if (THREADS.includes(part)) {
        if (threadsDone) continue; // 한 tick 에 Threads 하나만 마무리 (서브요청 50개 한도)
        threadsDone = true;
        if (!p[part + "_kids"]) throw new Error("쓰레드 사진 목록 없음 (다시 시도를 눌러 주세요)");
        mf = mf || (await manifest(ymd));
        if (!mf) continue; // manifest 를 잠시 못 받으면 다음 tick 에 다시
        const link = await finishThreads(env, p[part + "_kids"], mf.captions[part.slice(3)]);
        if (link) { heavy = true; await done(part, link); }
        else if (Date.now() - (p[part + "_t"] || 0) > REEL_TIMEOUT_MIN * 60e3) await fail(part, new Error(`${REEL_TIMEOUT_MIN}분 넘게 쓰레드 사진 처리가 끝나지 않음`));
        continue;
      }
      const link = await checkReel(env, p[part + "_cid"]);
      if (link) { heavy = true; await done(part, link); }
      else if (Date.now() - (p[part + "_t"] || 0) > REEL_TIMEOUT_MIN * 60e3) await fail(part, new Error(`${REEL_TIMEOUT_MIN}분 넘게 영상 처리가 끝나지 않음`));
    } catch (e) { await fail(part, e); }
  }
  // 2) Start one approved part per tick (keeps subrequests < 50). Carousels first.
  //    이번 tick 에 이미 게시(마무리)를 했다면 새 작업은 다음 tick 으로 미룬다.
  if (heavy) return;
  const part = parts.find((k) => p[k] === "approved");
  if (!part) return;
  const m = mf || (await manifest(ymd));
  if (!m) return fail(part, new Error("manifest 없음"));
  try {
    if (REELS.includes(part)) {
      const file = (m.reels || {})[part.slice(5)];
      if (!file) throw new Error("릴스 파일 없음");
      p[part + "_cid"] = await startReel(env, file, ymd, m.captions[part.slice(5)]);
      p[part] = "processing"; p[part + "_t"] = Date.now();
      await putPost(env, ymd, p); await refreshControl(env, ymd, p);
    } else if (THREADS.includes(part)) {
      const k = part.slice(3);
      p[part + "_kids"] = await startThreads(env, m[k], ymd);
      p[part] = "processing"; p[part + "_t"] = Date.now();
      await putPost(env, ymd, p); await refreshControl(env, ymd, p);
    } else {
      p[part] = "publishing"; await putPost(env, ymd, p);
      await done(part, await publishCarousel(env, m[part], ymd, m.captions[part]));
    }
  } catch (e) { await fail(part, e); }
}

async function tick(env) {
  const now = kstNow();
  await maybeRefreshToken(env);
  await maybeNotify(env, now);
  await maybePublish(env, now);
}

// ---------- webhook ----------
async function onUpdate(env, u) {
  const chatOwner = await owner(env);
  if (u.message) {
    const chat = String(u.message.chat.id), text = (u.message.text || "").trim();
    if (text.startsWith("/start")) {
      if (!chatOwner) { await env.STATE.put("owner_chat", chat); return tg(env, "sendMessage", { chat_id: chat, text: "✅ 연결 완료! 매일 밤 다음 날 운세가 준비되면 여기로 승인 요청을 보낼게요." }); }
      if (chatOwner !== chat) return; // ignore strangers
      return tg(env, "sendMessage", { chat_id: chat, text: "이미 연결돼 있어요. /status 로 상태를, /report 로 부서 보고서를 볼 수 있어요." });
    }
    if (chatOwner !== chat) return;
    if (/^\/report(\s|$)/.test(text)) {
      const arg = text.split(/\s+/)[1];
      const now = kstNow();
      const ymd = isYmd(arg) ? arg : now.hour >= NOTIFY_FROM_HOUR ? addDays(now.ymd, 1) : now.ymd;
      return sendReport(env, ymd);
    }
    if (text.startsWith("/status")) {
      const now = kstNow(), ts = Number((await env.STATE.get("ig_token_ts")) || 0);
      const days = ts ? Math.floor((Date.now() - ts) / 86400e3) : "?";
      const lines = [];
      for (const d of [now.ymd, addDays(now.ymd, 1)]) lines.push(`${label(d)}\n${statusLine(await getPost(env, d))}`);
      return say(env, `📊 상태\n\n${lines.join("\n\n")}\n\n🔑 인스타 토큰: 마지막 갱신 ${days}일 전 (${TOKEN_REFRESH_DAYS}일마다 자동 갱신)\n계정: @${(await env.STATE.get("ig_username")) || "?"}`);
    }
    return;
  }
  const q = u.callback_query;
  if (!q || String(q.message.chat.id) !== chatOwner) return;
  const [op, ymd, which] = q.data.split(":");
  if (op === "B") {
    if (!isYmd(ymd)) return tg(env, "answerCallbackQuery", { callback_query_id: q.id, text: "이 메시지에는 보고서가 없어요" });
    await tg(env, "answerCallbackQuery", { callback_query_id: q.id, text: "보고서를 보내 드릴게요" });
    return sendReport(env, ymd);
  }
  const p = await getPost(env, ymd);
  const now = kstNow();
  let note = "";
  const parts = partsOf(p);
  if (op === "A") {
    for (const k of approveSet(which, parts)) if (!p[k] || p[k] === "error") p[k] = "approved";
    for (const k of parts) if (!p[k]) p[k] = "skipped";
    note = ymd === now.ymd && now.hour >= PUBLISH_HOUR ? "승인! 5분 안에 게시돼요" : "승인! 6시에 게시돼요";
  } else if (op === "S") {
    for (const k of parts) if (!p[k]) p[k] = "skipped";
    note = "이번 회차는 건너뛸게요";
  } else if (op === "C") {
    for (const k of parts) if (["approved", "skipped"].includes(p[k])) delete p[k];
    note = "승인을 취소했어요";
  } else if (op === "R") {
    for (const k of parts) if (p[k] === "error") p[k] = "approved";
    note = "5분 안에 다시 시도할게요";
  }
  await putPost(env, ymd, p);
  await tg(env, "answerCallbackQuery", { callback_query_id: q.id, text: note });
  await refreshControl(env, ymd, p);
}

export default {
  async fetch(req, env, ctx) {
    const url = new URL(req.url);
    if (url.pathname === "/tg" && req.method === "POST") {
      if (req.headers.get("X-Telegram-Bot-Api-Secret-Token") !== env.WEBHOOK_SECRET) return new Response("forbidden", { status: 403 });
      ctx.waitUntil(onUpdate(env, await req.json()).catch((e) => console.log("update error", e.stack)));
      return new Response("ok");
    }
    if (url.pathname === "/setup" && url.searchParams.get("k") === env.WEBHOOK_SECRET) {
      const hook = await tg(env, "setWebhook", { url: `${url.origin}/tg`, secret_token: env.WEBHOOK_SECRET, allowed_updates: ["message", "callback_query"] });
      let ig;
      try {
        const token = await igToken(env);
        await env.STATE.delete("ig_user_id");
        const uid = await igUserId(env, token);
        const lim = await igCall(`${igBase(token)}/${uid}/content_publishing_limit`, { fields: "quota_usage,config", access_token: token }, "GET");
        if (!(await env.STATE.get("ig_token_ts"))) await env.STATE.put("ig_token_ts", String(Date.now()));
        ig = { ok: true, user_id: uid, username: await env.STATE.get("ig_username"), publishing_limit: lim.data };
      } catch (e) { ig = { ok: false, error: e.message }; }
      let threads = { ok: false, error: "no THREADS_ACCESS_TOKEN" };
      const tht = await thToken(env);
      if (tht) {
        try {
          await env.STATE.delete("th_user_id");
          const id = await thUserId(env, tht);
          if (!(await env.STATE.get("th_token_ts"))) await env.STATE.put("th_token_ts", String(Date.now()));
          threads = { ok: true, user_id: id, username: await env.STATE.get("th_username") };
        } catch (e) { threads = { ok: false, error: e.message }; }
      }
      return Response.json({ webhook: hook, instagram: ig, threads, owner_chat_set: !!(await owner(env)) });
    }
    if (url.pathname === "/test" && url.searchParams.get("k") === env.WEBHOOK_SECRET) {
      // Dry-run preview: real images + buttons, but under the key "TEST" which maybePublish never reads.
      const chat = await owner(env);
      if (!chat) return new Response("no owner yet");
      const d = url.searchParams.get("d") || "2026-11-23";
      const files = (pre, n) => Array.from({ length: n }, (_, i) => `${pre}_${String(i + 1).padStart(2, "0")}.png`);
      for (const f of [files("ddi", 9), files("mbti", 7)]) {
        await tg(env, "sendMediaGroup", { chat_id: chat, media: f.map((x) => ({ type: "photo", media: `${RAW}/images/${d}/${x}` })) });
      }
      await env.STATE.delete("post:TEST");
      const p = { head: `🧪 테스트 알림 (${d} 카드)\n\n버튼을 눌러 보세요. 테스트라서 실제로 게시되지는 않아요.` };
      const sent = await tg(env, "sendMessage", { chat_id: chat, text: `${p.head}\n\n${statusLine(p)}`, reply_markup: keyboard("TEST", p) });
      p.msg_id = sent.result && sent.result.message_id;
      await putPost(env, "TEST", p);
      return new Response(sent.ok ? "test sent" : "send failed");
    }
    if (url.pathname === "/notify" && url.searchParams.get("k") === env.WEBHOOK_SECRET) {
      // Send the approval request for date d right now (as if it were 21:00 the night before).
      const d = url.searchParams.get("d");
      if (!/^\d{4}-\d{2}-\d{2}$/.test(d || "")) return new Response("bad d", { status: 400 });
      if (url.searchParams.get("force") === "1") { // re-send a fresh message, keeping approvals already made
        const old = await getPost(env, d); delete old.msg_id; delete old.reminded; await putPost(env, d, old);
      }
      await maybeNotify(env, { ymd: addDays(d, -1), hour: NOTIFY_FROM_HOUR });
      return new Response((await getPost(env, d)).msg_id ? "notified" : "no manifest / no owner");
    }
    if (url.pathname === "/reelcheck" && url.searchParams.get("k") === env.WEBHOOK_SECRET) {
      // Upload-only check: creates a REELS container (never published; it expires in 24h) and reports its status.
      try {
        const cid = await startReel(env, url.searchParams.get("f") || "reel_ddi.mp4", url.searchParams.get("d") || "", "test");
        const token = await igToken(env);
        let s = {};
        for (let i = 0; i < 6; i++) {
          await sleep(5000);
          s = await igCall(`${igBase(token)}/${cid}`, { fields: "status_code,status", access_token: token }, "GET");
          if (s.status_code !== "IN_PROGRESS") break;
        }
        return Response.json({ container: cid, status_code: s.status_code, status: s.status });
      } catch (e) { return Response.json({ error: e.message }); }
    }
    if (url.pathname === "/reels" && url.searchParams.get("k") === env.WEBHOOK_SECRET) {
      // Attach reels to a date whose approval message went out before its manifest had reels.
      const d = url.searchParams.get("d") || "";
      const p = await getPost(env, d), m = await manifest(d), chat = await owner(env);
      if (!p.msg_id || !m || !m.reels || !chat) return new Response("nothing to attach");
      const vids = CARDS.filter((k) => m.reels[k]).map((k) => ({ type: "video", media: `${CDN}/images/${d}/${m.reels[k]}`, caption: PARTS["reel_" + k] }));
      if (url.searchParams.get("videos") !== "0") await tg(env, "sendMediaGroup", { chat_id: chat, media: vids, reply_to_message_id: p.msg_id });
      p.parts = await partsFor(env, m);
      await putPost(env, d, p);
      await refreshControl(env, d, p);
      return new Response("reels attached");
    }
    if (url.pathname === "/tick" && url.searchParams.get("k") === env.WEBHOOK_SECRET) { await tick(env); return new Response("tick done"); }
    return new Response("fortune-ig bot");
  },
  async scheduled(event, env, ctx) { ctx.waitUntil(tick(env)); },
};
