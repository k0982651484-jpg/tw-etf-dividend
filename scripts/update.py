"""每日增量更新(GitHub Actions 每天跑,也可手動一鍵觸發)
1. 重抓ETF清單 -> 新上市的ETF自動補齊5年歷史
2. 證交所+櫃買「全市場當日收盤」各1次請求 -> 所有ETF補今天股價(不吃FinMind額度)
3. 有缺漏天數 / 新分割的ETF -> 用FinMind補
4. 配息:優先更新「快除息、剛除息、有預告」的ETF,其餘輪流更新
5. 持股/規模:每天輪流更新最舊的一批(約一週全部輪完)
6. 重建 summary.json
FinMind 免token每小時300次;設環境變數 FINMIND_TOKEN 可提高到600次。
"""
import json, os, sys, subprocess, datetime as dt, urllib.request
HERE = os.path.dirname(os.path.abspath(__file__)); sys.path.insert(0, HERE)
os.environ.setdefault("FINMIND_NO_WAIT", "1")      # 雲端不要睡等額度,用完就收工,下次再補
import fetch_history as fh

DATA = fh.DATA
TODAY = dt.date.today()
BUDGET = int(os.environ.get("FINMIND_BUDGET", "500" if fh.TOKEN else "250"))   # 本次最多打幾次 FinMind
used = 0
UA = {"User-Agent": "Mozilla/5.0"}

def spend(n=1):
    global used; used += n
    return used <= BUDGET

def load(p, default=None):
    try: return json.load(open(p))
    except Exception: return default

def roc(d):  # 1151104 -> 2026-11-04
    return f"{int(d[:3]) + 1911}-{d[3:5]}-{d[5:7]}"

def num(s):
    try: return float(str(s).replace(",", "").strip())
    except ValueError: return None

def bulk_quotes():
    """上市+上櫃當日收盤(全市場一次抓)"""
    q = {}
    try:
        tw = json.load(urllib.request.urlopen(urllib.request.Request("https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL", headers=UA), timeout=90))
        for x in tw:
            c = num(x["ClosingPrice"])
            if c: q[x["Code"]] = [roc(x["Date"]), num(x["OpeningPrice"]), num(x["HighestPrice"]), num(x["LowestPrice"]), c, round((num(x["TradeVolume"]) or 0) / 1000)]
    except Exception as e: print("證交所當日行情失敗:", e)
    try:
        tp = json.load(urllib.request.urlopen(urllib.request.Request("https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes", headers=UA), timeout=120))
        for x in tp:
            c = num(x["Close"])
            if c: q[x["SecuritiesCompanyCode"]] = [roc(x["Date"]), num(x["Open"]), num(x["High"]), num(x["Low"]), c, round((num(x["TradingShares"]) or 0) / 1000)]
    except Exception as e: print("櫃買當日行情失敗:", e)
    print("當日行情", len(q), "檔")
    return q

def main():
    global used
    # 1. ETF 清單(新上市)
    old_ids = {e["id"] for e in load(os.path.join(DATA, "etf_master.json"), [])}
    r = subprocess.run([sys.executable, os.path.join(HERE, "build_master.py")], stdout=subprocess.DEVNULL); spend()
    if r.returncode: print("ETF清單更新失敗,沿用舊清單")
    master = load(os.path.join(DATA, "etf_master.json"))
    new_ids = [e["id"] for e in master if e["id"] not in old_ids]
    print("新上市ETF:", new_ids or "無")

    # 2. 分割 + 大盤
    old_splits = load(os.path.join(DATA, "splits.json"), {})
    try: fh.load_splits(); spend()
    except Exception as ex: print("分割資料失敗:", ex); fh.SPLITS.update({k: [tuple(x) for x in v] for k, v in old_splits.items()})
    new_split = [k for k in fh.SPLITS if fh.SPLITS[k] != [tuple(x) for x in old_splits.get(k, [])] and k in {e["id"] for e in master}]
    try: fh.save(os.path.join(DATA, "taiex.json"), fh.fetch_prices("TAIEX")); spend()
    except Exception as ex: print("大盤更新失敗:", ex)
    tx_dates = [r[0] for r in load(os.path.join(DATA, "taiex.json"))]
    last_trade = tx_dates[-1]; prev_trade = tx_dates[-2]

    # 3. 股價:當日行情直接接上;有缺漏/新上市/新分割 -> FinMind 重抓
    q = bulk_quotes()
    need_full = set(new_ids) | set(new_split)
    appended = 0
    for e in master:
        sid = e["id"]; pp = os.path.join(DATA, "prices", sid + ".json")
        rows = load(pp)
        if rows is None: need_full.add(sid); continue
        if sid in need_full: continue
        last = rows[-1][0] if rows else ""
        bar = q.get(sid)
        if bar and bar[0] > last:
            if last and last < prev_trade and bar[0] == last_trade:
                need_full.add(sid); continue        # 中間漏了交易日 -> 用FinMind整段重抓比較保險
            rows.append(bar); fh.save(pp, rows); appended += 1
    print(f"當日股價接上 {appended} 檔;需重抓 {len(need_full)} 檔")
    for sid in sorted(need_full):
        if not spend(2): print("FinMind 本次預算用完,其餘下次再補"); break
        try:
            fh.save(os.path.join(DATA, "prices", sid + ".json"), fh.fetch_prices(sid))
            fh.save(os.path.join(DATA, "dividends", sid + ".json"), fh.fetch_divs(sid))
        except fh.QuotaError: print("FinMind 額度用完,其餘下次再補"); used = BUDGET; break

    # 4. 配息:依急迫程度排序後,用剩下的額度更新
    summ = {e["id"]: e for e in (load(os.path.join(DATA, "summary.json"), {}) or {}).get("etfs", [])}
    upcoming = {u["id"] for u in load(os.path.join(DATA, "upcoming.json"), []) or []}
    def urgency(e):
        sid = e["id"]; s = summ.get(sid, {}); dp = os.path.join(DATA, "dividends", sid + ".json")
        age = (TODAY - dt.date.fromtimestamp(os.path.getmtime(dp))).days if os.path.exists(dp) else 999
        last_ex = (s.get("lastDiv") or {}).get("ex", "")
        recent = last_ex and (TODAY - dt.date.fromisoformat(last_ex)).days < 45          # 剛除息:等發放日/金額確認
        soon = TODAY.month in (s.get("exMonths") or []) or (TODAY.month % 12 + 1) in (s.get("exMonths") or [])
        return (0 if sid in upcoming else 1 if recent else 2 if soon else 3, -age)
    queue = sorted([e for e in master if e["id"] not in need_full and summ.get(e["id"], {}).get("perYear", 1)], key=urgency)
    n = 0
    for e in queue:
        if urgency(e)[1] == 0: continue        # 今天已更新
        if not spend(): break
        try: fh.save(os.path.join(DATA, "dividends", e["id"] + ".json"), fh.fetch_divs(e["id"])); n += 1
        except fh.QuotaError: print("FinMind 額度用完"); break
    print("配息更新", n, "檔")

    # 5. 持股/規模輪流更新
    subprocess.run([sys.executable, os.path.join(HERE, "fetch_holdings.py"), "--oldest", os.environ.get("HOLDINGS_PER_RUN", "70")] + (["--ids", ",".join(new_ids)] if new_ids else []))

    # 6. 總表
    subprocess.run([sys.executable, os.path.join(HERE, "build_summary.py")], check=True)
    print(f"完成。FinMind 用了 {used}/{BUDGET} 次")

if __name__ == "__main__":
    main()
