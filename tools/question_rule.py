#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""question_rule.py — 出题规则的复算器（确定性，零 LLM）。

规则**不写在这个文件里**。它读 `data/question_rule.json` —— 本机门
（sonda_question_queue.py）真正在用的那一份，由导出原样镜像过来。
所以任何人复算出来的题目集，就是我的门判定的题目集；两者一旦不同步，
`verify/check.py` 的第 ⑥ 条腿会红。规则本体见 GATE.md §3（已签 2026-09-26）。

两种视图，别混：
  --due-now   当前窗口「到期应出」的题（= 门判定的那一格，窗口终点取最新读数）
  （默认）    整份记录里规则会产生的全部题目（= 审计视图，用来核我发过什么）

用法：
    python tools/question_rule.py                                    # 全历史题目集
    python tools/question_rule.py --due-now                          # 当前窗口应出的题
    python tools/question_rule.py --reads <本机台账>                 # 换一份读数复算
    python tools/question_rule.py --preds data/sonda_predictions.jsonl   # 与已发布预测对账
"""
import argparse
import datetime
import json
import os

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_rule(path):
    r = json.load(open(path, encoding="utf-8"))
    for k in ("whitelist", "horizons_hours", "directions", "threshold", "tol_minutes", "self_fields"):
        if k not in r:
            raise ValueError("RULE_MISSING_KEY %s" % k)
    bad = [f for f in r["whitelist"] if f in r["self_fields"]]
    if bad:
        # 自身动作镜像进了白名单 = 判据自我实现，直接拒载
        raise ValueError("RULE_SELF_FIELD_IN_WHITELIST %s" % bad)
    return r


def parse(ts):
    try:
        return datetime.datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


def read_rows(path):
    out = []
    for line in open(path, encoding="utf-8"):
        if not line.strip():
            continue
        r = json.loads(line)
        t = parse(r.get("read_at"))
        if t:
            out.append((t, r))
    out.sort(key=lambda x: x[0])
    return out


def _points(rows, field):
    return [(t, r.get(field)) for t, r in rows if r.get(field) is not None]


def windows_for(rows, field, hours, tol_min):
    """该字段在该视界上的全部可比窗口 [(t0, t1), ...]。"""
    pts = _points(rows, field)
    out = []
    for i, (t0, _) in enumerate(pts):
        target = t0 + datetime.timedelta(hours=hours)
        for (t1, _) in pts[i + 1:]:
            if abs((t1 - target).total_seconds()) <= tol_min * 60:
                out.append((t0, t1))
                break
            if t1 > target + datetime.timedelta(minutes=tol_min):
                break
    return out


def all_windows_grid(rows, rule):
    """整份记录里，规则会产生的全部题目。"""
    grid = []
    for f in rule["whitelist"]:
        for h in rule["horizons_hours"]:
            for (t0, t1) in windows_for(rows, f, h, rule["tol_minutes"]):
                for d in rule["directions"]:
                    grid.append({"field": f, "horizon_hours": float(h), "direction": d,
                                 "threshold": float(rule["threshold"]),
                                 "window_start": t0.isoformat(timespec="seconds"),
                                 "window_end": t1.isoformat(timespec="seconds")})
    return grid


def due_now_grid(rows, rule):
    """当前窗口到期应出的题（门的语义）：窗口终点 = 最新读数。"""
    if not rows:
        return []
    t_end = rows[-1][0]
    tol = datetime.timedelta(minutes=rule["tol_minutes"])
    grid = []
    for f in rule["whitelist"]:
        if rows[-1][1].get(f) is None:
            continue
        for h in rule["horizons_hours"]:
            target = t_end - datetime.timedelta(hours=h)
            if not any(abs(t - target) <= tol and r.get(f) is not None for t, r in rows):
                continue
            for d in rule["directions"]:
                grid.append({"field": f, "horizon_hours": float(h), "direction": d,
                             "threshold": float(rule["threshold"])})
    return grid


def key_of(q):
    return (str(q.get("field")), float(q.get("horizon_hours") or 0), str(q.get("direction")),
            float(q.get("threshold") if q.get("threshold") is not None else 0.0))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--rule", default=os.path.join(REPO, "data", "question_rule.json"))
    ap.add_argument("--reads", default=os.path.join(REPO, "data", "state_reads.jsonl"))
    ap.add_argument("--preds", default=None, help="与已发布预测对账")
    ap.add_argument("--due-now", action="store_true", help="只看当前窗口应出的题（门的语义）")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    rule = load_rule(a.rule)
    rows = read_rows(a.reads)
    grid = due_now_grid(rows, rule) if a.due_now else all_windows_grid(rows, rule)

    if a.json:
        print(json.dumps({"rule": rule, "reads": len(rows),
                          "view": "due-now" if a.due_now else "all-windows",
                          "n_questions": len(grid), "questions": grid},
                         ensure_ascii=False, indent=1))
        return 0

    print("出题规则 v%s（data/question_rule.json，即本机门在用的那一份）" % rule.get("version"))
    print("  白名单 %s · 视界 %s h · 方向 %s · 阈值 %s · 容差 %s 分钟"
          % (rule["whitelist"], rule["horizons_hours"], rule["directions"],
             rule["threshold"], rule["tol_minutes"]))
    print("读数 %d 条 · 视图=%s · 题目数 %d"
          % (len(rows), "到期(当前窗口)" if a.due_now else "全历史", len(grid)))
    for g in grid[:12]:
        print("  %s @%gh %s thr=%s %s" % (g["field"], g["horizon_hours"], g["direction"], g["threshold"],
                                          (g.get("window_end") or "")))
    if len(grid) > 12:
        print("  …（共 %d 道）" % len(grid))
    if not grid:
        print("  0 道：世界侧字段两端可比读数不足。这不是失败，是样本还没到。")

    if a.preds:
        preds = [json.loads(l) for l in open(a.preds, encoding="utf-8") if l.strip()]
        ref = all_windows_grid(rows, rule)
        gk = {key_of(g) for g in ref}
        rule_ok = {(f, float(h), d, float(rule["threshold"]))
                   for f in rule["whitelist"] for h in rule["horizons_hours"] for d in rule["directions"]}
        self_ref, off = [], []
        for p in preds:
            k = key_of(p)
            if k[0] in rule["self_fields"]:
                self_ref.append("%s field=%s" % (str(p.get("prediction_id"))[:12], p.get("field")))
            elif k not in rule_ok or (k not in gk and k not in rule_ok):
                off.append("%s %s" % (str(p.get("prediction_id"))[:12], k))
        print("\n对账已发布预测 %d 条（参照 全历史窗口）：" % len(preds))
        print("  押在自身字段上（规则外）：%d %s" % (len(self_ref), self_ref))
        print("  不在规则网格内：%d %s" % (len(off), off))
        print("  ⇒ %s" % ("全部合规" if not self_ref and not off
                           else "存在规则外题目 —— 该批预测不能用于达标判定"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
