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
const NOTIFY_FROM_HOUR = 21; // look for tomorrow's cards from 21:00 KST
const REMIND_HOUR = 23;
const TOKEN_REFRESH_DAYS = 45;
const PARTS = { ddi: "🐭 띠별", mbti: "🧠 MBTI" };
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

function statusLine(p) {
  return Object.keys(PARTS).map((k) => {
    const s = p[k] || "대기";
    const icon = { approved: "✅ 승인(6시 게시 예정)", publishing: "⏳ 게시 중", published: "🎉 게시 완료", skipped: "⏭️ 건너뜀", error: "❌ 오류" }[s] || "⬜ 승인 전";
    return `${PARTS[k]}: ${icon}${p[k + "_link"] ? " " + p[k + "_link"] : ""}`;
  }).join("\n");
}
function keyboard(ymd, p) {
  const anyApproved = Object.keys(PARTS).some((k) => p[k] === "approved");
  const anyError = Object.keys(PARTS).some((k) => p[k] === "error");
  const done = Object.keys(PARTS).every((k) => ["published", "skipped"].includes(p[k]));
  if (done) return { inline_keyboard: [] };
  const rows = [];
  if (!anyApproved) {
    rows.push([{ text: "✅ 둘 다 6시에 게시", callback_data: `A:${ymd}:both` }]);
    rows.push([{ text: "🐭 띠별만", callback_data: `A:${ymd}:ddi` }, { text: "🧠 MBTI만", callback_data: `A:${ymd}:mbti` }]);
    rows.push([{ text: "⏭️ 이번엔 건너뛰기", callback_data: `S:${ymd}` }]);
  } else {
    rows.push([{ text: "↩️ 승인 취소", callback_data: `C:${ymd}` }]);
  }
  if (anyError) rows.push([{ text: "🔁 오류 난 것 다시 시도", callback_data: `R:${ymd}` }]);
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
  if (j.error) throw new Error(`${j.error.message || "IG error"} (${j.error.code || r.status})`);
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

// ---------- cron ----------
async function maybeRefreshToken(env) {
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
    if (now.hour === REMIND_HOUR && !p.reminded && !Object.keys(PARTS).some((k) => p[k])) {
      p.reminded = true; await putPost(env, target, p);
      await say(env, `⏰ ${label(target)} 운세가 아직 승인 전이에요. 위 메시지에서 승인해 주세요.`, { reply_to_message_id: p.msg_id });
    }
    return;
  }
  const m = await manifest(target);
  if (!m) return;
  const chat = await owner(env);
  if (!chat) return;
  for (const k of Object.keys(PARTS)) {
    const media = m[k].slice(0, 10).map((f) => ({ type: "photo", media: `${RAW}/images/${target}/${f}` }));
    if (media.length) await tg(env, "sendMediaGroup", { chat_id: chat, media });
  }
  const cap = (s) => s.split("\n").slice(0, 3).join("\n");
  p.head = `📅 ${label(target)} 운세 준비 완료\n\n🐭 띠별 캡션\n${cap(m.captions.ddi)}\n\n🧠 MBTI 캡션\n${cap(m.captions.mbti)}\n\n승인하면 ${label(target)} 오전 6시에 인스타에 자동 게시돼요.`;
  const sent = await tg(env, "sendMessage", { chat_id: chat, text: `${p.head}\n\n${statusLine(p)}`, reply_markup: keyboard(target, p), disable_web_page_preview: true });
  p.msg_id = sent.result && sent.result.message_id;
  await putPost(env, target, p);
}

async function maybePublish(env, now) {
  if (now.hour < PUBLISH_HOUR) return;
  const ymd = now.ymd;
  const p = await getPost(env, ymd);
  const part = Object.keys(PARTS).find((k) => p[k] === "approved"); // one part per tick keeps subrequests < 50
  if (!part) return;
  const m = await manifest(ymd);
  if (!m) { p[part] = "error"; p[part + "_err"] = "manifest 없음"; await putPost(env, ymd, p); await refreshControl(env, ymd, p); return; }
  p[part] = "publishing"; await putPost(env, ymd, p);
  try {
    const link = await publishCarousel(env, m[part], ymd, m.captions[part]);
    p[part] = "published"; p[part + "_link"] = link;
    await putPost(env, ymd, p);
    await say(env, `🎉 ${PARTS[part]} 운세 게시 완료!\n${link}`);
  } catch (e) {
    p[part] = "error"; p[part + "_err"] = e.message; await putPost(env, ymd, p);
    await say(env, `❌ ${PARTS[part]} 게시 실패: ${e.message}\n아래 메시지의 '다시 시도'를 누르면 5분 안에 다시 올려요.`, { reply_to_message_id: p.msg_id });
  }
  await refreshControl(env, ymd, p);
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
      return tg(env, "sendMessage", { chat_id: chat, text: "이미 연결돼 있어요. /status 로 상태를 볼 수 있어요." });
    }
    if (chatOwner !== chat) return;
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
  const p = await getPost(env, ymd);
  const now = kstNow();
  let note = "";
  if (op === "A") {
    for (const k of which === "both" ? Object.keys(PARTS) : [which]) if (!p[k] || p[k] === "error") p[k] = "approved";
    for (const k of Object.keys(PARTS)) if (!p[k]) p[k] = "skipped";
    note = ymd === now.ymd && now.hour >= PUBLISH_HOUR ? "승인! 5분 안에 게시돼요" : "승인! 6시에 게시돼요";
  } else if (op === "S") {
    for (const k of Object.keys(PARTS)) if (!p[k]) p[k] = "skipped";
    note = "이번 회차는 건너뛸게요";
  } else if (op === "C") {
    for (const k of Object.keys(PARTS)) if (["approved", "skipped"].includes(p[k])) delete p[k];
    note = "승인을 취소했어요";
  } else if (op === "R") {
    for (const k of Object.keys(PARTS)) if (p[k] === "error") p[k] = "approved";
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
      return Response.json({ webhook: hook, instagram: ig, owner_chat_set: !!(await owner(env)) });
    }
    if (url.pathname === "/tick" && url.searchParams.get("k") === env.WEBHOOK_SECRET) { await tick(env); return new Response("tick done"); }
    return new Response("fortune-ig bot");
  },
  async scheduled(event, env, ctx) { ctx.waitUntil(tick(env)); },
};
