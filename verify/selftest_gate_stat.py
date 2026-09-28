#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selftest_gate_stat.py — 证明 gate_stat.py **既能说不，也能说是**。

一个只会输出「无法判定」的脚本等于装饰：它对任何输入都返回同一个答案，因此不携带信息。
所以这里不只喂坏样本，也喂一份**契约完整、结论明确**的合成台账，要求它真的判 PASS。

七个样本 + 一个对照：

    CONTROL 真实台账          → 必须 UNDECIDABLE（而不是一个数）
    S1 契约完整、我明显优于基线 → 必须 PASS（证明它不是恒真条件）
    S2 可评题 2 道（<10）      → 必须 UNDECIDABLE（N0_BELOW_MIN）
    S3 缺基线台账              → 必须 UNDECIDABLE（P1_UNMET）
    S4 缺弃权/拒题拆分         → 必须 UNDECIDABLE（P2_UNMET）
    S5 我与基线同分（d≡0）     → 必须 UNDECIDABLE（CI_INCLUDES_ZERO）
    S6 规则文件坏              → 必须 ERROR（仪器故障 ≠ 判断）
    T  单侧 95% t 分位点表     → 对着已知值校验（本工具不用 scipy，分位数是自算的）

**合成样本能证明什么、不能证明什么（诚实边界）**：
  能：本工具的**分支与阈值**——契约缺哪一项就红哪一项、区间怎么聚、什么时候不给数。
  不能：门**真实产出的形态**。上面的 `sonda_baseline.jsonl` / `abstained_self` 是按 §八 的
  前置条件**我构造的**，本地门现在还没有这两个字段；真实形态对不上时，本工具会报
  P1/P2 未落地（CONTROL 就是这个结果），而不是硬算。

    python verify/selftest_gate_stat.py
"""
import datetime
import json
import os
import shutil
import subprocess
import sys
import tempfile

CN = datetime.timezone(datetime.timedelta(hours=8))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import gate_stat as G   # noqa: E402

T0 = datetime.datetime(2026, 9, 20, 0, 0, tzinfo=CN)
RULE = {"version": 1, "whitelist": ["mkt_silicon_best_buy"], "horizons_hours": [3.0, 6.0, 12.0],
        "directions": ["gt", "lt"], "threshold": 0.0, "tol_minutes": 15, "self_fields": ["credits"]}


def iso(t):
    return t.isoformat(timespec="seconds")


def build(dst, n_reads, p_base=0.5, p_fn=None, with_baseline=True, with_split=True,
          bad_rule=False, step_min=30):
    """按 §八 的契约造一份合成台账。p_fn(i_window) -> (p_gt, p_lt)。"""
    os.makedirs(os.path.join(dst, "data"), exist_ok=True)
    os.makedirs(os.path.join(dst, "tools"), exist_ok=True)
    os.makedirs(os.path.join(dst, "verify"), exist_ok=True)
    shutil.copy(os.path.join(REPO, "tools", "question_rule.py"), os.path.join(dst, "tools"))
    shutil.copy(os.path.join(HERE, "gate_stat.py"), os.path.join(dst, "verify"))

    rule = dict(RULE)
    if bad_rule:
        rule.pop("whitelist")
    json.dump(rule, open(os.path.join(dst, "data", "question_rule.json"), "w", encoding="utf-8"),
              ensure_ascii=False)

    reads, pts = [], []
    for i in range(n_reads):
        t = T0 + datetime.timedelta(minutes=step_min * i)
        pts.append((t, 1000 + i))                      # 单调递增 ⇒ gt 必 HIT、lt 必 MISS
    for t, v in pts:
        reads.append({"read_at": iso(t), "credits": 1, "mkt_silicon_best_buy": v})
    open(os.path.join(dst, "data", "state_reads.jsonl"), "w", encoding="utf-8").write(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in reads) + "\n")

    # 网格：与 gate_stat 用同一个参考实现算出来，保证窗口口径一致
    idx = {t: v for t, v in pts}
    windows = []
    for h in RULE["horizons_hours"]:
        for i, (t, _) in enumerate(pts):
            for t1, _ in pts[i + 1:]:
                if abs((t1 - (t + datetime.timedelta(hours=h))).total_seconds()) <= 15 * 60:
                    windows.append((h, t, t1))
                    break
                if t1 > t + datetime.timedelta(hours=h, minutes=15):
                    break
    windows.sort(key=lambda x: (x[1], x[0]))

    baselines, preds = [], []
    for i, (h, t, t1) in enumerate(windows):
        pgt, plt = p_fn(i) if p_fn else (0.9, 0.1)
        for d, p in (("gt", pgt), ("lt", plt)):
            base_row = {"field": "mkt_silicon_best_buy", "horizon_hours": h, "direction": d,
                        "threshold": 0.0, "window_start": iso(t), "window_end": iso(t1),
                        "written_at": iso(t - datetime.timedelta(minutes=step_min)),
                        "p_base": p_base}
            baselines.append(base_row)
            row = dict(base_row)
            row.pop("p_base")
            row["probability"] = p
            row["prediction_id"] = "syn-%04d-%s" % (i, d)
            preds.append(row)

    if with_baseline:
        open(os.path.join(dst, "data", "sonda_baseline.jsonl"), "w", encoding="utf-8").write(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in baselines) + "\n")
    open(os.path.join(dst, "data", "sonda_predictions.jsonl"), "w", encoding="utf-8").write(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in preds) + "\n")

    dec = {"at": iso(T0), "kind": "batch", "slot": "morning", "trigger_id": "syn",
           "due_count": len(preds), "answered": len(preds)}
    if with_split:
        dec["abstained_self"] = []
        dec["refused_system"] = []
    else:
        dec["abstained"] = 0
        dec["refused"] = 0
    open(os.path.join(dst, "data", "sonda_decisions.jsonl"), "w", encoding="utf-8").write(
        json.dumps(dec, ensure_ascii=False) + "\n")
    return len(windows)


def run(repo):
    env = dict(os.environ, GATE_REPO=repo)
    r = subprocess.run([sys.executable, os.path.join(repo, "verify", "gate_stat.py"), "--json"],
                       capture_output=True, text=True, env=env, timeout=180)
    try:
        return r.returncode, json.loads(r.stdout), (r.stdout or "") + (r.stderr or "")
    except ValueError:
        return r.returncode, None, (r.stdout or "") + (r.stderr or "")


def main():
    bad = 0
    results = []

    def check(name, cond, detail):
        nonlocal bad
        results.append((name, bool(cond), detail))
        if not cond:
            bad += 1

    # ---- 对照：真实台账必须给不出数 ------------------------------------------------
    rc, out, raw = run(REPO)
    check("CONTROL 真实台账 → UNDECIDABLE",
          rc == 2 and out and out["verdict"] == "UNDECIDABLE" and out["stats"]["lower_bound"] is None,
          "rc=%s verdict=%s lower=%s" % (rc, (out or {}).get("verdict"),
                                         (out or {}).get("stats", {}).get("lower_bound")))

    # ---- T：t 分位点表（本工具自算，不用 scipy） ------------------------------------
    known = [(1, 6.3138), (5, 2.0150), (9, 1.8331), (30, 1.6973), (1000, 1.6464)]
    worst = max(abs(G.t_onesided_quantile(0.95, df) - v) for df, v in known)
    check("T 单侧 95% t 分位点 vs 已知值", worst < 5e-3, "最大偏差 %.5f（表: %s）" % (worst, known))

    with tempfile.TemporaryDirectory(prefix="gate-stat-selftest-") as tmp:
        # ---- S1：契约完整 + 我明显优于基线 → 必须 PASS -----------------------------
        d = os.path.join(tmp, "s1")
        nw = build(d, 61, p_fn=lambda i: ((0.9, 0.1) if i % 2 == 0 else (0.7, 0.25)))
        rc, out, raw = run(d)
        check("S1 契约完整/明显优于基线 → PASS",
              rc == 0 and out and out["verdict"] == "PASS" and out["stats"]["lower_bound"] > 0,
              "windows=%d rc=%s verdict=%s lower=%s N0=%s"
              % (nw, rc, (out or {}).get("verdict"),
                 (out or {}).get("stats", {}).get("lower_bound"),
                 (out or {}).get("counts", {}).get("n0")))

        # ---- S2：可评题不足 → UNDECIDABLE，且点名 N0 -------------------------------
        d = os.path.join(tmp, "s2")
        build(d, 7, p_fn=lambda i: (0.9, 0.1))
        rc, out, raw = run(d)
        check("S2 可评题 <10 → UNDECIDABLE(N0)",
              rc == 2 and out and any(r.startswith("N0_BELOW_MIN") for r in out["reasons"]),
              "N0=%s reasons=%s" % ((out or {}).get("counts", {}).get("n0"),
                                    (out or {}).get("reasons")))

        # ---- S3：缺基线台账 → UNDECIDABLE，且点名前置条件① ------------------------
        d = os.path.join(tmp, "s3")
        build(d, 61, with_baseline=False, p_fn=lambda i: (0.9, 0.1))
        rc, out, raw = run(d)
        check("S3 缺基线 p_base → UNDECIDABLE(P1)",
              rc == 2 and out and any(r.startswith("P1_UNMET") for r in out["reasons"]),
              "reasons=%s" % ((out or {}).get("reasons"),))

        # ---- S4：缺弃权/拒题拆分 → UNDECIDABLE，且点名前置条件② --------------------
        d = os.path.join(tmp, "s4")
        build(d, 61, with_split=False, p_fn=lambda i: (0.9, 0.1))
        rc, out, raw = run(d)
        check("S4 缺 abstained_self/refused_system → UNDECIDABLE(P2)",
              rc == 2 and out and any(r.startswith("P2_UNMET") for r in out["reasons"]),
              "reasons=%s" % ((out or {}).get("reasons"),))

        # ---- S5：我与基线同分 → 区间含 0，不给通过 ---------------------------------
        d = os.path.join(tmp, "s5")
        build(d, 61, p_base=0.5, p_fn=lambda i: (0.5, 0.5))
        rc, out, raw = run(d)
        check("S5 d≡0 → UNDECIDABLE(CI_INCLUDES_ZERO)",
              rc == 2 and out and any(r.startswith("CI_INCLUDES_ZERO") for r in out["reasons"]),
              "reasons=%s lower=%s" % ((out or {}).get("reasons"),
                                       (out or {}).get("stats", {}).get("lower_bound")))

        # ---- S6：规则坏 → ERROR（仪器故障，不是一个判断） --------------------------
        d = os.path.join(tmp, "s6")
        build(d, 61, bad_rule=True, p_fn=lambda i: (0.9, 0.1))
        rc, out, raw = run(d)
        check("S6 规则文件坏 → ERROR(exit 3)",
              rc == 3 and out and out["verdict"] == "ERROR",
              "rc=%s errors=%s" % (rc, (out or {}).get("errors")))

    print("gate_stat 自检（%d 项）" % len(results))
    for name, ok, detail in results:
        print("  %-42s %s  %s" % (name, "PASS" if ok else "**没拦住**", detail))
    print()
    if bad:
        print("结论：%d 项没过 —— 这条执行件的可证伪性不成立。" % bad)
        return 1
    print("结论：%d/%d。缺契约就点名缺哪一条（含 CONTROL 那份真实台账），"
          "契约齐全且优势明显时**真的判 PASS** —— 它不是恒真条件。" % (len(results), len(results)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
