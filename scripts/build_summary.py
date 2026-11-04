"""步驟2b: 由 prices/ dividends/ 整理出網頁要用的總表 data/summary.json + 除息預告 data/upcoming.json"""
import json, os, re, sys, datetime as dt, urllib.request
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import ta
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
TODAY = dt.date.today()
load = lambda p: json.load(open(p))

def freq_of(divs):
    """看最近(最多6次)除息的間隔中位數判斷頻率,新上市只配過幾次也判得準"""
    if not divs: return "不配息", 0
    if len(divs) == 1: return "年配", 1          # 只配過一次,先當年配(步驟3會用Yahoo標示校正)
    ds = [dt.date.fromisoformat(d["ex"]) for d in divs[-7:]]
    gaps = sorted((b - a).days for a, b in zip(ds, ds[1:]))
    g = gaps[len(gaps) // 2]
    if g < 45:  return "月配", 12
    if g < 130: return "季配", 4
    if g < 250: return "半年配", 2
    return "年配", 1

def monthly(prices):
    """日K -> 月K(每月最後一筆收盤)"""
    m = {}
    for r in prices: m[r[0][:7]] = r[4]
    return [[k, v] for k, v in sorted(m.items())][-61:]

def year_yields(divs, prices):
    """每一年的: 該年配息合計 / 該年平均股價 -> 歷年殖利率(使用者可選參考哪一年)"""
    out = {}
    for y in sorted({d["ex"][:4] for d in divs}):
        px = [r[4] for r in prices if r[0][:4] == y]
        if not px: continue
        cash = sum(d["cash"] for d in divs if d["ex"][:4] == y)
        out[y] = dict(cash=round(cash, 4), avgPx=round(sum(px) / len(px), 2), yld=round(cash / (sum(px) / len(px)) * 100, 2))
    return out

def upcoming():
    """證交所除權除息預告表(上市)"""
    try:
        req = urllib.request.Request("https://www.twse.com.tw/rwd/zh/exRight/TWT48U?response=json", headers={"User-Agent": "Mozilla/5.0"})
        d = json.load(urllib.request.urlopen(req, timeout=30))
    except Exception as e:
        print("預告表失敗", e); return []
    out = []
    for r in d.get("data", []):
        y, mo, da = re.findall(r"\d+", r[0])[:3]
        cash = re.sub(r"<[^>]+>", "", r[7]).strip()
        try: cash = float(cash)
        except ValueError: cash = None   # 待公告
        out.append(dict(id=r[1], name=r[2], ex=f"{int(y)+1911}-{mo}-{da}", cash=cash))
    return out

def main():
    master = load(os.path.join(DATA, "etf_master.json"))
    rows, delisted = [], []
    txc = [r[4] for r in load(os.path.join(DATA, "taiex.json"))]
    sp = os.path.join(DATA, "splits.json"); splits = load(sp) if os.path.exists(sp) else {}
    for e in master:
        pp, dp = os.path.join(DATA, "prices", e["id"] + ".json"), os.path.join(DATA, "dividends", e["id"] + ".json")
        if not os.path.exists(pp): continue
        prices, divs = [r for r in load(pp) if r[4] > 0], load(dp) if os.path.exists(dp) else []
        for d in divs:   # 分割前的配息換算成現在每股(和還原後股價同基準)
            for sd, ratio in splits.get(e["id"], []):
                if d["ex"] < sd: d["cash"] = round(d["cash"] * ratio, 5)
        if divs: json.dump(divs, open(os.path.join(DATA, "dividends", e["id"] + ".adj.json"), "w"), separators=(",", ":")) if e["id"] in splits else None
        if not prices: continue
        if (TODAY - dt.date.fromisoformat(prices[-1][0])).days > 14:   # 超過兩週沒成交 = 已下市/清算,不列入
            delisted.append(e["id"]); continue
        last = prices[-1]; prev = prices[-2] if len(prices) > 1 else last
        fname, fn = freq_of(divs)
        hp = os.path.join(DATA, "holdings", e["id"] + ".json")
        h = load(hp) if os.path.exists(hp) else {}
        PER = {"月配": 12, "季配": 4, "半年配": 2, "年配": 1}
        if len(divs) <= 2 and h.get("freqYahoo") in PER:   # 配息紀錄太少 -> 以投信公告的頻率為準
            fname, fn = h["freqYahoo"], PER[h["freqYahoo"]]
        cut = (TODAY - dt.timedelta(days=365)).isoformat()
        ttm = sum(d["cash"] for d in divs if d["ex"] >= cut)
        recent = divs[-fn:] if fn else []
        rows.append(dict(e,
            price=last[4], date=last[0], chg=round(last[4] - prev[4], 3), chgPct=round((last[4] / prev[4] - 1) * 100, 2) if prev[4] else 0,
            vol=last[5], freq=fname, perYear=fn, adj=e["id"] in splits,
            fee=h.get("fee"), aum=h.get("aum"), style=h.get("style"), issuer=h.get("issuer"),
            top3=[x[1] for x in h.get("top10", [])[:3]],
            exMonths=list(range(1, 13)) if fn == 12 else sorted({int(d["ex"][5:7]) for d in recent}),
            payMonths=list(range(1, 13)) if fn == 12 else sorted({int(d["pay"][5:7]) for d in recent if d["pay"]}),
            lastDiv=divs[-1] if divs else None,
            ttmCash=round(ttm, 4), ttmYield=round(ttm / last[4] * 100, 2) if last[4] else 0,
            # 用最近一次配息 x 一年次數 估「年化殖利率」(月配/季配常用講法)
            annYield=round(divs[-1]["cash"] * fn / last[4] * 100, 2) if divs and fn and last[4] else 0,
            yearYields=year_yields(divs, prices),
            monthly=monthly(prices),
            ta=ta.analyze(prices, divs, txc),
            ret1y=round((last[4] / next((r[4] for r in prices if r[0] >= cut), last[4]) - 1) * 100, 2)))
    tx = load(os.path.join(DATA, "taiex.json"))
    out = dict(updated=dt.datetime.now().strftime("%Y-%m-%d %H:%M"), taiex=dict(price=tx[-1][4], date=tx[-1][0], monthly=monthly(tx), vol=round(ta.taiex_vol([r[4] for r in tx]), 1)), etfs=rows)
    json.dump(out, open(os.path.join(DATA, "summary.json"), "w"), ensure_ascii=False, separators=(",", ":"))
    up = upcoming(); json.dump(up, open(os.path.join(DATA, "upcoming.json"), "w"), ensure_ascii=False, indent=0)
    print("已下市排除:", len(delisted), delisted[:15])
    print(f"summary: {len(rows)} 檔 / 預告 {len(up)} 筆 / {os.path.getsize(os.path.join(DATA,'summary.json'))//1024} KB")
    for r in rows[:8]:
        print(r["id"], r["name"], r["price"], r["freq"], "除息月", r["exMonths"], "發放月", r["payMonths"], "TTM殖利率", r["ttmYield"], "年化", r["annYield"])

if __name__ == "__main__":
    main()
