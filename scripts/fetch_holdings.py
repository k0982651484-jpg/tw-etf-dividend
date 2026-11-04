"""步驟3: 每檔ETF持股明細 -> data/holdings/{id}.json
- MoneyDJ: 完整持股清單(名稱/千股/比例/增減)
- Yahoo股市: 前十大(含代號)、產業/地區比重、資產配置、配息頻率、費用率、規模、追蹤指數、經理公司
可中斷續跑(今天抓過的跳過)。用法: python3 scripts/fetch_holdings.py [--only 0050,00878]
"""
import json, os, re, sys, time, datetime as dt, urllib.request
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/130 Safari/537.36"}
TODAY = dt.date.today()
FREQ = {"Monthly": "月配", "Quarterly": "季配", "Semi-Annually": "半年配", "Semi-Annual": "半年配", "Annual": "年配", "SemiAnnually": "半年配", "Annually": "年配", "Yearly": "年配"}

def get(url):
    for a in range(4):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40).read().decode("utf-8", "ignore")
        except urllib.error.HTTPError as e:
            if e.code == 404: return ""          # 該網站沒有這檔,不用重試
            print("   重試", a + 1, e); time.sleep(5 * (a + 1))
        except Exception as e:
            print("   重試", a + 1, e); time.sleep(5 * (a + 1))
    return ""

def grab(h, key):
    i = h.find('"' + key + '":')
    if i < 0: return None
    try: return json.JSONDecoder().raw_decode(h[i + len(key) + 3:])[0]
    except Exception: return None

def enclosing(h, key):
    i = h.find('"' + key + '"')
    if i < 0: return {}
    depth, j = 0, i
    while j > 0:
        j -= 1
        if h[j] == "}": depth += 1
        elif h[j] == "{":
            if depth == 0: break
            depth -= 1
    try: return json.JSONDecoder().raw_decode(h[j:])[0]
    except Exception: return {}

num = lambda s: float(s.replace(",", "")) if s and re.match(r"^-?[\d,.]+$", s.strip()) else None

def moneydj(sid):
    h = get(f"https://www.moneydj.com/ETF/X/Basic/Basic0007a.xdjhtm?etfid={sid}.TW")
    rows = re.findall(r'<td class="col05">(.*?)</td>\s*<td class="col06">(.*?)</td>\s*<td class="col07">(.*?)</td>\s*<td class="col08">(.*?)</td>', h, re.S)
    strip = lambda s: re.sub(r"<[^>]+>", "", s).strip()
    full = [[strip(a), num(strip(b)), num(strip(c)), strip(d)] for a, b, c, d in rows]
    date = (re.findall(r"資料日期：([\d/]+)", h) or [""])[0]
    return full, date

def yahoo(sid, market):
    h = get(f"https://tw.stock.yahoo.com/quote/{sid}.{'TWO' if market == '上櫃' else 'TW'}/holding")
    p = enclosing(h, "divCashFreq")
    ind = grab(h, "investIndustryWeights") or {}
    loc = lambda v: v.get("local") if isinstance(v, dict) else v
    return dict(
        top10=[[x.get("ticker", "").split(".")[0], x.get("name"), num(x.get("weighting"))] for x in (grab(h, "holdingDetail") or []) if isinstance(x, dict)],
        top10Date=((grab(h, "holdingDetail") or [{}])[0] or {}).get("date", ""),
        industry=[[x.get("name"), num(x.get("weighting"))] for x in (ind.get("detail") or []) if isinstance(x, dict)],
        asset={k: num(v) for k, v in (grab(h, "assetAllocation") or {}).items() if k != "date"},
        freqYahoo=FREQ.get(p.get("divCashFreq"), p.get("divCashFreq") or ""),
        fee=p.get("managementfee"), custodian=p.get("custodianfee"),
        aum=num(p.get("totalAssets") or ""), aumDate=p.get("totalAssetsDate"),
        benchmark=p.get("primaryProspectusBenchmark"), issuer=loc(p.get("providerCompanyName")),
        manager=loc(p.get("fundManagerName")), inception=p.get("inceptionDate"), style=p.get("category"),
        investRegion=loc(p.get("investRegion")), premium=(grab(h, "premiumDiscount") or {}).get("daily"))

def main():
    master = json.load(open(os.path.join(DATA, "etf_master.json")))
    if "--only" in sys.argv:
        only = sys.argv[sys.argv.index("--only") + 1].split(","); master = [e for e in master if e["id"] in only]
    if "--oldest" in sys.argv:      # 每日輪流:只更新最久沒更新的 N 檔(+指定的新ETF)
        n = int(sys.argv[sys.argv.index("--oldest") + 1])
        extra = sys.argv[sys.argv.index("--ids") + 1].split(",") if "--ids" in sys.argv else []
        mt = lambda e: os.path.getmtime(os.path.join(DATA, "holdings", e["id"] + ".json")) if os.path.exists(os.path.join(DATA, "holdings", e["id"] + ".json")) else 0
        master = [e for e in master if e["id"] in extra] + sorted([e for e in master if e["id"] not in extra], key=mt)[:n]
    ap = os.path.join(DATA, "aum_history.json")
    aum_hist = json.load(open(ap)) if os.path.exists(ap) else {}
    for n, e in enumerate(master, 1):
        path = os.path.join(DATA, "holdings", e["id"] + ".json")
        if os.path.exists(path) and dt.date.fromtimestamp(os.path.getmtime(path)) == TODAY:
            continue
        try:
            full, fdate = moneydj(e["id"]); time.sleep(1)
            y = yahoo(e["id"], e["market"]); time.sleep(1)
        except Exception as ex:          # 單檔出錯不中斷整批,下次再補
            print(f"[{n}/{len(master)}] {e['id']} 失敗: {ex}", flush=True); continue
        out = dict(id=e["id"], fetched=TODAY.isoformat(), full=full, fullDate=fdate, **y)
        json.dump(out, open(path, "w"), ensure_ascii=False, separators=(",", ":"))
        if y.get("aum"):            # 規模歷史:之後可畫規模成長趨勢
            hst = aum_hist.setdefault(e["id"], [])
            d = (y.get("aumDate") or TODAY.isoformat()).replace("/", "-")
            if not hst or hst[-1][0] != d: hst.append([d, y["aum"]])
            json.dump(aum_hist, open(ap, "w"), separators=(",", ":"))
        print(f"[{n}/{len(master)}] {e['id']} {e['name']} 完整{len(full)}檔 前十{len(y['top10'])} 產業{len(y['industry'])} 頻率:{y['freqYahoo']} 費用:{y['fee']}", flush=True)
    print("全部完成")

if __name__ == "__main__":
    main()
