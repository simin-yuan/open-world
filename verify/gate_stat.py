#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""gate_stat.py — GATE.md §八「弃权即采纳基线」的执行件（确定性、零 LLM、只读）。

它只回答一件事：

    在事先写死的出题规则下，我在**可评规则题**上是否显著优于同题「照旧基线」？

判据全部来自 `GATE.md` §八（2026-09-26 已签，署名 = 权威链持有者）。本文件**不新造判据**：

  · 配对差 `d_i = Brier(基线_i) − Brier(我_i)`；我方弃权的题记 `d_i = 0`
  · 以**窗口**为单位（同窗口的 6 道题高度相关，不许把单题当独立样本）
  · 全体可评题 `mean(d)` 的**单侧 95% t 区间下界 > 0 ⇒ 通过**，否则 ⇒ 无法判定
  · `α = 0.05`、`N0 ≥ 10` —— 这两个门槛不是本工具选的，是 §八 写死的

§八 的三条前置条件在这里是**硬门**：不满足时输出「无法判定」并点名缺什么，不给数。

  ①【P1】基线必须对每道到期题落事前概率（含我弃权的题）。
      本工具**只读** `data/sonda_baseline.jsonl` 里的 `p_base`，**不自行推导**。
      「照旧基线」是判据的一部分，工具去推导它 = 替基线改答案。
  ②【P2】系统拒题不得记成我方弃权。只认 `refused_system` / `abstained_self` 两个字段；
      台账里没有这个拆分 = 前置条件 ② 未落地。
      （诚实边界：本工具只查这两个字段**在不在**，查不出「值放错了桶」。）
  ③【P3】区间按窗口算 —— 见上。

输出只有三值：

    PASS=0 · UNDECIDABLE=2 · ERROR=3

`ERROR` 是**仪器故障**（规则读不出来、台账坏行），不是一个判断；故意与 `UNDECIDABLE` 分开记，
否则「量不出来」会被读成「结论是不行」。§八 没有「FAIL」这一值，本工具不新造。

用法：
    python verify/gate_stat.py                    # 读本仓库 data/
    python verify/gate_stat.py --json             # 机读
    python verify/gate_stat.py --repo <副本>      # 换一份导出台账（selftest 用）
    python verify/gate_stat.py --explain          # 打印题目清单（前 12 道可评题）

数据契约（缺任一项，对应前置条件就会红，而不是静默当 0）：
    data/question_rule.json        出题规则（公开且固定；漂移由 check.py 第 ⑥ 腿抓）
    data/state_reads.jsonl         世界侧读数 —— 题目与结算都从这里来（世界给答案）
    data/sonda_predictions.jsonl   我方事前概率 p_mine（按 字段/视界/方向/阈值/窗口 匹配）
    data/sonda_baseline.jsonl      【前置条件①要求的】基线事前概率 p_base（本工具只读，不推导）
    data/sonda_decisions.jsonl     弃权与拒题的拆分（abstained_self / refused_system）
"""
import argparse
import datetime
import json
import math
import os
import sys

CN = datetime.timezone(datetime.timedelta(hours=8))
DEFAULT_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# ---- 门槛：全部抄自 GATE.md §八，本文件不新增及格线 ---------------------------------
ALPHA = 0.05          # §八：单侧 95%
N0_MIN = 10           # §八：可评题数 < 10 ⇒ 直接无法判定
CLUSTER_MIN = 2       # 非判据：单侧 t 区间需要 df >= 1，df = 聚类数 - 1。
                      # 写在这里只是为了让「算不出区间」与「区间算出来不达标」两件事可分辨。

BASELINE_FILE = "sonda_baseline.jsonl"
RULE_FILE = "question_rule.json"
READS_FILE = "state_reads.jsonl"
PRED_FILE = "sonda_predictions.jsonl"
DEC_FILE = "sonda_decisions.jsonl"

PASS, UNDECIDABLE, ERROR = "PASS", "UNDECIDABLE", "ERROR"
EXIT = {PASS: 0, UNDECIDABLE: 2, ERROR: 3}


# ---- 读盘（只读；「文件不存在」与「文件是空的」分开记） -----------------------------
def jlines(path):
    """-> (rows, note)。文件不存在返回 (None, 'missing')，空文件返回 ([], 'empty')。"""
    if not os.path.exists(path):
        return None, "missing"
    rows = []
    bad = 0
    for line in open(path, encoding="utf-8"):
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except ValueError:
            bad += 1
    return rows, ("%d bad line(s)" % bad if bad else "ok")


def jload(path):
    if not os.path.exists(path):
        return None, "missing"
    try:
        return json.load(open(path, encoding="utf-8")), "ok"
    except ValueError as e:
        return None, "unreadable: %s" % str(e)[:80]


def parse(ts):
    try:
        return datetime.datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None


# ---- 统计：单侧 t 区间下界（纯 stdlib，无 scipy；可被 selftest 对着已知分位点验） -----
def _betacf(a, b, x):
    MAXIT, EPS, FPMIN = 300, 3e-16, 1e-300
    qab, qap, qam = a + b, a + 1.0, a - 1.0
    c, d = 1.0, 1.0 - qab * x / qap
    if abs(d) < FPMIN:
        d = FPMIN
    d = 1.0 / d
    h = d
    for m in range(1, MAXIT + 1):
        m2 = 2 * m
        aa = m * (b - m) * x / ((qam + m2) * (a + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        h *= d * c
        aa = -(a + m) * (qab + m) * x / ((a + m2) * (qap + m2))
        d = 1.0 + aa * d
        if abs(d) < FPMIN:
            d = FPMIN
        c = 1.0 + aa / c
        if abs(c) < FPMIN:
            c = FPMIN
        d = 1.0 / d
        de = d * c
        h *= de
        if abs(de - 1.0) < EPS:
            break
    return h


def _betai(a, b, x):
    if x <= 0:
        return 0.0
    if x >= 1:
        return 1.0
    lb = math.lgamma(a + b) - math.lgamma(a) - math.lgamma(b)
    bt = math.exp(lb + a * math.log(x) + b * math.log(1.0 - x))
    if x < (a + 1.0) / (a + b + 2.0):
        return bt * _betacf(a, b, x) / a
    return 1.0 - bt * _betacf(b, a, 1.0 - x) / b


def t_cdf(t, df):
    """P(T <= t)，T ~ t(df)。"""
    x = df / (df + t * t)
    upper = 0.5 * _betai(df / 2.0, 0.5, x)   # P(T > |t|)
    return 1.0 - upper if t > 0 else upper


def t_onesided_quantile(p, df):
    """满足 cdf(t) = p 的 t（p > 0.5）—— 单侧分位点，二分求解，确定性。"""
    lo, hi = 0.0, 1.0
    while t_cdf(hi, df) < p:
        hi *= 2.0
        if hi > 1e6:
            break
    for _ in range(200):
        mid = (lo + hi) / 2.0
        if t_cdf(mid, df) < p:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2.0


def mean_sd(xs):
    n = len(xs)
    if n == 0:
        return None, None
    m = sum(xs) / float(n)
    if n == 1:
        return m, None
    var = sum((x - m) ** 2 for x in xs) / float(n - 1)
    return m, math.sqrt(var)


def brier(p, hit):
    return (float(p) - (1.0 if hit else 0.0)) ** 2


# ---- 主评估 ------------------------------------------------------------------------
def evaluate(repo):
    out = {"generated_at": datetime.datetime.now(CN).isoformat(timespec="seconds"),
           "repo_files": {}, "errors": [], "reasons": [], "counts": {}, "stats": {},
           "preconditions": {}, "accounting": {}, "examples": []}
    errors = out["errors"]

    sys.path.insert(0, os.path.join(repo, "tools"))
    try:
        import question_rule as qr          # noqa: E402 —— 参考答案实现，出题规则与门同源
    except Exception as e:                  # pragma: no cover
        errors.append("TOOLS_UNREADABLE: tools/question_rule.py 载不进来：%s" % str(e)[:120])
        out["verdict"] = ERROR
        out["reasons"].append("仪器故障：参考实现不可用")
        return out, EXIT[ERROR]

    rule, rn = jload(os.path.join(repo, "data", RULE_FILE))
    out["repo_files"][RULE_FILE] = rn
    if rule is None:
        errors.append("RULES_UNREADABLE: data/%s %s —— 判据的规则部分读不出来" % (RULE_FILE, rn))

    # 读数只认 question_rule.read_rows（它同时是出题规则的取数口径）
    reads_path = os.path.join(repo, "data", READS_FILE)
    reads = qr.read_rows(reads_path) if os.path.exists(reads_path) else None
    out["repo_files"][READS_FILE] = "missing" if reads is None else ("ok" if reads else "empty")
    if not reads:
        errors.append("READS_%s: data/%s 没有可用读数 —— 题目和结算都出不来"
                      % ("MISSING" if reads is None else "EMPTY", READS_FILE))

    if errors:
        out["verdict"] = ERROR
        out["reasons"].append("仪器故障：%d 项" % len(errors))
        return out, EXIT[ERROR]

    try:
        qr.load_rule(os.path.join(repo, "data", RULE_FILE))   # 规则本体的自校验
    except Exception as e:                                    # 规则不合法 = 判据不可用
        errors.append("RULE_INVALID: %s" % str(e)[:120])
        out["verdict"] = ERROR
        out["reasons"].append("仪器故障：规则本体非法")
        return out, EXIT[ERROR]

    tol = float(rule.get("tol_minutes", 15))
    grid = qr.all_windows_grid(reads, rule)                   # 与门同源的出题规则
    out["counts"]["grid_questions"] = len(grid)
    out["counts"]["windows"] = len({(g["field"], g["window_start"]) for g in grid})

    # 世界侧读数：按字段建索引，供端点取值
    by_field = {}
    for t, r in reads:
        for f in rule["whitelist"]:
            if r.get(f) is not None:
                by_field.setdefault(f, []).append((t, r.get(f)))

    def value_at(field, t):
        for tt, v in by_field.get(field, []):
            if abs((tt - t).total_seconds()) <= tol * 60:
                return v
        return None

    # 事前概率：我方（predictions）与基线（baseline）分别索引
    preds, pn = jlines(os.path.join(repo, "data", PRED_FILE))
    out["repo_files"][PRED_FILE] = pn
    base, bn = jlines(os.path.join(repo, "data", BASELINE_FILE))
    out["repo_files"][BASELINE_FILE] = bn
    decs, dn = jlines(os.path.join(repo, "data", DEC_FILE))
    out["repo_files"][DEC_FILE] = dn

    def ident(r):
        try:
            return (str(r.get("field")), float(r.get("horizon_hours")), str(r.get("direction")),
                    float(0.0 if r.get("threshold") is None else r.get("threshold")))
        except (TypeError, ValueError):
            return None

    def wkey(r):
        t0 = parse(r.get("window_start") or r.get("baseline_at") or r.get("written_at"))
        return t0

    pred_ix, base_ix = {}, {}
    for row, ix in ((preds or []), pred_ix), ((base or []), base_ix):
        for r in rows_of(row):
            k = ident(r)
            if k:
                ix.setdefault(k, []).append(r)

    def find_window_match(rows, k, w0, w1):
        """在同类事前概率行里，找出**确实指向这个窗口**的那一条。"""
        for r in rows:
            t0 = wkey(r)
            if t0 is None:
                continue
            try:
                h = float(r.get("horizon_hours"))
            except (TypeError, ValueError):
                continue
            t1 = t0 + datetime.timedelta(hours=h)
            if (abs((t0 - w0).total_seconds()) <= tol * 60
                    and abs((t1 - w1).total_seconds()) <= tol * 60):
                return r
        return None

    # 弃权 / 拒题的拆分：只认这两个字段（前置条件②）
    self_abstained, refused = set(), set()
    split_rows = 0
    for d in decs or []:
        if "abstained_self" in d or "refused_system" in d:
            split_rows += 1
        for tag, sink in (("abstained_self", self_abstained), ("refused_system", refused)):
            for q in (d.get(tag) or []):
                sink.add(str(q))

    n_out_known = n_base_missing = n_unaccounted = n_refused = 0
    ds, clusters = [], {}
    for g in grid:
        f, h, d, thr = g["field"], float(g["horizon_hours"]), g["direction"], float(g["threshold"])
        w0, w1 = parse(g["window_start"]), parse(g["window_end"])
        v0, v1 = value_at(f, w0), value_at(f, w1)
        if v0 is None or v1 is None:
            continue                                   # 端点缺读数：题目不可评（样本没到，不是失败）
        n_out_known += 1
        delta = v1 - v0
        hit = (delta > thr) if d == "gt" else (delta < -thr)   # 阈值 0 时两个方向互为否；非 0 阈值此处为对称假设

        k = (f, h, d, thr)
        qtag = "%s|%g|%s|%g" % (f, h, d, thr)
        if qtag in refused:
            n_refused += 1
            continue                                   # 系统拒题：从 N0 剔除（§八 前置条件②）
        # 两个计数**各自独立**统计，互不遮蔽 ——
        # 若让「缺基线」先 continue，`unaccounted` 会永远显示 0，读起来像「我方处置记录齐全」，
        # 实际只是没走到那一步。仪器不能把「没量」报成「量到 0」。
        p_base_row = find_window_match(base_ix.get(k, []), k, w0, w1) if base else None
        has_base = p_base_row is not None and p_base_row.get("p_base") is not None
        p_mine_row = find_window_match(pred_ix.get(k, []), k, w0, w1) if preds else None
        has_mine = p_mine_row is not None and p_mine_row.get("probability") is not None
        has_abstain = qtag in self_abstained
        if not has_base:
            n_base_missing += 1
        if not (has_mine or has_abstain):
            n_unaccounted += 1
        if not (has_base and (has_mine or has_abstain)):
            continue                                   # 不评；不许替自己补一条处置记录
        p_mine = float(p_mine_row["probability"]) if has_mine else float(p_base_row["p_base"])
        #                                                                    ↑ §八：弃权即采纳基线 ⇒ d=0
        di = brier(float(p_base_row["p_base"]), hit) - brier(p_mine, hit)
        ds.append(di)
        clusters.setdefault((f, g["window_start"]), []).append(di)
        if len(out["examples"]) < 12:
            out["examples"].append({"q": qtag, "window_start": g["window_start"],
                                    "hit": hit, "p_mine": p_mine,
                                    "p_base": float(p_base_row["p_base"]), "d": round(di, 6)})

    n0 = len(ds)
    wk = sorted(clusters)
    dw = [sum(clusters[x]) / float(len(clusters[x])) for x in wk]
    m_w, sd_w = mean_sd(dw)
    m_q, sd_q = mean_sd(ds)
    tcrit = t_onesided_quantile(1.0 - ALPHA, len(dw) - 1) if len(dw) >= CLUSTER_MIN else None
    lower = (m_w - tcrit * sd_w / math.sqrt(len(dw))) if (tcrit is not None and sd_w is not None) else None

    out["counts"].update({"outcome_known": n_out_known, "baseline_missing": n_base_missing,
                          "unaccounted": n_unaccounted, "refused_system": n_refused,
                          "n0": n0, "clusters": len(dw)})
    out["accounting"] = {"abstained_self_tags": len(self_abstained), "refused_system_tags": len(refused),
                         "decision_rows_with_split": split_rows,
                         "decision_rows_total": len(decs or [])}
    out["stats"] = {"mean_d_question": m_q, "sd_d_question": sd_q, "mean_d_window": m_w,
                    "sd_d_window": sd_w, "t_crit": tcrit, "lower_bound": lower,
                    "alpha": ALPHA, "n0_min": N0_MIN}

    p1 = (base is not None and n_base_missing == 0 and n0 > 0)
    p2 = split_rows > 0
    out["preconditions"] = {
        "P1_baseline_logged": p1,
        "P1_note": ("data/%s 不存在 —— 前置条件①未落地" % BASELINE_FILE) if base is None
                   else ("%d 道可评题缺 p_base" % n_base_missing if n_base_missing else "ok"),
        "P2_refusal_split": p2,
        "P2_note": "%d 行决策含 abstained_self/refused_system" % split_rows,
        "P3_window_cluster": True,
    }

    r = out["reasons"]
    if n0 == 0:
        r.append("NO_EVALUABLE_QUESTION: 0 道规则题同时具备『世界已给答案 + 基线 p_base + 我方处置记录』")
    if n0 < N0_MIN:
        r.append("N0_BELOW_MIN: 可评题 %d < %d" % (n0, N0_MIN))
    if len(dw) < CLUSTER_MIN:
        r.append("CLUSTERS_BELOW_MIN: 可评窗口 %d < %d（单侧 t 区间需要 df>=1）" % (len(dw), CLUSTER_MIN))
    if not p1:
        r.append("P1_UNMET: %s" % out["preconditions"]["P1_note"])
    if not p2:
        r.append("P2_UNMET: 决策台账没有 abstained_self/refused_system 拆分——"
                 "系统拒题与我方弃权现在还混在 abstained 里")
    if r:
        out["verdict"] = UNDECIDABLE
        return out, EXIT[UNDECIDABLE]
    if lower is not None and lower > 0:
        out["verdict"] = PASS
        return out, EXIT[PASS]
    out["verdict"] = UNDECIDABLE
    out["reasons"].append("CI_INCLUDES_ZERO: 单侧 95%% 下界 %.6f <= 0（可评题已足，这是判据算出来的结果）"
                          % (lower if lower is not None else float("nan")))
    return out, EXIT[UNDECIDABLE]


def rows_of(x):
    return x if x else []


def render(out):
    p = print
    p("gate_stat — GATE.md §八「弃权即采纳基线」执行件（只读、零 LLM）")
    p("  门槛（抄自 §八）：单侧 %g 区间 · N0 >= %d · 以窗口为单位"
      % (1 - ALPHA, N0_MIN))
    c = out.get("counts", {})
    p("")
    p("[观测] 规则网格 %s 道 / %s 个窗口 · 两端可比读数 %s 道"
      % (c.get("grid_questions"), c.get("windows"), c.get("outcome_known")))
    p("[观测] 缺基线 p_base %s 道 · 无我方处置记录 %s 道 · 系统拒题 %s 道"
      % (c.get("baseline_missing"), c.get("unaccounted"), c.get("refused_system")))
    p("[观测] 可评题 N0=%s · 可评窗口 %s" % (c.get("n0"), c.get("clusters")))
    pre = out.get("preconditions", {})
    p("[观测] 前置条件 ①基线落账=%s（%s）②拒题拆分=%s（%s）③窗口聚类=%s"
      % (pre.get("P1_baseline_logged"), pre.get("P1_note"),
         pre.get("P2_refusal_split"), pre.get("P2_note"), pre.get("P3_window_cluster")))
    s = out.get("stats", {})
    if s.get("mean_d_window") is not None:
        p("[观测] mean(d)=%.6f（题级 %.6f）· sd=%.6f · t*=%s · 下界=%s"
          % (s["mean_d_window"], s.get("mean_d_question") or float("nan"),
             s.get("sd_d_window") or float("nan"),
             ("%.4f" % s["t_crit"]) if s.get("t_crit") is not None else "算不出",
             ("%.6f" % s["lower_bound"]) if s.get("lower_bound") is not None else "算不出"))
    for name, note in out.get("repo_files", {}).items():
        p("[源] data/%s = %s" % (name, note))
    for f in out.get("errors", []):
        p("ERROR %s" % f)
    for rr in out.get("reasons", []):
        p("REASON %s" % rr)
    p("")
    if out["verdict"] == PASS:
        p("结论：通过 —— 单侧 95%% 下界 > 0。")
    elif out["verdict"] == UNDECIDABLE:
        p("结论：无法判定 —— 这不是失败，是现有的台账还算不出这个数。上面点名了缺什么。")
    else:
        p("结论：ERROR —— 仪器故障，不是一个判断。")


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=os.environ.get("GATE_REPO") or DEFAULT_REPO)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--explain", action="store_true", help="打印前 12 道可评题的明细")
    a = ap.parse_args(argv)
    out, code = evaluate(os.path.abspath(a.repo))
    if a.json:
        print(json.dumps(out, ensure_ascii=False, indent=1))
    else:
        render(out)
        if a.explain:
            print("\n[明细] 前 12 道可评题：")
            for e in out.get("examples", []):
                print("  %-34s @%s hit=%s p_mine=%s p_base=%s d=%s"
                      % (e["q"], e["window_start"], e["hit"], e["p_mine"], e["p_base"], e["d"]))
    return code


if __name__ == "__main__":
    sys.exit(main())
