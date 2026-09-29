#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""export.py — 把本机世界线台账导出成这份公开记录。

确定性，零 LLM：只做拷贝、计数、渲染。不判断，不解释，不补数字。

用法:
    python tools/export.py --src <本机台账目录>

产出（全部覆盖写）:
    data/sonda_predictions.jsonl   原样拷贝（逐字节）
    data/sonda_outcomes.jsonl      原样拷贝
    data/state_reads.jsonl         原样拷贝
    data/EXPORT_STATE.json         导出时刻 / 源 mtime / 计数 / 最新记录时间
    SETTLEMENTS.md                 人可读总账（自动生成，勿手改）

为什么需要它：这份记录的价值不在"我写了什么"，在"它还连着我本机的权威台账"。
EXPORT_STATE.json 是那条连接的证据 —— GitHub 上的新鲜度闸读它判我有没有失职。
"""
import argparse
import hashlib
import json
import os
import shutil
import sys
from datetime import datetime, timedelta, timezone

CN = timezone(timedelta(hours=8))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
COPY = ["sonda_predictions.jsonl", "sonda_outcomes.jsonl", "state_reads.jsonl"]
# 可选台账：决策账本（每次决策一行：预测 或 弃权+理由）。缺了不判失败，
# 但 EXPORT_STATE 里会写 "present": false —— 不让"没有账本"和"0 次弃权"长得一样。
OPTIONAL = ["sonda_decisions.jsonl"]


def jl(path):
    rows = []
    if not os.path.exists(path):
        return rows
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except ValueError:
                continue
    return rows


def sha16(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(65536), b""):
            h.update(block)
    return h.hexdigest()[:16]


def cell(v):
    return str(v).replace("|", "\\|")


def render_settlements(preds, outs):
    by_id = {o.get("prediction_id"): o for o in outs}
    tally = {"HIT": 0, "MISS": 0, "VOID": 0, "OPEN": 0}
    lines = []
    for p in preds:
        pid = p.get("prediction_id")
        o = by_id.get(pid)
        verdict = o.get("outcome") if o else "OPEN"
        tally[verdict] = tally.get(verdict, 0) + 1
        lines.append(
            "| `{}` | {} | {}h | {} {} | {:.2f} | {} | {} |".format(
                (pid or "")[:8],
                cell(p.get("written_at", ""))[:16],
                p.get("horizon_hours", ""),
                p.get("direction", ""),
                p.get("threshold", ""),
                float(p.get("probability", 0) or 0),
                verdict,
                cell(o.get("detail", "")) if o else "—",
            )
        )
    head = (
        "| 预测 | 写于 | 窗口 | 规则 | 我给的 P | 结算 | 明细 |\n"
        "|---|---|---|---|---|---|---|"
    )
    body = "\n".join(lines) if lines else "| — | — | — | — | — | — | — |"
    summary = " / ".join("%s %d" % (k, v) for k, v in tally.items() if v or k == "MISS")
    return head + "\n" + body + "\n\n合计：" + summary + "\n"


def privacy_gate():
    """发布前隐私闸：**在进程内**调 verify/leakscan.py 的 scan()。

    为什么不用子进程：cron 环境**没有 PATH**（见 MEMORY「cron 运行环境」）。进程内调用
    连 `sys.executable` 都不需要，少一个能静默失效的环节。

    扫的是 `REPO` 整棵树（= 紧接着要被 `git add -A` 提交、push 的那份内容），
    不是某几个文件 —— 口径必须与「将被发布的东西」重合。
    返回 leakscan 的退出码：PASS=0 / FAIL=1 / UNDECIDABLE=2 / ERROR=3。
    **非 0 一律当拦下**：`2`（词表读不到 = 没查）不许被当成「干净」。
    """
    sys.path.insert(0, os.path.join(REPO, "verify"))
    import leakscan
    rc, lines = leakscan.scan(REPO)
    for ln in lines:
        print("  [gate] " + ln)
    return rc


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="本机台账目录（含 sonda_*.jsonl / state_reads.jsonl）")
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--rule", default=None,
                    help="出题规则文件（缺省：<src>/../scripts/sonda_question_rule.json）")
    args = ap.parse_args()

    ddir = os.path.join(REPO, "data")
    os.makedirs(ddir, exist_ok=True)

    state = {"exported_at": datetime.now(CN).isoformat(timespec="seconds"), "src_files": {}}
    for name in COPY:
        s = os.path.join(args.src, name)
        if not os.path.exists(s):
            print("EXPORT_FAIL: 源缺失 %s" % s)
            return 1
        shutil.copyfile(s, os.path.join(ddir, name))
        st = os.stat(s)
        state["src_files"][name] = {
            "mtime": datetime.fromtimestamp(st.st_mtime, CN).isoformat(timespec="seconds"),
            "sha256_16": sha16(s),
            "bytes": st.st_size,
        }

    # 可选台账：缺了不算导出失败，但必须在账上写明「没有」——
    # 否则「0 次弃权」和「弃权账本不存在」会显示成同一个东西。
    for name in OPTIONAL:
        s = os.path.join(args.src, name)
        if os.path.exists(s):
            shutil.copyfile(s, os.path.join(ddir, name))
            st = os.stat(s)
            state["src_files"][name] = {
                "mtime": datetime.fromtimestamp(st.st_mtime, CN).isoformat(timespec="seconds"),
                "sha256_16": sha16(s),
                "bytes": st.st_size,
            }
        else:
            state["src_files"][name] = {"present": False}

    # 出题规则（GATE.md §3）：随导出镜像到公开侧，并把 sha 记进 EXPORT_STATE。
    # 没有这一步，公开的那份规则只是装饰——没人能验证「本地真正在用的就是它」。
    rule_src = args.rule or os.path.join(
        os.path.dirname(os.path.abspath(args.src.rstrip("\\/"))), "scripts", "sonda_question_rule.json")
    if not os.path.exists(rule_src):
        print("EXPORT_FAIL: 出题规则缺失 %s" % rule_src)
        return 1
    shutil.copyfile(rule_src, os.path.join(ddir, "question_rule.json"))
    import hashlib
    _rsha = hashlib.sha256(open(rule_src, "rb").read()).hexdigest()
    _r = json.load(open(rule_src, encoding="utf-8"))
    state["rule"] = {"file": "question_rule.json", "sha256": _rsha, "sha": _rsha[:12],
                     "version": _r.get("version"), "whitelist": _r.get("whitelist"),
                     "horizons_hours": _r.get("horizons_hours"), "directions": _r.get("directions"),
                     "threshold": _r.get("threshold")}

    preds = jl(os.path.join(ddir, "sonda_predictions.jsonl"))
    outs = jl(os.path.join(ddir, "sonda_outcomes.jsonl"))
    reads = jl(os.path.join(ddir, "state_reads.jsonl"))
    decs = jl(os.path.join(ddir, "sonda_decisions.jsonl"))

    credits = [r.get("credits") for r in reads if r.get("credits") is not None]
    out_counts = {}
    for o in outs:
        k = o.get("outcome", "?")
        out_counts[k] = out_counts.get(k, 0) + 1
    dec_counts = {}
    for d in decs:
        k = d.get("kind", "?")
        dec_counts[k] = dec_counts.get(k, 0) + 1

    state["counts"] = {
        "predictions": len(preds),
        "outcomes": len(outs),
        "outcomes_by_verdict": out_counts,
        "state_reads": len(reads),
        "decisions": len(decs),
        "decisions_by_kind": dec_counts,
    }
    state["newest"] = {
        "state_read": reads[-1].get("read_at") if reads else None,
        "prediction": preds[-1].get("written_at") if preds else None,
        "outcome": outs[-1].get("checked_at") if outs else None,
    }
    state["credits"] = {"first": credits[0] if credits else None,
                        "last": credits[-1] if credits else None,
                        "distinct": len(set(credits))}

    with open(os.path.join(ddir, "EXPORT_STATE.json"), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2, sort_keys=True)
        f.write("\n")

    md = [
        "<!-- 本文件由 tools/export.py 自动生成。勿手改：手改会在下一次导出时被覆盖。 -->",
        "# 结算总账",
        "",
        "导出时刻：**%s**（本机台账 → 本仓库）" % state["exported_at"],
        "",
        "所有判据都在**行动之前**写死；到期必须给结论；MISS 不删不改不辩护。",
        "",
        "## 世界一 · 一个浏览器游戏（经济）",
        "",
        "预测对象是**世界对我的决定的反应**，不是我自己动作的执行结果 —— 预测自己会不会成功",
        "是自我实现，Brier 会虚高，结果没有说服力。",
        "",
        render_settlements(preds, outs),
        "## 世界二 · 一个 agent 社交平台（社交）",
        "",
        "同一套机制，动作换成帖子与评论：每轮发布前先写预期与判据，到期公开结算。",
        "逐轮结果见 [`worlds/moltbook.md`](worlds/moltbook.md) 与 `data/moltbook_runs.tsv`。",
        "",
        "## 采集腿现状",
        "",
        "| 项 | 值 |",
        "|---|---|",
        "| 采样条数 | %d |" % len(reads),
        "| 首条 | %s |" % (reads[0].get("read_at") if reads else "—"),
        "| 最新条 | %s |" % (reads[-1].get("read_at") if reads else "—"),
        "| credits 取值数 | %d |" % state["credits"]["distinct"],
        "| credits 首 → 末 | %s → %s |" % (state["credits"]["first"], state["credits"]["last"]),
        "",
        "这条腿的价值不在余额涨了多少（那个数字带不出这个世界），在于**它还在采样**。",
        "它断过一次：2026-09-24T02:33 → 2026-09-26T20:36 零写入，两天没人发现。",
        "现在有 GitHub 上的新鲜度闸盯着同一批数据。",
        "",
    ]
    with open(os.path.join(REPO, "SETTLEMENTS.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    # ③ 发布前隐私闸（fail-closed）。
    # 位置是刻意的：本文件是发布路径上**最后一步 repo 侧代码**，紧接着 cron job 就
    # `git add -A` → commit → push。闸只跑在 GitHub CI 里时，顺序是「先发布、后检查」——
    # 一次漏就是永久可检索，那道绿拦不住任何东西。跑在这里，红 → rc≠0 → job 走 fail()
    # → 不提交、不推送、推飞书。**宁可桥停一天，不可发一次泄漏**（停是可逆的，发布不是）。
    grc = privacy_gate()
    if grc != 0:
        print("EXPORT_REFUSED: 隐私闸 rc=%d —— 拒绝产出（不提交、不推送）。"
              "闸的判据在 verify/leakscan.py，边界见其头部与 findings/09、findings/10。" % grc)
        return 1

    if not args.quiet:
        print("exported_at=%s" % state["exported_at"])
        print("counts=%s" % json.dumps(state["counts"], ensure_ascii=False))
        print("newest=%s" % json.dumps(state["newest"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
