#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""selftest.py — 证明这条闸**能说不**。

一个判据如果从来没被观察到拒绝过任何东西，它就不是判据，是装饰。
所以这里不测"check.py 会通过"——那件事毫无信息量。这里造四种**已知的坏**，
逐个喂给 check.py，要求它每一条都报 FAIL。

四种坏样本：
  A 导出腿停摆    把 exported_at 改成 48 小时前
  B 采集腿断流    把最后一条观测改成 9 小时前
  C 结算腿逾期    把一条已结算预测的结算记录删掉
  D 账本不自洽    把 EXPORT_STATE 里的条数改错

另加一个对照：干净副本必须**通过**（否则上面四条 FAIL 可能只是脚本本身坏了）。

    python verify/selftest.py
"""
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


def build(dst):
    os.makedirs(dst, exist_ok=True)
    shutil.copytree(os.path.join(REPO, "data"), os.path.join(dst, "data"))
    shutil.copytree(os.path.join(REPO, "verify"), os.path.join(dst, "verify"))


def run(dst):
    env = dict(os.environ, CHECK_REPO=dst)
    r = subprocess.run([sys.executable, os.path.join(dst, "verify", "check.py")],
                       capture_output=True, text=True, env=env, timeout=120)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def edit_json(path, fn):
    d = json.load(open(path, encoding="utf-8"))
    fn(d)
    json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=2)


def last_line(path):
    lines = [l for l in open(path, encoding="utf-8") if l.strip()]
    return lines[-1] if lines else ""


def main():
    now = datetime.now(CN)
    cases = []

    def case(name, mutate, expect):
        cases.append((name, mutate, expect))

    def m_export(d):
        edit_json(os.path.join(d, "data", "EXPORT_STATE.json"), lambda s: s.__setitem__(
            "exported_at", (now - timedelta(hours=48)).isoformat(timespec="seconds")))

    def m_read(d):
        p = os.path.join(d, "data", "state_reads.jsonl")
        rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
        rows[-1]["read_at"] = (now - timedelta(hours=9)).isoformat(timespec="seconds")
        with open(p, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def m_settle(d):
        p = os.path.join(d, "data", "sonda_outcomes.jsonl")
        rows = [l for l in open(p, encoding="utf-8") if l.strip()]
        open(p, "w", encoding="utf-8").writelines(rows[:-1])

    def m_counts(d):
        edit_json(os.path.join(d, "data", "EXPORT_STATE.json"),
                  lambda s: s["counts"].__setitem__("state_reads", 999999))

    def m_decision(d):
        # 决策腿假死：账本里最后一行是 30 小时前的（预测行更老，所以 max() 取它）
        p = os.path.join(d, "data", "sonda_decisions.jsonl")
        rows = [json.loads(l) for l in open(p, encoding="utf-8") if l.strip()]
        rows[-1]["at"] = (now - timedelta(hours=30)).isoformat(timespec="seconds")
        with open(p, "w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    def m_rule(d):
        # 公开的规则被改过：导出记录里的 sha 对不上了（本地偷偷放宽视界）
        p = os.path.join(d, "data", "question_rule.json")
        r = json.load(open(p, encoding="utf-8"))
        r["horizons_hours"] = [3.0, 6.0]
        json.dump(r, open(p, "w", encoding="utf-8"), ensure_ascii=False)

    case("A 导出腿停摆 48h", m_export, "[导出腿]")
    case("B 采集腿断流 9h", m_read, "[采集腿]")
    case("C 结算腿丢一条结算", m_settle, "[结算腿]")
    case("D 决策腿假死 30h", m_decision, "[决策腿]")
    case("E EXPORT_STATE 条数撒谎", m_counts, "[自洽]")
    case("F 公开规则被偷偷改过", m_rule, "[规则]")

    bad = 0
    with tempfile.TemporaryDirectory(prefix="ow-selftest-") as tmp:
        # 对照：干净副本必须过
        clean = os.path.join(tmp, "clean")
        build(clean)
        rc, out = run(clean)
        ok_clean = (rc == 0)
        print("对照 干净副本            rc=%d %s" % (rc, "PASS" if ok_clean else "**本脚本或 check.py 坏了**"))
        if not ok_clean:
            bad += 1
            print(out[-600:])

        for i, (name, mutate, expect) in enumerate(cases):
            d = os.path.join(tmp, "m%d" % i)
            build(d)
            mutate(d)
            rc, out = run(d)
            got_fail = (rc != 0)
            named = any(l.startswith("FAIL") and expect in l for l in out.splitlines())
            ok = got_fail and named
            print("样本 %-22s rc=%d %s" % (name, rc, "PASS（这条闸说不）" if ok else "**没拦住**"))
            if not ok:
                bad += 1
                print(out[-600:])

    print()
    if bad:
        print("结论：%d 项没过 —— 这条闸的可证伪性不成立。" % bad)
        return 1
    print("结论：%d/%d。这条闸能说不，且干净时确实说通过。" % (len(cases) + 1, len(cases) + 1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
