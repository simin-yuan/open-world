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

    # ④ 决策腿活性：没有新判断 ≠ 一切正常。
    # 这条腿是外脑 2026-09-26 指出后补的。原三条腿里结算腿只看「到期未结」，
    # 于是**只要不再产生新预测，结算腿永远不会红** —— 闸会以「空转」的方式全绿通过
    # （徽章 passing 曾经就是这样来的）。判据取自 MEMORY「报警器失效盲区」：
    # 巡检查「最近有没有新写入」，不是查文件存在。
    DECISION_MAX_H = 24
    decs = load("sonda_decisions.jsonl")
    last_dec = decs[-1].get("at") if decs else None
    last_pred = preds[-1].get("written_at") if preds else None
    cand = [x for x in (last_dec, last_pred) if x]
    h = age_h(max(cand)) if cand else None
    print("[决策腿] %d 行决策 / 最近落账 %s (%s)"
          % (len(decs), max(cand) if cand else "无",
             ("%.1fh 前" % h) if h is not None else "取不到"))
    if h is None or h > DECISION_MAX_H:
        fails.append("[决策腿] 决策账本已 %s 没有新行（硬线 %dh）—— 预测腿可能死了，"
                     "而结算腿对这种情况是瞎的"
                     % (("%.1fh" % h) if h is not None else "??", DECISION_MAX_H))

    # ⑤ 账本自洽：写下的数字必须等于实际条数
    if state:
        c = state.get("counts", {})
        if c.get("predictions") != len(preds):
            fails.append("[自洽] EXPORT_STATE 说 %s 条预测，实际 %d 条"
                         % (c.get("predictions"), len(preds)))
        if c.get("state_reads") != len(reads):
            fails.append("[自洽] EXPORT_STATE 说 %s 条采样，实际 %d 条"
                         % (c.get("state_reads"), len(reads)))
        if c.get("decisions") != len(decs):
            fails.append("[自洽] EXPORT_STATE 说 %s 行决策，实际 %d 行"
                         % (c.get("decisions"), len(decs)))

    # ⑥ 规则漂移：公开的规则必须就是本地真正在用的那一份。
    # 判据：EXPORT_STATE.rule.sha256 == data/question_rule.json 的实际 sha256，
    # 且最近一条带指纹的决策行必须记着同一个 sha。
    # 没有这条，GATE.md §3 里那份「公开且固定」的规则只是装饰。
    import hashlib as _hl
    rule = (state or {}).get("rule")
    if not rule:
        warns.append("[规则] EXPORT_STATE 没有 rule 段 —— 无法核对公开规则是否即本地在用")
    else:
        rf = os.path.join(REPO, "data", rule.get("file", "question_rule.json"))
        if not os.path.exists(rf):
            fails.append("[规则] 公开规则文件缺失 %s" % os.path.basename(rf))
        else:
            got = _hl.sha256(open(rf, "rb").read()).hexdigest()
            print("[规则] 公开副本 sha=%s / 导出记录 sha=%s"
                  % (got[:12], str(rule.get("sha256"))[:12]))
            if got != rule.get("sha256"):
                fails.append("[规则] 公开规则被改过（实际 sha 与导出记录不符）—— 规则不再是固定物")
        stamped = [d for d in decs if d.get("rule_sha256")]
        if stamped:
            if str(stamped[-1]["rule_sha256"])[:12] != str(rule.get("sha"))[:12]:
                fails.append("[规则] 本地最近一次判定用的规则指纹 %s ≠ 公开规则 %s"
                             " —— 本地改了规则、公开侧没跟上"
                             % (stamped[-1]["rule_sha256"], rule.get("sha")))
            else:
                print("[规则] 本地判定指纹与公开规则一致（%s）" % rule.get("sha"))
        else:
            warns.append("[规则] 尚无带规则指纹的决策行 —— 落一次预测/拒绝之后这条才有牙齿")

    # ⑦ 批次完整性：每一批「到期应出的题」都必须每一道都有处置。
    # 弃权（abstained）是判断结果，漏答（omitted）是漏 —— 两者分开记。
    # 没有这条，「网格内少报」在账面上是看不见的。
    batches = [d for d in decs if d.get("kind") == "batch"]
    if not batches:
        warns.append("[批次] 还没有批次行——第一轮预测落账后这条才开始有牙齿")
    else:
        bad = [b for b in batches if (b.get("missing") or []) or (b.get("omitted") or [])
               or (b.get("off_rule") or [])]
        for b in bad:
            fails.append("[批次] %s 不完整：due=%s answered=%s abstained=%s omitted=%s missing=%s off_rule=%s"
                         % (b.get("at"), b.get("due_count"), b.get("answered"), b.get("abstained"),
                            b.get("omitted"), b.get("missing"), b.get("off_rule")))
        import datetime as _dt
        try:
            newest = max(_dt.datetime.fromisoformat(str(b.get("at")).replace("Z", "+00:00"))
                         for b in batches)
            b_age_h = (_dt.datetime.now(newest.tzinfo) - newest).total_seconds() / 3600.0
            last = batches[-1]
            print("[批次] 共 %d 批，最新 %.1fh 前：due=%s answered=%s abstained=%s"
                  % (len(batches), b_age_h, last.get("due_count"), last.get("answered"),
                     last.get("abstained")))
            if b_age_h > 36:
                fails.append("[批次] 最新批次行已 %.1fh 前（>36h）—— 决策链又停了" % b_age_h)
        except Exception as e:
            warns.append("[批次] 时间戳解析失败：%s" % str(e)[:80])
        if not bad:
            print("[批次] 每一批都完整（无漏答、无越界）")

    for w in warns:
        print("WARN  %s" % w)
    for f in fails:
        print("FAIL  %s" % f)
    if fails:
        print("\n结论：这份记录当前不可当活的用（%d 条 FAIL）。" % len(fails))
        return 1
    print("\n结论：四条腿都在（%d 条 WARN）。" % len(warns))
    return 0


if __name__ == "__main__":
    sys.exit(main())
