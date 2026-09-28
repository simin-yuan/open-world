#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selftest.py — 证明这条闸**能说不**，并且在干净输入上**说得出「通过」**。

一个判据如果从来没被观察到拒绝过任何东西，它就不是判据，是装饰。
所以这里不测"check.py 会通过"——那件事毫无信息量。这里造七种**已知的坏**，
逐个喂给 check.py，要求它每一条都报 FAIL。

七种坏样本（都建在**自造的**干净样本上，一处只坏一条腿）：
  A 导出腿停摆    把 exported_at 改成 48 小时前
  B 采集腿断流    把最后一条观测改成 9 小时前
  C 结算腿逾期    把一条已结算预测的结算记录删掉
  D 决策腿假死    把最后一行决策改成 30 小时前
  E 账本不自洽    把 EXPORT_STATE 里的条数改错
  F 规则漂移      把公开的 question_rule.json 改掉（sha 对不上）
  G 批次漏答      追加一批「到期 6 道只处置 5 道」
另加一个对照：**自造的**干净样本必须通过。

    python verify/selftest.py

--------------------------------------------------------------------
2026-09-29 修：对照样本必须**自造**，不能是 live 台账的副本
--------------------------------------------------------------------
旧写法把「干净副本」定义成**当前盘上 data/ 的拷贝**。于是 live 台账一陈旧，
对照跟着红 —— 而脚本把原因报成「本脚本或 check.py 坏了」。两处后果：

  ① **误判归因**：红的是 live 数据的新鲜度，被写成了判据脚本坏了。
  ② **把真判据挡在门外**：CI（.github/workflows/freshness.yml）里本脚本是**第一步**，
     它红了后面 `verify/check.py` 就不跑（GitHub Actions 默认：一步失败即终止该 job）——
     于是「四条腿到底怎么样」在 CI 日志里永远看不到，只看到一句栽赃。

一个跟着被测对象一起沉的对照不是对照。所以：
  · 控制组 = `build_clean()`，**按 check.py 的契约现造**（时间戳现取、条数自洽、规则 sha 对齐）。
    必须**每次重建**：写成只读快照的话，它自己会变陈旧，落进同一形态。
  · 七个坏样本也都建在它上面 —— 一处只坏一条腿，噪声不再混进来。
  · live 台账另外单独跑一次，**只作观测**（红 = 数据陈旧，不判本脚本/check.py），不计分。

契约（改 check.py 的任何一条腿，就要同步改 `build_clean`）：
  data/EXPORT_STATE.json       exported_at 新鲜；counts 与实际条数一致；rule.sha256 == 规则文件 sha
  data/state_reads.jsonl       非空，末条 read_at 新鲜
  data/sonda_predictions.jsonl 每条都在 sonda_outcomes.jsonl 里有结算
  data/sonda_decisions.jsonl   非空，且含一条完整批次行（missing/omitted/off_rule 皆空）
  data/question_rule.json      其 sha256 被写进 EXPORT_STATE.rule
"""
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

CN = timezone(timedelta(hours=8))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
HERE = os.path.dirname(os.path.abspath(__file__))


def _iso(dt):
    return dt.isoformat(timespec="seconds")


def _write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def build_clean(dst):
    """按 check.py 的契约造一份「按构造合法」的台账。时间戳一律**现取**。"""
    now = datetime.now(CN)
    data = os.path.join(dst, "data")
    os.makedirs(data, exist_ok=True)

    rule_obj = {"_note": "selftest 自造样本，不是 GATE.md §3 那份规则",
                "version": 1, "whitelist": ["selftest_subject"],
                "horizons_hours": [1.0, 6.0], "directions": ["gt", "lt"], "threshold": 0.0}
    rule_bytes = json.dumps(rule_obj, ensure_ascii=False, indent=2).encode("utf-8")
    with open(os.path.join(data, "question_rule.json"), "wb") as f:
        f.write(rule_bytes)
    rule_sha = hashlib.sha256(rule_bytes).hexdigest()

    reads = [{"read_at": _iso(now - timedelta(minutes=30)), "n": 1},
             {"read_at": _iso(now), "n": 2}]
    # 预测故意写老（32h）+ 已结算：这样 D 样例把决策行改成 30h 前时，max() 落在它上面。
    preds = [{"prediction_id": "p-selftest-0", "written_at": _iso(now - timedelta(hours=32)),
              "horizon_hours": 1.0}]
    outs = [{"prediction_id": "p-selftest-0", "at": _iso(now - timedelta(hours=31)), "verdict": "HIT"}]
    decs = [{"at": _iso(now - timedelta(hours=1)), "kind": "abstain", "rule_sha256": rule_sha,
             "prediction_id": None},
            {"at": _iso(now), "kind": "batch", "slot": "selftest", "trigger_id": "t-selftest-clean",
             "due_count": 4, "answered": 4, "abstained": 0, "refused": 0,
             "omitted": [], "missing": [], "off_rule": []}]

    _write_jsonl(os.path.join(data, "state_reads.jsonl"), reads)
    _write_jsonl(os.path.join(data, "sonda_predictions.jsonl"), preds)
    _write_jsonl(os.path.join(data, "sonda_outcomes.jsonl"), outs)
    _write_jsonl(os.path.join(data, "sonda_decisions.jsonl"), decs)

    state = {"exported_at": _iso(now),
             "counts": {"predictions": len(preds), "state_reads": len(reads), "decisions": len(decs)},
             "rule": {"file": "question_rule.json", "sha256": rule_sha, "sha": rule_sha}}
    with open(os.path.join(data, "EXPORT_STATE.json"), "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)

    shutil.copytree(os.path.join(REPO, "verify"), os.path.join(dst, "verify"))
    return dst


def build_live(dst):
    """旧的「干净副本」：当前盘上 data/ 的拷贝。留作**观测**，不作控制组。"""
    os.makedirs(dst, exist_ok=True)
    shutil.copytree(os.path.join(REPO, "data"), os.path.join(dst, "data"))
    shutil.copytree(os.path.join(REPO, "verify"), os.path.join(dst, "verify"))
    return dst


def run(dst):
    env = dict(os.environ, CHECK_REPO=dst)
    r = subprocess.run([sys.executable, os.path.join(dst, "verify", "check.py")],
                       capture_output=True, text=True, env=env, timeout=120)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def edit_json(path, fn):
    d = json.load(open(path, encoding="utf-8"))
    fn(d)
    json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def main():
    now = datetime.now(CN)
    cases = []

    def case(name, mutate, expect):
        cases.append((name, mutate, expect))

    def m_export(d):
        edit_json(os.path.join(d, "data", "EXPORT_STATE.json"), lambda s: s.__setitem__(
            "exported_at", _iso(now - timedelta(hours=48))))

    def m_read(d):
        p = os.path.join(d, "data", "state_reads.jsonl")
        rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
        rows[-1]["read_at"] = _iso(now - timedelta(hours=9))
        _write_jsonl(p, rows)

    def m_settle(d):
        p = os.path.join(d, "data", "sonda_outcomes.jsonl")
        rows = [l for l in open(p, encoding="utf-8") if l.strip()]
        open(p, "w", encoding="utf-8").writelines(rows[:-1])

    def m_decision(d):
        # 决策腿假死：最后一行改成 30 小时前（预测行更老，所以 max() 落在它上面）
        p = os.path.join(d, "data", "sonda_decisions.jsonl")
        rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
        rows[-1]["at"] = _iso(now - timedelta(hours=30))
        _write_jsonl(p, rows)

    def m_counts(d):
        edit_json(os.path.join(d, "data", "EXPORT_STATE.json"),
                  lambda s: s["counts"].__setitem__("state_reads", 999999))

    def m_rule(d):
        # 公开的规则被改过：导出记录里的 sha 对不上了（本地偷偷放宽视界）
        p = os.path.join(d, "data", "question_rule.json")
        r = json.load(open(p, encoding="utf-8"))
        r["horizons_hours"] = [3.0, 6.0]
        json.dump(r, open(p, "w", encoding="utf-8"), ensure_ascii=False)

    def m_batch(d):
        # 有一批「到期 6 道只处置了 5 道」——漏答必须在闸上红
        p = os.path.join(d, "data", "sonda_decisions.jsonl")
        rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
        rows.append({"at": _iso(datetime.now(CN)), "kind": "batch", "slot": "morning",
                     "trigger_id": "t-selftest", "due_count": 6, "answered": 5,
                     "abstained": 0, "refused": 0, "omitted": [],
                     "missing": ["mkt_silicon_best_buy|3|gt|0"], "off_rule": []})
        _write_jsonl(p, rows)

    case("A 导出腿停摆 48h", m_export, "[导出腿]")
    case("B 采集腿断流 9h", m_read, "[采集腿]")
    case("C 结算腿丢一条结算", m_settle, "[结算腿]")
    case("D 决策腿假死 30h", m_decision, "[决策腿]")
    case("E EXPORT_STATE 条数撒谎", m_counts, "[自洽]")
    case("F 公开规则被偷偷改过", m_rule, "[规则]")
    case("G 批次里有漏答的题", m_batch, "[批次]")

    bad = 0
    with tempfile.TemporaryDirectory(prefix="ow-selftest-") as tmp:
        # 对照：**自造**的干净样本必须过 —— 每次现造，不读 live
        rc, out = run(build_clean(os.path.join(tmp, "clean")))
        ok_clean = (rc == 0)
        print("对照 自造干净样本(按构造合法)  rc=%d %s"
              % (rc, "PASS（这条闸说得出「通过」）" if ok_clean else "**样本或 check.py 坏了**"))
        if not ok_clean:
            bad += 1
            print(out[-600:])

        for i, (name, mutate, expect) in enumerate(cases):
            d = build_clean(os.path.join(tmp, "m%d" % i))
            mutate(d)
            rc, out = run(d)
            got_fail = (rc != 0)
            named = any(l.startswith("FAIL") and expect in l for l in out.splitlines())
            ok = got_fail and named
            print("样本 %-22s rc=%d %s" % (name, rc, "PASS（这条闸说不）" if ok else "**没拦住**"))
            if not ok:
                bad += 1
                print(out[-600:])

        # 观测（**不计分**）：live 台账副本。
        # 它红 = 当前盘上的数据陈旧，不是判据坏了；旧写法把它当控制组，于是红也红在错的地方。
        rcl, outl = run(build_live(os.path.join(tmp, "live")))
        print("观测 live 台账副本              rc=%d %s（读当前盘上的数据；红=数据陈旧，不判本脚本/check.py）"
              % (rcl, "GREEN" if rcl == 0 else "RED"))
        for l in outl.splitlines():
            if l.startswith("FAIL"):
                print("      live FAIL  %s" % l[6:])

    print()
    if bad:
        print("结论：%d 项没过 —— 这条闸的可证伪性不成立。" % bad)
        return 1
    print("结论：%d/%d。这条闸能说不（7 个已知坏样本），且干净时确实说通过"
          "（自造样本，不依赖 live）。" % (len(cases) + 1, len(cases) + 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
