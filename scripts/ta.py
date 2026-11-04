"""技術分析指標:從日K算出趨勢/動能/位置/波動/填息/相對大盤,給 build_summary 用
prices: [[日期, 開, 高, 低, 收, 張], ...]  (已還原分割、未還原配息 -> 才能算填息)
"""
import math

def _ma(c, n):
    return sum(c[-n:]) / n if len(c) >= n else None

def _ema(vals, n):
    k, out, e = 2 / (n + 1), [], None
    for v in vals:
        e = v if e is None else v * k + e * (1 - k)
        out.append(e)
    return out

def _rsi(c, n=14):
    if len(c) <= n: return None
    g = l = 0
    for i in range(1, n + 1):
        d = c[i] - c[i - 1]; g += max(d, 0); l += max(-d, 0)
    g, l = g / n, l / n
    for i in range(n + 1, len(c)):
        d = c[i] - c[i - 1]
        g = (g * (n - 1) + max(d, 0)) / n
        l = (l * (n - 1) + max(-d, 0)) / n
    return 100.0 if l == 0 else 100 - 100 / (1 + g / l)

def _kd(h, lo, c, n=9):
    k = d = 50.0
    for i in range(len(c)):
        if i < n - 1: continue
        hh, ll = max(h[i - n + 1:i + 1]), min(lo[i - n + 1:i + 1])
        rsv = 50 if hh == ll else (c[i] - ll) / (hh - ll) * 100
        k = k * 2 / 3 + rsv / 3
        d = d * 2 / 3 + k / 3
    return k, d

def _vol(c, n=250):
    r = [math.log(c[i] / c[i - 1]) for i in range(max(1, len(c) - n), len(c)) if c[i - 1] > 0 and c[i] > 0]
    if len(r) < 20: return None
    m = sum(r) / len(r)
    return math.sqrt(sum((x - m) ** 2 for x in r) / (len(r) - 1)) * math.sqrt(252) * 100

def _mdd(c, n=250):
    peak, mdd = 0, 0
    for v in c[-n:]:
        peak = max(peak, v); mdd = min(mdd, v / peak - 1) if peak else mdd
    return mdd * 100

def _ret(c, n):
    return (c[-1] / c[-n - 1] - 1) * 100 if len(c) > n and c[-n - 1] else None

def fill_stats(prices, divs, last_n=4):
    """填息:除息前一天收盤價,之後第一天收盤 >= 它就算填息"""
    dates = [p[0] for p in prices]; c = [p[4] for p in prices]
    out = []
    for d in [x for x in divs if x["ex"] <= dates[-1]][-last_n:]:
        i = next((k for k, t in enumerate(dates) if t >= d["ex"]), None)
        if not i: continue
        pre = c[i - 1]
        j = next((k for k in range(i, len(c)) if c[k] >= pre), None)
        out.append(dict(ex=d["ex"], cash=d["cash"], days=(j - i + 1) if j is not None else None, waited=len(c) - i))
    return out

def analyze(prices, divs, taiex_close):
    pr = [p for p in prices if p[4] > 0]
    if len(pr) < 30: return None
    h, lo, c, v = [p[2] for p in pr], [p[3] for p in pr], [p[4] for p in pr], [p[5] for p in pr]
    px = c[-1]
    ma = {n: _ma(c, n) for n in (5, 20, 60, 120, 240)}
    ma20_10 = _ma(c[:-10], 20) if len(c) > 30 else None
    macd_line = [a - b for a, b in zip(_ema(c, 12), _ema(c, 26))]
    sig = _ema(macd_line, 9)
    hist, hist_prev = macd_line[-1] - sig[-1], macd_line[-2] - sig[-2]
    k, d = _kd(h, lo, c)
    rsi = _rsi(c)
    w = c[-250:]; hi52, lo52 = max(w), min(w)
    pos = (px - lo52) / (hi52 - lo52) * 100 if hi52 > lo52 else 50
    vol, mdd = _vol(c), _mdd(c)
    v5, v20 = sum(v[-5:]) / 5, sum(v[-20:]) / 20 if len(v) >= 20 else None

    # ---- 分數 (0~100) ----
    t = 0; tn = 0
    for ok in (ma[20] and px > ma[20], ma[60] and ma[20] and ma[20] > ma[60], ma[120] and ma[60] and ma[60] > ma[120],
               ma[240] and px > ma[240], ma20_10 and ma[20] and ma[20] > ma20_10):
        if ok is None: continue
        tn += 1; t += 1 if ok else 0
    trend = round(t / tn * 100) if tn else 50
    mom = 50
    if rsi is not None: mom += 15 if 50 <= rsi <= 70 else 5 if 40 <= rsi < 50 else -10 if rsi > 80 else -15 if rsi < 30 else 0
    mom += 15 if hist > 0 else -15
    mom += 10 if hist > hist_prev else -10
    mom += 10 if k > d else -10
    mom = max(0, min(100, mom))
    # 相對大盤(近3個月 / 近1年)
    rel3 = rel12 = None
    if taiex_close:
        tr3, tr12 = _ret(taiex_close, 63), _ret(taiex_close, 250)
        r3, r12 = _ret(c, 63), _ret(c, 250)
        if r3 is not None and tr3 is not None: rel3 = r3 - tr3
        if r12 is not None and tr12 is not None: rel12 = r12 - tr12
    fills = fill_stats(pr, divs)
    done = [f for f in fills if f["days"] is not None]
    risk = None if vol is None else max(0, min(100, round(100 - (vol - 8) * 3)))   # 波動越小分數越高
    total = round(trend * .4 + mom * .3 + (risk if risk is not None else 50) * .15 + (100 - abs(pos - 55)) * .15)
    r1 = lambda x, n=2: None if x is None else round(x, n)
    return dict(score=total, trend=trend, mom=mom, risk=risk,
                ma={str(n): r1(x, 3) for n, x in ma.items()}, rsi=r1(rsi, 1), k=r1(k, 1), d=r1(d, 1),
                macd=r1(hist, 4), macdUp=hist > hist_prev, pos=r1(pos, 1), hi52=hi52, lo52=lo52,
                vol=r1(vol, 1), mdd=r1(mdd, 1), volRatio=r1(v5 / v20, 2) if v20 else None,
                ret1m=r1(_ret(c, 21)), ret3m=r1(_ret(c, 63)), rel3=r1(rel3), rel12=r1(rel12),
                fills=fills, fillAvg=r1(sum(f["days"] for f in done) / len(done), 1) if done else None,
                fillRate=f"{len(done)}/{len(fills)}" if fills else None)

def taiex_vol(taiex_close):
    return _vol(taiex_close)
