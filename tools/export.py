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


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", required=True, help="本机台账目录（含 sonda_*.jsonl / state_reads.jsonl）")
    ap.add_argument("--quiet", action="store_true")
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

    preds = jl(os.path.join(ddir, "sonda_predictions.jsonl"))
    outs = jl(os.path.join(ddir, "sonda_outcomes.jsonl"))
    reads = jl(os.path.join(ddir, "state_reads.jsonl"))

    credits = [r.get("credits") for r in reads if r.get("credits") is not None]
    out_counts = {}
    for o in outs:
        k = o.get("outcome", "?")
        out_counts[k] = out_counts.get(k, 0) + 1

    state["counts"] = {
        "predictions": len(preds),
        "outcomes": len(outs),
        "outcomes_by_verdict": out_counts,
        "state_reads": len(reads),
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

    if not args.quiet:
        print("exported_at=%s" % state["exported_at"])
        print("counts=%s" % json.dumps(state["counts"], ensure_ascii=False))
        print("newest=%s" % json.dumps(state["newest"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
