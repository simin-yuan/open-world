#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""question_rule.py — 出题规则的参考实现（确定性，零 LLM）。

这是 GATE.md §3 那套规则的**可执行版本**：给定导出的 state_reads.jsonl，
列出「按规则应当存在的全部题目」。任何人都能拿它复算我的题目集。

为什么要有它：光写「题目由规则穷举」是口号。只有当规则能被别人**跑出来**、
并与我实际发布的预测一一对照时，「不许挑题」才是可验证的。

用法：
    python tools/question_rule.py                    # 打印题目集与计数
    python tools/question_rule.py --json             # 输出 JSON（便于对账）
    python tools/question_rule.py --preds data/sonda_predictions.jsonl   # 与已发布预测对账
"""
import argparse
import datetime
import json
import os

# ── 规则（改这里 = 改判据，会留下提交记录）──────────────────────────────
WHITELIST = ["mkt_silicon_best_buy"]   # 只有世界侧读数可进；自身账户字段一律不算
HORIZONS = [3.0, 6.0, 12.0]            # 小时
DIRECTIONS = ["gt", "lt"]              # delta 与阈值比
THRESHOLD = 0.0                        # 固定，不许挑
TOL_MIN = 15                           # 找配对点时允许的时间偏差（分钟）
SELF_FIELDS = ["credits", "credits_earned", "credits_spent", "implied_credits",
               "cargo_kinds", "poi", "docked_at", "system", "offset", "player_id"]

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def parse(ts):
    try:
        return datetime.datetime.fromisoformat(ts)
    except (TypeError, ValueError):
        return None


def windows_for(rows, field, hours):
    """返回该字段在该视界上的全部可比窗口 [(t0, t1), ...]。"""
    pts = [(parse(r.get("read_at")), r.get(field)) for r in rows]
    pts = [(t, v) for (t, v) in pts if t and v is not None]
    out = []
    for i, (t0, _) in enumerate(pts):
        target = t0 + datetime.timedelta(hours=hours)
        for (t1, _) in pts[i + 1:]:
            if abs((t1 - target).total_seconds()) <= TOL_MIN * 60:
                out.append((t0, t1))
                break
            if t1 > target + datetime.timedelta(minutes=TOL_MIN):
                break
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--reads", default=os.path.join(REPO, "data", "state_reads.jsonl"))
    ap.add_argument("--preds", default=None, help="与已发布预测对账")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    rows = [json.loads(l) for l in open(a.reads, encoding="utf-8") if l.strip()]
    questions, report = [], []
    for f in WHITELIST:
        have = sum(1 for r in rows if r.get(f) is not None)
        if f in SELF_FIELDS:
            report.append("%s: **违规**（自身动作镜像，不许进白名单）" % f)
            continue
        for h in HORIZONS:
            ws = windows_for(rows, f, h)
            n = len(ws) * len(DIRECTIONS)
            report.append("%s @%gh: 读数 %d 条 / 合格窗口 %d / 应出题 %d"
                          % (f, h, have, len(ws), n))
            for (t0, t1) in ws:
                for d in DIRECTIONS:
                    questions.append({
                        "field": f, "horizon_hours": h, "direction": d,
                        "threshold": THRESHOLD,
                        "window_start": t0.isoformat(timespec="seconds"),
                        "window_end": t1.isoformat(timespec="seconds"),
                    })

    if a.json:
        print(json.dumps({"whitelist": WHITELIST, "horizons": HORIZONS,
                          "directions": DIRECTIONS, "threshold": THRESHOLD,
                          "n_questions": len(questions), "questions": questions},
                         ensure_ascii=False, indent=1))
        return 0

    print("出题规则（GATE.md §3）· 读数 %d 条" % len(rows))
    for r in report:
        print("  " + r)
    print("规则应出题总数：%d" % len(questions))

    if a.preds:
        preds = [json.loads(l) for l in open(a.preds, encoding="utf-8") if l.strip()]
        grid = {(q["field"], q["horizon_hours"], q["direction"], q["threshold"]) for q in questions}
        off, self_ref = [], []
        for p in preds:
            key = (p.get("field"), p.get("horizon_hours"), p.get("direction"), p.get("threshold"))
            if p.get("field") in SELF_FIELDS:
                self_ref.append("%s field=%s" % (p["prediction_id"][:12], p.get("field")))
            elif key not in grid:
                off.append("%s %s" % (p["prediction_id"][:12], key))
        print("\n对账已发布预测 %d 条：" % len(preds))
        print("  押在自身字段上（规则外）：%d %s" % (len(self_ref), self_ref))
        print("  不在规则网格内：%d %s" % (len(off), off))
        print("  ⇒ 结论：%s" % ("全部合规" if not self_ref and not off
                                else "存在规则外题目 —— 该批预测不能用于达标判定"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
