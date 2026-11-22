"""일진(그날의 간지)과 띠 관계 계산 — 찰떡궁합 사이트(ssong032/gunghap)의 js/saju.js, js/data.js와 같은 공식.

카드뉴스의 띠 순위와 찰떡 궁합이 사이트 결과와 어긋나지 않게 하려고 쓴다.

  python3 tool/iljin.py 2026-11-23              # 그날 일진, 띠별 등급, 쓸 수 있는 궁합 쌍
  python3 tool/iljin.py --check tool/data_D.json  # 작성한 데이터가 규칙에 맞는지 검사 (틀리면 exit 1)

일진 기준: 1900-01-01 = 갑술(60갑자 인덱스 10). 실제 기사 일진(2022-07-05 기미, 2022-08-22 정미,
2026-11-19 정유, 2026-11-20 무술)으로 검증함.
"""
import datetime as dt
import json
import sys

STEMS = "갑을병정무기경신임계"
STEMS_HJ = "甲乙丙丁戊己庚辛壬癸"
BRANCHES = "자축인묘진사오미신유술해"
BRANCHES_HJ = "子丑寅卯辰巳午未申酉戌亥"
ELEMENT_ADJ = ["푸른", "붉은", "노란", "하얀", "검은"]
TTI = ["쥐", "소", "범", "토끼", "용", "뱀", "말", "양", "원숭이", "닭", "개", "돼지"]
WONJIN = [{0, 7}, {1, 6}, {2, 9}, {3, 8}, {4, 11}, {5, 10}]

# 띠 궁합 점수 (사이트 js/data.js의 TTI_RELATIONS와 같음)
REL_SCORE = {"yukhap": 96, "samhap": 92, "same": 80, "chung": 62, "wonjin": 58}
REL_KO = {"yukhap": "육합", "samhap": "삼합", "same": "같은 지지", "chung": "충", "wonjin": "원진", "normal": "평"}


def ganzhi(day):
    i = (10 + (day - dt.date(1900, 1, 1)).days) % 60
    return {"index": i, "stem": i % 10, "branch": i % 12,
            "ko": STEMS[i % 10] + BRANCHES[i % 12], "hj": STEMS_HJ[i % 10] + BRANCHES_HJ[i % 12]}


def label(day):
    g = ganzhi(day)
    return f"{g['ko']}({g['hj']})일 · {ELEMENT_ADJ[g['stem'] // 2]} {TTI[g['branch']]}의 날"


def relation(a, b):
    if a == b:
        return "same"
    if (a + b) % 12 == 1:
        return "yukhap"
    if a % 4 == b % 4:
        return "samhap"
    if abs(a - b) == 6:
        return "chung"
    if {a, b} in WONJIN:
        return "wonjin"
    return "normal"


def tti_score(a, b):
    r = relation(a, b)
    return REL_SCORE.get(r, 68 + ((7 * (a + b) + a * b) % 11))


def mbti_score(a, b):
    """사이트 js/data.js mbtiResult와 같음: 기본 50 + E/I(같5·다10) + S/N(같20·다0) + T/F(같6·다8) + J/P(같4·다10)."""
    s = 50
    for pos, same, diff in ((0, 5, 10), (1, 20, 0), (2, 6, 8), (3, 4, 10)):
        s += same if a[pos] == b[pos] else diff
    return s


def tier(rel):
    return {"yukhap": "A", "samhap": "A", "same": "B", "normal": "C", "chung": "D", "wonjin": "D"}[rel]


def tti_index(name):
    n = name.replace("띠", "").strip()
    n = "범" if n == "호랑이" else n
    return TTI.index(n)


def guide(day):
    g = ganzhi(day)
    b = g["branch"]
    rows = [(TTI[i], relation(i, b)) for i in range(12)]
    out = [f"D = {day} · {label(day)}", "",
           "띠별 등급 (오늘 지지와의 관계):"]
    for name, r in rows:
        t = tier(r)
        hint = {"A": "상위권 ★4~5 (1등은 이 중에서, 육합 우선)", "B": "상위~중간 ★3~4",
                "C": "중간 ★2~4 (자유)", "D": "하위권 ★2~3, 부드러운 조언 톤, TOP3 금지"}[t]
        out.append(f"  {name}띠: {REL_KO[r]} → {t} {hint}")
    pairs = sorted(((tti_score(i, j), TTI[i], TTI[j], REL_KO[relation(i, j)])
                    for i in range(12) for j in range(i + 1, 12) if tti_score(i, j) >= 92), reverse=True)
    out += ["", "찰떡 궁합(ddi_chem)에 쓸 수 있는 쌍 = 사이트 92점 이상(육합 96, 삼합 92). 점수 높은 순으로 배치:",
            "  " + ", ".join(f"{a}띠×{c}띠({s} {k})" for s, a, c, k in pairs),
            "  오늘 상위권(A) 띠가 들어간 쌍을 우선 고르세요.",
            "", "MBTI 케미(mbti_chem)는 사이트 MBTI 궁합 90점 이상인 쌍만, 점수 높은 순으로.",
            "  예: S/N이 같고 E/I가 다르면 항상 90점 이상. 검사는 --check 로."]
    return "\n".join(out)


def check(path):
    d = json.load(open(path, encoding="utf-8"))
    day = dt.date.fromisoformat(path.rsplit("data_", 1)[1][:10])
    b = ganzhi(day)["branch"]
    errs = []
    zs = d["zodiac"]
    fives = [z["name"] for z in zs if z["stars"] == 5]
    if len(fives) != 1:
        errs.append(f"5★ 띠는 정확히 1개여야 해요: {fives}")
    # render.py ranks()와 같은 순위: 모든 항목에 rank가 있으면 그것, 없으면 별점 높은 순(같으면 띠 순서)
    if all("rank" in z for z in zs):
        top3 = {i for i, z in enumerate(zs) if z["rank"] <= 3}
    else:
        top3 = set(sorted(range(12), key=lambda i: (-zs[i]["stars"], i))[:3])
    for i, z in enumerate(zs):
        r = relation(tti_index(z["name"]), b)
        t = tier(r)
        if z["stars"] == 5 and t != "A":
            errs.append(f"1등 {z['name']}는 오늘과 {REL_KO[r]} 관계예요. 1등은 육합·삼합 띠 중에서 골라야 해요.")
        if t == "A" and z["stars"] < 4:
            errs.append(f"{z['name']}는 오늘과 {REL_KO[r]}이라 ★4 이상이어야 해요 (지금 ★{z['stars']}).")
        if t == "D" and (z["stars"] > 3 or i in top3):
            errs.append(f"{z['name']}는 오늘과 {REL_KO[r]}이라 ★3 이하, TOP3 밖이어야 해요 (지금 ★{z['stars']}).")
    for key, scorer, need, fmt in (("ddi_chem", lambda a, c: tti_score(tti_index(a), tti_index(c)), 92, "띠"),
                                   ("mbti_chem", lambda a, c: mbti_score(a.upper(), c.upper()), 90, "MBTI")):
        pairs = d.get(key) or []
        scores = []
        for p in pairs[:3]:
            s = scorer(p["a"], p["b"])
            scores.append(s)
            if s < need:
                errs.append(f"{key}: {p['a']}×{p['b']}는 사이트 {fmt} 궁합 {s}점이에요. {need}점 이상인 쌍만 써야 해요.")
        if scores != sorted(scores, reverse=True):
            errs.append(f"{key}: 사이트 점수 높은 순으로 놓아 주세요 (지금 {scores}).")
    hook = d.get("hook")
    if hook is not None:
        if not isinstance(hook, dict):
            errs.append("hook 은 {\"ddi\": \"…\", \"mbti\": \"…\"} 형식이어야 해요.")
        else:
            for k in ("ddi", "mbti"):
                v = hook.get(k)
                if v is None:
                    continue
                if not isinstance(v, str):
                    errs.append(f"hook.{k} 는 문자열이어야 해요.")
                    continue
                if len(v.strip()) > 20:
                    errs.append(f"hook.{k} 가 {len(v.strip())}자예요. 20자 이내로 줄여 주세요.")
                if any(len(w) > 12 for w in v.split()):
                    errs.append(f"hook.{k} 에 띄어쓰기 없이 12자가 넘는 덩어리가 있어요. 화면에서 잘릴 수 있으니 띄어 써 주세요.")
    if errs:
        print("FAIL " + path)
        print("\n".join("- " + e for e in errs))
        return 1
    print(f"OK {path} · {label(day)}")
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--check":
        sys.exit(check(sys.argv[2]))
    if len(sys.argv) == 2:
        print(guide(dt.date.fromisoformat(sys.argv[1])))
        sys.exit(0)
    sys.exit(__doc__)
