#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check.py — 外部判据：这份记录还连着本机吗？账本有没有撒谎？

这里刻意不做「我说我健康」的自评。三条检查全部只读磁盘上的文件，
任何人在任何机器上跑出来的结果都一样。非零退出 = 记录不该被当成活的。

    python verify/check.py            # 本地
    （CI 里由 .github/workflows/freshness.yml 每 6 小时跑一次）

阈值为什么是这些数：
  - 导出腿 36h：我每日本该导出一次；超过 36h 说明桥断了，不是世界安静了。
  - 采集腿 6h 硬线 / 3h 软线：采样设计频率 30 分钟。断 6 小时 = 12 个采样点没了。
    2026-09-24 那次断流是 55 小时。这个数不提速，只要求"有人知道"。
  - 逾期未结算 3h 宽限：到期后给结算留一个窗口，超过就该有结论。
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

CN = timezone(timedelta(hours=8))
# 默认查本仓库；CHECK_REPO 用于 verify/selftest.py 把判据指向人造的坏样本 ——
# 「这条闸能不能说不」必须能被证明，不能被声称。
REPO = os.environ.get("CHECK_REPO") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
EXPORT_MAX_H = 36
READ_FAIL_H = 6
READ_WARN_H = 3
OVERDUE_GRACE_H = 3

fails, warns = [], []


def load(name):
    p = os.path.join(REPO, "data", name)
    if not os.path.exists(p):
        fails.append("data/%s 不存在" % name)
        return []
    rows = []
    for line in open(p, encoding="utf-8"):
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
    return rows


def age_h(ts):
    if not ts:
        return None
    try:
        return (datetime.now(CN) - datetime.fromisoformat(ts)).total_seconds() / 3600.0
    except ValueError:
        return None


def main():
    now = datetime.now(CN)

    # ① 导出腿：这份记录是不是还在连着我本机的台账
    sp = os.path.join(REPO, "data", "EXPORT_STATE.json")
    if not os.path.exists(sp):
        fails.append("[导出腿] data/EXPORT_STATE.json 不存在 —— 桥没接上")
        state = {}
    else:
        state = json.load(open(sp, encoding="utf-8"))
        h = age_h(state.get("exported_at"))
        print("[导出腿] exported_at=%s (%.1fh 前)" % (state.get("exported_at"), h or -1))
        if h is None or h > EXPORT_MAX_H:
            fails.append("[导出腿] 导出已停 %.1fh（上限 %dh）" % (h or -1, EXPORT_MAX_H))

    # ② 采集腿：世界一侧的观测还在不在累积
    reads = load("state_reads.jsonl")
    if reads:
        h = age_h(reads[-1].get("read_at"))
        print("[采集腿] %d 条，最新 %s (%.1fh 前)" % (len(reads), reads[-1].get("read_at"), h or -1))
        if h is None or h > READ_FAIL_H:
            fails.append("[采集腿] 最新观测已 %.1fh 前（硬线 %dh）" % (h or -1, READ_FAIL_H))
        elif h > READ_WARN_H:
            warns.append("[采集腿] 最新观测 %.1fh 前（软线 %dh）" % (h, READ_WARN_H))
    else:
        print("[采集腿] 无数据")

    # ③ 结算腿：到期了就必须有结论，不许悬着
    preds = load("sonda_predictions.jsonl")
    outs = load("sonda_outcomes.jsonl")
    settled = set(o.get("prediction_id") for o in outs)
    overdue = []
    for p in preds:
        if p.get("prediction_id") in settled:
            continue
        due = None
        try:
            due = datetime.fromisoformat(p["written_at"]) + timedelta(hours=float(p["horizon_hours"]))
        except (KeyError, ValueError, TypeError):
            continue
        if now - due > timedelta(hours=OVERDUE_GRACE_H):
            overdue.append((p.get("prediction_id"), due.isoformat(timespec="minutes")))
    print("[结算腿] %d 条预测 / %d 条已结算 / %d 条逾期未结算" % (len(preds), len(outs), len(overdue)))
    if overdue:
        fails.append("[结算腿] 逾期未结算 %d 条：%s" % (len(overdue), overdue[:5]))

    # ④ 账本自洽：写下的数字必须等于实际条数
    if state:
        c = state.get("counts", {})
        if c.get("predictions") != len(preds):
            fails.append("[自洽] EXPORT_STATE 说 %s 条预测，实际 %d 条"
                         % (c.get("predictions"), len(preds)))
        if c.get("state_reads") != len(reads):
            fails.append("[自洽] EXPORT_STATE 说 %s 条采样，实际 %d 条"
                         % (c.get("state_reads"), len(reads)))

    for w in warns:
        print("WARN  %s" % w)
    for f in fails:
        print("FAIL  %s" % f)
    if fails:
        print("\n结论：这份记录当前不可当活的用（%d 条 FAIL）。" % len(fails))
        return 1
    print("\n结论：三条腿都在（%d 条 WARN）。" % len(warns))
    return 0


if __name__ == "__main__":
    sys.exit(main())
