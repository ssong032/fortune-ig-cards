"""Render the daily fortune carousels (띠별 8장 + MBTI 6장) to 1080x1350 PNGs.

usage: python render.py data.json OUT_DIR [--browser PATH]
"""
import argparse, json, os, shutil, subprocess, sys, html
from pathlib import Path

W, H = 1080, 1350
FONT = "'Pretendard','Noto Sans KR','Malgun Gothic',sans-serif"
EMOJI = "'Segoe UI Emoji','Apple Color Emoji','Noto Color Emoji'"

THEMES = {
    "zodiac": dict(bg="linear-gradient(165deg,#FFF7EA 0%,#FBE6D4 55%,#F6D6C8 100%)",
                   ink="#2B2340", sub="#7A6A66", accent="#C8912E", card="rgba(255,255,255,.78)",
                   chip="#FFF1DC"),
    "mbti": dict(bg="linear-gradient(165deg,#F1F1FF 0%,#E4ECFB 55%,#DDF0F6 100%)",
                 ink="#22264A", sub="#666C8C", accent="#5B5BD6", card="rgba(255,255,255,.8)",
                 chip="#ECEBFF"),
}

def esc(s): return html.escape(str(s))

def stars(n, accent):
    return (f'<span style="color:{accent}">' + "★" * n + '</span>'
            f'<span style="color:rgba(0,0,0,.14)">' + "★" * (5 - n) + '</span>')

def page(theme, body, idx, total, header):
    t = THEMES[theme]
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
*{{margin:0;padding:0;box-sizing:border-box}}
html,body{{width:{W}px;height:{H}px;overflow:hidden}}
body{{background:{t['bg']};color:{t['ink']};font-family:{FONT};position:relative;
  -webkit-font-smoothing:antialiased;word-break:keep-all}}
.e{{font-family:{EMOJI};}}
.head{{position:absolute;top:64px;left:72px;right:72px;display:flex;justify-content:space-between;
  font-size:30px;font-weight:700;letter-spacing:.06em;color:{t['sub']}}}
.foot{{position:absolute;bottom:56px;left:0;right:0;text-align:center;font-size:26px;color:{t['sub']};
  letter-spacing:.1em}}
.wrap{{position:absolute;top:150px;bottom:120px;left:64px;right:64px;display:flex;flex-direction:column;
  justify-content:center;gap:40px}}
.card{{background:{t['card']};border-radius:44px;padding:48px 52px;box-shadow:0 18px 50px rgba(60,40,80,.10);
  position:relative}}
.card.win{{border:5px solid {t['accent']};box-shadow:0 18px 60px rgba(200,145,46,.28)}}
.badge{{position:absolute;top:-30px;right:44px;background:{t['accent']};color:#fff;font-size:28px;font-weight:800;
  padding:10px 26px;border-radius:999px}}
.chip{{display:inline-flex;align-items:center;gap:12px;background:{t['chip']};border-radius:999px;
  padding:12px 26px;font-size:30px;font-weight:600;margin-right:14px}}
.sw{{width:30px;height:30px;border-radius:50%;border:2px solid rgba(0,0,0,.12);display:inline-block}}
</style></head><body>
<div class="head"><span>{esc(header)}</span><span>{idx} / {total}</span></div>
{body}
<div class="foot">재미로 보는 운세예요 🙂</div>
</body></html>"""

def zodiac_card(z, accent):
    win = z["stars"] == 5
    badge = '<div class="badge">👑 오늘의 1등 띠</div>' if win else ""
    return f"""<div class="card{' win' if win else ''}">{badge}
  <div style="display:flex;align-items:center;gap:36px">
    <div class="e" style="font-size:120px;line-height:1">{z['emoji']}</div>
    <div>
      <div style="font-size:60px;font-weight:800">{esc(z['name'])}</div>
      <div style="font-size:48px;letter-spacing:.08em;margin-top:4px">{stars(z['stars'], accent)}</div>
    </div>
  </div>
  <div style="font-size:42px;font-weight:600;line-height:1.45;margin:30px 0 30px">{esc(z['text'])}</div>
  <div><span class="chip"><span class="sw" style="background:{z['hex']}"></span>행운의 색 · {esc(z['color'])}</span>
       <span class="chip">행운의 숫자 · {z['num']}</span></div>
</div>"""

def mbti_row(m, accent):
    win = m["stars"] == 5
    badge = '<div class="badge" style="top:-24px;font-size:24px">👑 오늘의 1등 MBTI</div>' if win else ""
    return f"""<div class="card{' win' if win else ''}" style="padding:26px 40px 30px;border-radius:34px">{badge}
  <div style="display:flex;align-items:center;justify-content:space-between">
    <div style="display:flex;align-items:center;gap:20px">
      <div style="font-size:48px;font-weight:900;letter-spacing:.04em">{m['type']}</div>
      <span class="chip" style="font-size:25px;padding:6px 20px;margin:0">🍀 {esc(m['lucky'])}</span>
    </div>
    <div style="font-size:36px;letter-spacing:.06em">{stars(m['stars'], accent)}</div>
  </div>
  <div style="font-size:33px;font-weight:600;line-height:1.4;margin-top:12px">{esc(m['text'])}</div>
</div>"""

def center(lines):
    return f'<div class="wrap" style="align-items:center;text-align:center;gap:34px">{lines}</div>'

def build(d):
    pages = []
    tz, tm = THEMES["zodiac"], THEMES["mbti"]
    zs = d["zodiac"]
    win = next(z for z in zs if z["stars"] == 5)
    # 띠별 1: cover
    emojis = "".join(z["emoji"] for z in zs)
    pages.append(("zodiac", center(f"""
      <div style="font-size:34px;font-weight:700;color:{tz['accent']};letter-spacing:.2em">DAILY FORTUNE</div>
      <div style="font-size:112px;font-weight:900;line-height:1.15">오늘의<br>띠별 운세</div>
      <div style="font-size:42px;font-weight:600">{esc(d['date_label'])}</div>
      <div style="font-size:36px;color:{tz['sub']}">{esc(d['season_line'])}</div>
      <div class="e" style="font-size:62px;letter-spacing:6px;margin-top:20px;line-height:1.4">{emojis[:12]}<br>{emojis[12:]}</div>
      <div style="font-size:36px;font-weight:700;background:{tz['ink']};color:#fff;padding:20px 44px;border-radius:999px;margin-top:10px">
        👑 1등은 {esc(win['name'])} · 넘겨서 확인 👉</div>"""), "띠별 운세"))
    for i in range(0, 12, 2):
        body = '<div class="wrap">' + zodiac_card(zs[i], tz["accent"]) + zodiac_card(zs[i+1], tz["accent"]) + "</div>"
        pages.append(("zodiac", body, "띠별 운세"))
    pages.append(("zodiac", center(f"""
      <div class="e" style="font-size:150px">💬</div>
      <div style="font-size:72px;font-weight:900;line-height:1.3">댓글에<br>내 띠를 남겨주세요</div>
      <div style="font-size:44px;font-weight:600;color:{tz['sub']}">한 줄 운세를 답글로 보내드려요!</div>
      <div style="font-size:34px;margin-top:20px;color:{tz['sub']}">예) 말띠 · 쥐띠 · 돼지띠</div>"""), "띠별 운세"))

    groups = d["mbti_groups"]
    mwin = next(t for g in groups for t in g["types"] if t["stars"] == 5)
    m_pages = [("mbti", center(f"""
      <div style="font-size:34px;font-weight:700;color:{tm['accent']};letter-spacing:.2em">DAILY FORTUNE</div>
      <div style="font-size:112px;font-weight:900;line-height:1.15">오늘의<br>MBTI 운세</div>
      <div style="font-size:42px;font-weight:600">{esc(d['date_label'])}</div>
      <div style="font-size:36px;color:{tm['sub']}">{esc(d['season_line'])}</div>
      <div style="font-size:40px;font-weight:800;letter-spacing:.1em;margin-top:16px;color:{tm['accent']}">NT · NF · SJ · SP</div>
      <div style="font-size:36px;font-weight:700;background:{tm['ink']};color:#fff;padding:20px 44px;border-radius:999px;margin-top:10px">
        👑 1등은 {mwin['type']} · 넘겨서 확인 👉</div>"""), "MBTI 운세")]
    for g in groups:
        rows = "".join(mbti_row(t, tm["accent"]) for t in g["types"])
        title = (f'<div style="font-size:50px;font-weight:900;margin-bottom:6px">{g["code"]} '
                 f'<span style="color:{tm["accent"]}">{esc(g["label"])}</span></div>')
        m_pages.append(("mbti", f'<div class="wrap" style="gap:26px">{title}{rows}</div>', "MBTI 운세"))
    m_pages.append(("mbti", center(f"""
      <div class="e" style="font-size:150px">📌</div>
      <div style="font-size:72px;font-weight:900;line-height:1.3">저장해두고<br>오늘 하루 틈틈이</div>
      <div style="font-size:44px;font-weight:600;color:{tm['sub']}">같은 MBTI 친구에게 공유해요 👥</div>"""), "MBTI 운세"))

    out = []
    for n, (th, body, head) in enumerate(pages, 1):
        out.append((f"ddi_{n:02d}.png", page(th, body, n, len(pages), f"{d['date_short']} · {head}")))
    for n, (th, body, head) in enumerate(m_pages, 1):
        out.append((f"mbti_{n:02d}.png", page(th, body, n, len(m_pages), f"{d['date_short']} · {head}")))
    return out

def find_browser(given):
    cands = [given] if given else []
    cands += [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
              shutil.which("chromium") or "", shutil.which("google-chrome") or "", shutil.which("chromium-browser") or ""]
    for c in cands:
        if c and os.path.exists(c):
            return c
    sys.exit("no Chrome/Edge/Chromium found")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data"); ap.add_argument("out"); ap.add_argument("--browser")
    a = ap.parse_args()
    d = json.load(open(a.data, encoding="utf-8"))
    out = Path(a.out).resolve(); (out / "html").mkdir(parents=True, exist_ok=True)
    br = find_browser(a.browser)
    for name, doc in build(d):
        hp = out / "html" / name.replace(".png", ".html")
        hp.write_text(doc, encoding="utf-8")
        subprocess.run([br, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                        "--force-device-scale-factor=1", f"--window-size={W},{H}",
                        "--virtual-time-budget=3000", f"--screenshot={out / name}", hp.resolve().as_uri()],
                       check=True, capture_output=True, timeout=60)
        print("ok", name)

if __name__ == "__main__":
    main()
