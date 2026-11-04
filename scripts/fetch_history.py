"""步驟2: 抓每檔ETF近60個月日K + 配息歷史 + 大盤(TAIEX)
- 可中斷續跑:已抓過且今天更新過的檔案會跳過
- FinMind 免 token 300次/時,碰到上限自動睡到額度恢復
- 有 token 時設環境變數 FINMIND_TOKEN 即可加速
用法: python3 scripts/fetch_history.py [--only 0050,00878]
"""
import json, os, sys, time, datetime as dt, urllib.request, urllib.parse
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
TOKEN = os.environ.get("FINMIND_TOKEN", "")
TODAY = dt.date.today()
START = (TODAY.replace(day=1) - dt.timedelta(days=365 * 5 + 31)).isoformat()   # 60個月前的月初再往前一點

class QuotaError(Exception):
    pass

def finmind(dataset, data_id, start):
    q = dict(dataset=dataset, data_id=data_id, start_date=start)
    url = "https://api.finmindtrade.com/api/v4/data?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {TOKEN}"} if TOKEN else {})
    for attempt in range(30):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                d = json.load(r)
        except urllib.error.HTTPError as e:
            d = {"status": e.code, "msg": e.read().decode(errors="ignore")[:200]}
        except Exception as e:
            print("  網路錯誤,10秒後重試:", e); time.sleep(10); continue
        if d.get("status") == 200:
            return d["data"]
        if d.get("status") == 402 or "upper limit" in str(d.get("msg", "")):
            if os.environ.get("FINMIND_NO_WAIT"): raise QuotaError("FinMind 每小時額度用完")
            print(f"  [{dt.datetime.now():%H:%M}] 達每小時上限,睡10分鐘…", flush=True); time.sleep(600); continue
        print("  API錯誤:", d); time.sleep(5)
    raise RuntimeError("重試太多次")

def fresh(path):
    return os.path.exists(path) and dt.date.fromtimestamp(os.path.getmtime(path)) == TODAY

def save(path, obj):
    tmp = path + ".tmp"
    json.dump(obj, open(tmp, "w"), ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)

SPLITS = {}   # sid -> [(日期, 比例)]  分割/反分割還原用

def load_splits():
    rows = finmind("TaiwanStockSplitPrice", "", "2015-01-01")
    for r in rows:
        if r["before_price"] and r["after_price"]:
            SPLITS.setdefault(r["stock_id"], []).append((r["date"], r["after_price"] / r["before_price"]))
    save(os.path.join(DATA, "splits.json"), SPLITS)

def fetch_prices(sid):
    rows = finmind("TaiwanStockPrice", sid, START)
    out = []
    for r in rows:
        f = 1.0   # 分割前的價格乘上比例,讓走勢圖連續(還原分割,不還原配息)
        for d, ratio in SPLITS.get(sid, []):
            if r["date"] < d: f *= ratio
        # 精簡格式: [日期, 開, 高, 低, 收, 成交張數]
        out.append([r["date"], round(r["open"] * f, 3), round(r["max"] * f, 3), round(r["min"] * f, 3),
                    round(r["close"] * f, 3), round(r["Trading_Volume"] / 1000 / f)])
    return out

def fetch_divs(sid):
    rows = finmind("TaiwanStockDividend", sid, "2015-01-01")   # 配息抓長一點,算殖利率/頻率用
    out = []
    for r in rows:
        cash = (r.get("CashEarningsDistribution") or 0) + (r.get("CashStatutorySurplus") or 0)
        if cash <= 0 or not r.get("CashExDividendTradingDate"): continue
        out.append(dict(ex=r["CashExDividendTradingDate"], pay=r.get("CashDividendPaymentDate") or "",
                        cash=round(cash, 5), ann=r.get("date", "")))
    out.sort(key=lambda x: x["ex"])
    return out

def main():
    master = json.load(open(os.path.join(DATA, "etf_master.json")))
    ids = [e["id"] for e in master]
    if "--only" in sys.argv: ids = sys.argv[sys.argv.index("--only") + 1].split(",")
    load_splits(); print("分割資料", len(SPLITS), "檔")
    # 大盤先抓
    tp = os.path.join(DATA, "taiex.json")
    if not fresh(tp): save(tp, fetch_prices("TAIEX")); print("TAIEX ok")
    for n, sid in enumerate(ids, 1):
        pp, dp = os.path.join(DATA, "prices", f"{sid}.json"), os.path.join(DATA, "dividends", f"{sid}.json")
        msg = []
        if not fresh(dp): d = fetch_divs(sid); save(dp, d); msg.append(f"配息{len(d)}筆")
        if not fresh(pp): p = fetch_prices(sid); save(pp, p); msg.append(f"日K{len(p)}筆")
        print(f"[{n}/{len(ids)}] {sid} {' '.join(msg) or '已是最新'}", flush=True)
    print("全部完成")

if __name__ == "__main__":
    main()
