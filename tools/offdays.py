"""offdays.py — 내일부터 이어지는 '쉬는 날'(토·일·공휴일) 목록을 출력한다.

사용: python tools/offdays.py [기준일 YYYY-MM-DD, 기본 오늘 KST] [추가 공휴일 YYYY-MM-DD ...]
  추가 공휴일: 캘린더에서 확인한 임시공휴일 등 (state/holidays_kr.json 에 없는 날).
출력: 한 줄에 하나씩 'YYYY-MM-DD 요일 사유'. 내일이 평일이면 아무것도 출력하지 않는다.
"""
import json, sys
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent.parent
WD = "월화수목금토일"


def main():
    base = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else datetime.now(ZoneInfo("Asia/Seoul")).date()
    hol = json.loads((ROOT / "state" / "holidays_kr.json").read_text(encoding="utf-8"))["dates"]
    hol.update({d: "추가 공휴일" for d in sys.argv[2:]})
    d = base + timedelta(days=1)
    while True:
        k = d.isoformat()
        why = hol.get(k) or ("주말" if d.weekday() >= 5 else None)
        if not why:
            break
        print(k, WD[d.weekday()], why)
        d += timedelta(days=1)


if __name__ == "__main__":
    main()
