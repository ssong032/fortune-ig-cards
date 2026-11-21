"""Track Metricool scheduled posts per month against the plan limit.

usage:
  python3 tool/quota.py check  YYYY-MM-DD [N]   # can N posts (default 2) be scheduled for that date?
  python3 tool/quota.py record YYYY-MM-DD [N]   # log N scheduled posts for that date, then print any warning

Counts by publication month, using tool/post_log.json (one entry per scheduled post day).
LIMIT is the free-plan cap (20/month as of 2026-11). Set "limit" in post_log.json to change it,
e.g. to 0 for unlimited after upgrading.
Output lines that start with "WARN:" or "BLOCK:" are meant to be sent to the user as a push notification.
"""
import json, sys, datetime as dt
from pathlib import Path

LOG = Path(__file__).resolve().parent / "post_log.json"
PER_DAY = 2

def load():
    return json.loads(LOG.read_text(encoding="utf-8")) if LOG.exists() else {"limit": 20, "posts": []}

def used(log, month):
    return sum(p["n"] for p in log["posts"] if p["date"].startswith(month))

def md(d):
    return f"{d.month}/{d.day}"

def main():
    cmd, day = sys.argv[1], dt.date.fromisoformat(sys.argv[2])
    n = int(sys.argv[3]) if len(sys.argv) > 3 else PER_DAY
    log = load()
    limit = log.get("limit", 20)
    month = day.strftime("%Y-%m")
    if cmd == "check":
        if any(p["date"] == day.isoformat() for p in log["posts"]):
            print(f"OK: {md(day)} already recorded")
            return
        u = used(log, month)
        if limit and u + n > limit:
            print(f"BLOCK: ⛔ Metricool 무료 한도 초과로 {md(day)} 운세를 예약하지 못했어요 "
                  f"(이번 달 {u}/{limit}개 사용). 유료로 전환하면 다시 자동 게시돼요.")
            sys.exit(3)
        print(f"OK: {month} {u}+{n}/{limit or '∞'}")
    elif cmd == "record":
        if not any(p["date"] == day.isoformat() for p in log["posts"]):
            log["posts"].append({"date": day.isoformat(), "n": n})
            log["posts"].sort(key=lambda p: p["date"])
            LOG.write_text(json.dumps(log, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        if not limit:
            return
        nxt, nxt2 = day + dt.timedelta(days=1), day + dt.timedelta(days=2)
        u1 = used(log, nxt.strftime("%Y-%m"))
        if u1 + PER_DAY > limit:
            print(f"WARN: ⚠️ 내일 밤부터 Metricool 무료 한도(월 {limit}개)를 넘어서 {md(nxt)} 운세가 예약되지 않아요. "
                  f"계속 올리려면 유료 전환이 필요해요.")
        elif nxt2.month == nxt.month and u1 + 2 * PER_DAY > limit:
            print(f"WARN: ⚠️ Metricool 무료 한도 예고: 내일 밤 예약하는 {md(nxt)} 운세가 이번 달 마지막이에요 "
                  f"(월 {limit}개). {md(nxt2)}부터는 유료로 전환해야 계속 올라가요.")
    else:
        sys.exit("unknown command")

if __name__ == "__main__":
    main()
