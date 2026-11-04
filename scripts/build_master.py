"""步驟1: 建立全台ETF清單+分類 -> data/etf_master.json"""
import json, re, urllib.request, os
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
URL = "https://api.finmindtrade.com/api/v4/data?dataset=TaiwanStockInfo"
d = json.load(urllib.request.urlopen(URL, timeout=60))["data"]

# 主分類規則(由上往下第一個命中)
RULES = [
    ("槓桿反向", lambda i,n: i.endswith(("L","R")) or re.search(r"正2|反1|正向|反向|兩倍|2倍", n)),
    ("債券",     lambda i,n: i.endswith("B") or "債" in n or "投等" in n),
    ("平衡型",   lambda i,n: i.endswith("T") or "平衡" in n),
    ("原物料期貨", lambda i,n: i.endswith("U") or re.search(r"黃金|白銀|原油|石油|黃豆|期貨|商品|銅", n)),
    ("不動產",   lambda i,n: re.search(r"REIT|不動產|房地產", n, re.I)),
    ("高股息",   lambda i,n: re.search(r"高息|高股息|股息|股利|優息|收益|填息|入息|特別股|息收|配息|高利|月月|鑫收", n)),
    ("科技",     lambda i,n: re.search(r"半導體|科技|電子|5G|AI|晶片|IC|網通|電動車|雲端|資安|元宇宙|機器人|FANG|NASDAQ|那斯達克|費城|創新|未來車|通訊|數位|智能|算力|伺服器|太空|量子|晶圓|納斯達克|NASDAQ|IC設計|生技|醫療|軟體|網路|電信", n, re.I)),
    ("ESG永續",  lambda i,n: re.search(r"ESG|永續|低碳|淨零|綠能|潔淨|氫能|電池", n, re.I)),
    ("金融",     lambda i,n: "金融" in n or "銀行" in n),
    ("市值型",   lambda i,n: re.search(r"台灣50|臺灣50|台50|中型100|MSCI|領袖|寶島|市值|加權|台灣大|臺灣|台灣|中小|藍籌|精選|100|50|S&P|標普|日經|東證|滬深|上証|上證|深証|A50|摩台|韓國|印度|歐洲|道瓊|富時|恒生|香港|越南|日本|全球|新興|大型|中國|東協|德國|發達|台商|富櫃", n)),
]
OVERSEAS = r"美國|美股|S&P|標普|日本|日經|東證|中國|滬深|上証|上證|深|香港|恒生|印度|越南|歐洲|全球|NASDAQ|那斯達克|費城|韓國|東協|新興|亞洲|道瓊|FANG|美|日|陸|A50|德國|英國"

def classify(i, n):
    cat = next((c for c, f in RULES if f(i, n)), "其他主題")
    region = "海外" if re.search(OVERSEAS, n, re.I) and not re.search(r"台|臺", n) else "台股"
    if cat == "債券": region = "海外" if not re.search(r"台|臺|公司債\b", n) and re.search(r"美|全球|新興|歐|亞|中國|投等|非投等|公債|政府|金融債|科技債|電信|醫療|A級|BBB|AAA|\+", n) else region
    tags = []
    if i.endswith("A") or n.startswith("主動"): tags.append("主動式")
    if re.search(r"月月|月配|月收", n): tags.append("月配名稱")
    return cat, region, tags

etf = {}
for x in d:
    c = x["industry_category"]
    if "ETF" not in c: continue          # 受益證券(REITs信託 T 結尾)另計
    sid, name = x["stock_id"], x["stock_name"]
    if sid in etf: continue
    cat, region, tags = classify(sid, name)
    etf[sid] = dict(id=sid, name=name, market="上市" if x["type"]=="twse" else "上櫃",
                    listed=x["date"], category=cat, region=region, tags=tags)
# REITs 受益證券也收進來(一樣會配息)
for x in d:
    if x["industry_category"] == "受益證券" and x["stock_id"] not in etf:
        etf[x["stock_id"]] = dict(id=x["stock_id"], name=x["stock_name"], market="上市" if x["type"]=="twse" else "上櫃",
                                  listed=x["date"], category="不動產", region="台股", tags=["REITs"])

out = sorted(etf.values(), key=lambda e: e["id"])
json.dump(out, open(os.path.join(ROOT, "data", "etf_master.json"), "w"), ensure_ascii=False, indent=1)
from collections import Counter
print("總數", len(out))
print(Counter(e["category"] for e in out).most_common())
print(Counter(e["region"] for e in out))
for c in ["科技","高股息","市值型","其他主題"]:
    print(c, [e["id"]+e["name"] for e in out if e["category"]==c][:25])
