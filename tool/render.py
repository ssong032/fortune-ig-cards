"""Render the daily fortune carousels (띠별 8장 + MBTI 6장) to 1080x1350 PNGs.

usage: python render.py data.json OUT_DIR [--browser PATH]
"""
import argparse, json, os, shutil, subprocess, sys, html
from pathlib import Path

W, H = 1080, 1350
# Bundled fonts (OFL) so Windows and the Linux cloud runner render identically.
FONTS_DIR = Path(__file__).resolve().parent / "fonts"
FONT_FACES = (
    f"@font-face{{font-family:'FKR';src:url('{(FONTS_DIR / 'NotoSansKR-VF.ttf').as_uri()}');font-weight:100 900}}"
    f"@font-face{{font-family:'FEmoji';src:url('{(FONTS_DIR / 'NotoColorEmoji.ttf').as_uri()}')}}"
)
FONT = "'FKR','Noto Sans KR','Malgun Gothic',sans-serif,'FEmoji'"
EMOJI = "'FEmoji','Noto Color Emoji','Segoe UI Emoji'"

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
{FONT_FACES}
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

ZODIAC_EMOJI = {"쥐": "🐭", "소": "🐮", "범": "🐯", "호랑이": "🐯", "토끼": "🐰", "용": "🐲", "뱀": "🐍",
                "말": "🐴", "양": "🐑", "원숭이": "🐵", "닭": "🐔", "개": "🐶", "돼지": "🐷"}

def ranks(items):
    """Rank 1..N. Uses explicit 'rank' if every item has one, else stars desc, ties in list order."""
    if all("rank" in it for it in items):
        return [it["rank"] for it in items]
    order = sorted(range(len(items)), key=lambda i: (-items[i]["stars"], i))
    r = [0] * len(items)
    for pos, i in enumerate(order, 1):
        r[i] = pos
    return r

def rank_pill(n, accent, size=30):
    medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(n, "")
    style = (f"background:{accent};color:#fff" if n <= 3 else "background:rgba(0,0,0,.06);color:inherit")
    return (f'<span style="{style};font-size:{size}px;font-weight:800;padding:6px 18px;border-radius:999px;'
            f'white-space:nowrap">{medal}{n}위</span>')

def zodiac_card(z, accent, rank):
    win = z["stars"] == 5
    badge = '<div class="badge">👑 오늘의 1등 띠</div>' if win else ""
    return f"""<div class="card{' win' if win else ''}">{badge}
  <div style="display:flex;align-items:center;gap:36px">
    <div class="e" style="font-size:120px;line-height:1">{z['emoji']}</div>
    <div style="flex:1">
      <div style="display:flex;align-items:center;justify-content:space-between">
        <div style="font-size:60px;font-weight:800">{esc(z['name'])}</div>{'' if win else rank_pill(rank, accent)}
      </div>
      <div style="font-size:48px;letter-spacing:.08em;margin-top:4px">{stars(z['stars'], accent)}</div>
    </div>
  </div>
  <div style="font-size:42px;font-weight:600;line-height:1.45;margin:30px 0 30px">{esc(z['text'])}</div>
  <div><span class="chip"><span class="sw" style="background:{z['hex']}"></span>행운의 색 · {esc(z['color'])}</span>
       <span class="chip">행운의 숫자 · {z['num']}</span></div>
</div>"""

def mbti_row(m, accent, rank):
    win = m["stars"] == 5
    badge = '<div class="badge" style="top:-24px;font-size:24px">👑 오늘의 1등 MBTI</div>' if win else ""
    return f"""<div class="card{' win' if win else ''}" style="padding:26px 40px 30px;border-radius:34px">{badge}
  <div style="display:flex;align-items:center;justify-content:space-between">
    <div style="display:flex;align-items:center;gap:18px">
      <div style="font-size:48px;font-weight:900;letter-spacing:.04em">{m['type']}</div>
      <span class="chip" style="font-size:25px;padding:6px 20px;margin:0">🍀 {esc(m['lucky'])}</span>
    </div>
    <div style="display:flex;align-items:center;gap:14px">{'' if win else rank_pill(rank, accent, 24)}
      <div style="font-size:34px;letter-spacing:.04em">{stars(m['stars'], accent)}</div></div>
  </div>
  <div style="font-size:33px;font-weight:600;line-height:1.4;margin-top:12px">{esc(m['text'])}</div>
</div>"""

def center(lines):
    return f'<div class="wrap" style="align-items:center;text-align:center;gap:34px">{lines}</div>'

def podium(names, t):
    """Cover preview of today's top 3: list of (label, emoji-or-'')."""
    items = "".join(
        f'<div style="display:flex;flex-direction:column;align-items:center;gap:6px;min-width:200px">'
        f'<div style="font-size:44px">{m}</div><div class="e" style="font-size:64px;line-height:1.1">{e}</div>'
        f'<div style="font-size:36px;font-weight:800">{esc(n)}</div></div>'
        for m, (n, e) in zip(("🥇", "🥈", "🥉"), names))
    return f'<div style="display:flex;gap:28px;justify-content:center;margin-top:8px">{items}</div>'

def chem_page(title, pairs, t):
    """'오늘의 찰떡 궁합' slide. pairs: [{"a","b","text"}] (띠 names or MBTI types)."""
    def lab(x):
        e = ZODIAC_EMOJI.get(x.replace("띠", ""), "")
        return f'<span class="e">{e}</span> {esc(x)}' if e else esc(x)
    cards = "".join(
        f'<div class="card" style="padding:36px 44px">'
        f'<div style="font-size:30px;font-weight:800;color:{t["accent"]}">{m} TOP {i}</div>'
        f'<div style="font-size:50px;font-weight:900;margin:8px 0 10px">{lab(p["a"])} <span style="color:{t["accent"]}">×</span> {lab(p["b"])}</div>'
        f'<div style="font-size:36px;font-weight:600;line-height:1.4">{esc(p["text"])}</div></div>'
        for i, (m, p) in enumerate(zip(("💞", "💕", "💗"), pairs), 1))
    head = f'<div style="font-size:58px;font-weight:900;text-align:center;margin-bottom:8px">{title}</div>'
    tail = (f'<div style="font-size:34px;font-weight:700;text-align:center;color:{t["sub"]}">'
            f'📩 궁합 좋은 친구에게 보내주세요</div>')
    return f'<div class="wrap" style="gap:30px">{head}{cards}{tail}</div>'

def outro(t, lines):
    return center(f"""
      <div class="e" style="font-size:130px">📩</div>
      <div style="font-size:70px;font-weight:900;line-height:1.3">{lines}</div>
      <div style="display:flex;flex-direction:column;gap:22px;margin-top:10px;font-size:40px;font-weight:700">
        <div style="background:{t['card']};padding:22px 40px;border-radius:999px">📩 친구에게 보내서 운세 비교하기</div>
        <div style="background:{t['card']};padding:22px 40px;border-radius:999px">📌 저장하고 하루 3번 꺼내보기</div>
        <div style="background:{t['ink']};color:#fff;padding:22px 40px;border-radius:999px">🔔 팔로우하면 매일 아침 6시 업데이트</div>
      </div>""")

def build(d):
    pages = []
    tz, tm = THEMES["zodiac"], THEMES["mbti"]
    zs = d["zodiac"]
    zr = ranks(zs)
    top3 = sorted(range(12), key=lambda i: zr[i])[:3]
    emojis = "".join(z["emoji"] for z in zs)
    pages.append(("zodiac", center(f"""
      <div style="font-size:34px;font-weight:700;color:{tz['accent']};letter-spacing:.2em">DAILY FORTUNE</div>
      <div style="font-size:104px;font-weight:900;line-height:1.12">오늘의<br>띠별 운세</div>
      <div style="font-size:42px;font-weight:600">{esc(d['date_label'])}</div>
      <div style="font-size:34px;color:{tz['sub']}">{esc(d['season_line'])}</div>
      {podium([(zs[i]['name'], zs[i]['emoji']) for i in top3], tz)}
      <div style="font-size:36px;font-weight:700;background:{tz['ink']};color:#fff;padding:20px 44px;border-radius:999px;margin-top:6px">
        내 띠는 몇 위? 넘겨서 확인 👉</div>"""), "띠별 운세"))
    for i in range(0, 12, 2):
        body = ('<div class="wrap">' + zodiac_card(zs[i], tz["accent"], zr[i])
                + zodiac_card(zs[i + 1], tz["accent"], zr[i + 1]) + "</div>")
        pages.append(("zodiac", body, "띠별 운세"))
    if d.get("ddi_chem"):
        pages.append(("zodiac", chem_page("오늘의 찰떡 궁합", d["ddi_chem"][:3], tz), "띠별 운세"))
    pages.append(("zodiac", outro(tz, "오늘 내 띠<br>몇 위였나요?"), "띠별 운세"))

    groups = d["mbti_groups"]
    flat = [t for g in groups for t in g["types"]]
    mr = ranks(flat)
    mrank = {t["type"]: r for t, r in zip(flat, mr)}
    mtop3 = sorted(flat, key=lambda t: mrank[t["type"]])[:3]
    m_pages = [("mbti", center(f"""
      <div style="font-size:34px;font-weight:700;color:{tm['accent']};letter-spacing:.2em">DAILY FORTUNE</div>
      <div style="font-size:104px;font-weight:900;line-height:1.12">오늘의<br>MBTI 운세</div>
      <div style="font-size:42px;font-weight:600">{esc(d['date_label'])}</div>
      <div style="font-size:34px;color:{tm['sub']}">{esc(d['season_line'])}</div>
      {podium([(t['type'], '') for t in mtop3], tm)}
      <div style="font-size:36px;font-weight:700;background:{tm['ink']};color:#fff;padding:20px 44px;border-radius:999px;margin-top:6px">
        내 MBTI는 몇 위? 넘겨서 확인 👉</div>"""), "MBTI 운세")]
    for g in groups:
        rows = "".join(mbti_row(t, tm["accent"], mrank[t["type"]]) for t in g["types"])
        title = (f'<div style="font-size:50px;font-weight:900;margin-bottom:6px">{g["code"]} '
                 f'<span style="color:{tm["accent"]}">{esc(g["label"])}</span></div>')
        m_pages.append(("mbti", f'<div class="wrap" style="gap:26px">{title}{rows}</div>', "MBTI 운세"))
    if d.get("mbti_chem"):
        m_pages.append(("mbti", chem_page("오늘의 MBTI 케미", d["mbti_chem"][:3], tm), "MBTI 운세"))
    m_pages.append(("mbti", outro(tm, "오늘 내 MBTI<br>몇 위였나요?"), "MBTI 운세"))

    out = []
    for n, (th, body, head) in enumerate(pages, 1):
        out.append((f"ddi_{n:02d}.png", page(th, body, n, len(pages), f"{d['date_short']} · {head}")))
    for n, (th, body, head) in enumerate(m_pages, 1):
        out.append((f"mbti_{n:02d}.png", page(th, body, n, len(m_pages), f"{d['date_short']} · {head}")))
    return out

def find_browser(given):
    cands = [given] if given else []
    cands += [r"C:\Program Files\Google\Chrome\Application\chrome.exe",
              r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"]
    cands += [shutil.which(n) or "" for n in ("chromium", "chromium-browser", "google-chrome", "google-chrome-stable")]
    # Playwright's downloaded Chromium (cloud runner)
    pw = Path.home() / ".cache" / "ms-playwright"
    cands += sorted((str(p) for p in pw.glob("chromium-*/chrome-linux*/chrome")), reverse=True)
    for c in cands:
        if c and os.path.exists(c):
            return c
    sys.exit("no Chrome/Edge/Chromium found")

def has_blank_patch(png):
    """Chrome sometimes captures before the page finishes painting, leaving pure-white
    tiles. Backgrounds are gradients and never pure white, so white along the bottom or
    right edge means a bad capture. Skipped if Pillow is not installed."""
    try:
        from PIL import Image
    except ImportError:
        return False
    im = Image.open(png).convert("RGB")
    w, h = im.size
    pts = [(x, y) for x in range(0, w, 8) for y in (h - 4, h - 40)] + [(w - 4, y) for y in range(0, h, 8)]
    return any(im.getpixel(p) == (255, 255, 255) for p in pts)

def find_ffmpeg():
    exe = shutil.which("ffmpeg")
    if exe:
        return exe
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        sys.exit("ffmpeg not found: install it or `python3 -m pip install imageio-ffmpeg`")

def make_reel(out, slides, bg, dest):
    """9:16 silent slideshow for Reels (Instagram adds licensed music on top).
    Each 1080x1350 card is scaled to 918x1148 and placed at y=230 so it stays inside the
    Reels safe zone (top 230px and bottom ~480px are covered by Instagram UI)."""
    ff = find_ffmpeg()
    durs = [2.6] + [2.0] * (len(slides) - 2) + [2.4]
    inputs, chains = [], []
    for i, (s, dur) in enumerate(zip(slides, durs)):
        inputs += ["-loop", "1", "-t", f"{dur}", "-i", str(out / s)]
        chains.append(f"[{i}:v]scale=918:1148,pad=1080:1920:81:230:color={bg},setsar=1,fps=30,format=yuv420p[v{i}]")
    # 0.3s crossfades between cards
    xf, last, t = [], "v0", durs[0]
    for i in range(1, len(slides)):
        t -= 0.3
        xf.append(f"[{last}][v{i}]xfade=transition=fade:duration=0.3:offset={t:.2f}[x{i}]")
        last, t = f"x{i}", t + durs[i]
    graph = ";".join(chains + xf)
    subprocess.run([ff, "-y", *inputs, "-filter_complex", graph, "-map", f"[{last}]", "-c:v", "libx264",
                    "-preset", "medium", "-crf", "20", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
                    "-r", "30", str(dest)], check=True, capture_output=True, timeout=300)
    print("ok", dest.name, f"{t:.1f}s")

def write_publish_files(out, d, names):
    """The Instagram API only accepts JPEG, so write a JPEG next to each PNG, plus
    manifest.json, which the Telegram/Instagram worker reads to preview and publish."""
    from PIL import Image  # required here: no JPEGs means nothing can be published
    jpgs = []
    for n in names:
        j = n.replace(".png", ".jpg")
        Image.open(out / n).convert("RGB").save(out / j, "JPEG", quality=92, optimize=True, progressive=False)
        jpgs.append(j)
    caps = d.get("captions", {})
    manifest = {
        "date": out.name,
        "ddi": [j for j in jpgs if j.startswith("ddi_")],
        "mbti": [j for j in jpgs if j.startswith("mbti_")],
        "captions": {"ddi": caps.get("ddi", ""), "mbti": caps.get("mbti", "")},
    }
    (out / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8")
    print("ok manifest.json", len(jpgs), "jpg")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("data"); ap.add_argument("out"); ap.add_argument("--browser")
    ap.add_argument("--reel", action="store_true", help="also build reel.mp4 (off by default)")
    ap.add_argument("--no-reel", action="store_true", help="kept for compatibility; reels are off by default")
    a = ap.parse_args()
    d = json.load(open(a.data, encoding="utf-8"))
    out = Path(a.out).resolve(); (out / "html").mkdir(parents=True, exist_ok=True)
    for old in [*out.glob("ddi_*.png"), *out.glob("mbti_*.png"), *out.glob("ddi_*.jpg"), *out.glob("mbti_*.jpg")]:
        old.unlink()  # slide count can change between runs
    br = find_browser(a.browser)
    pages = build(d)
    for name, doc in pages:
        hp = out / "html" / name.replace(".png", ".html")
        hp.write_text(doc, encoding="utf-8")
        args = [br, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                "--allow-file-access-from-files", "--force-device-scale-factor=1", f"--window-size={W},{H}",
                "--virtual-time-budget=5000", f"--screenshot={out / name}", hp.resolve().as_uri()]
        if os.name != "nt":
            args[1:1] = ["--no-sandbox", "--disable-dev-shm-usage"]
        for attempt in range(4):
            subprocess.run(args, check=True, capture_output=True, timeout=90)
            if (out / name).exists() and (out / name).stat().st_size > 20000 and not has_blank_patch(out / name):
                break
            print(f"retry {name} (attempt {attempt + 2})")
        else:
            sys.exit(f"render failed for {name}")
        print("ok", name)
    write_publish_files(out, d, [n for n, _ in pages])
    if a.reel and not a.no_reel:
        ddi = [n for n, _ in pages if n.startswith("ddi_")]
        make_reel(out, ddi, "0xF9E2D3", out / "reel.mp4")

if __name__ == "__main__":
    main()
