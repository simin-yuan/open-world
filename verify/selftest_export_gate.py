#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""selftest_export_gate.py — 证明「发布前隐私闸」真的接在发布路径上，而且会拦。

为什么需要它：闸自己有自证（`selftest_leakscan.py`），但**接线**是另一件事 ——
一个接错位置的闸和根本没有闸，从外面看长得一模一样（本仓 findings/06「提过一次 ≠ 交付过」同族）。
本自证只问一个问题：**导出工具会不会因为闸红而拒绝产出？**

四道用例（每道都能红）

| # | 场景 | 期望 |
|---|------|------|
| A | 干净沙箱 + 自造词表 | 导出 rc=0，且 stdout 里有闸的摘要行（**跑过 ≠ 静默**） |
| B | 沙箱里植入 L2 命中串与盘符路径 | 导出 rc=1（拒绝），stdout 点名命中文件 |
| C | 沙箱里**去掉词表** | 导出 rc=1（闸 rc=2 UNDECIDABLE）→ 必须拒绝，**不许把「没查」当「干净」** |
| D | PATH 剥空下重跑 A | 仍 rc=0（进程内调用，不靠 PATH；cron 无 PATH） |

沙箱 = 本仓的临时副本（排除 `.git` / `_local`），词表 **自造**（不拷 live 词表）：
对照/test 数据跟着被测对象一起沉，是本仓已记的失败形态（findings/07）。

用法：
    python verify/selftest_export_gate.py [--root REPO]

退出码：0 = 四道全按预期；1 = 有偏离。
"""
import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.normpath(os.path.join(HERE, os.pardir))

#: 自造词表用的假标识串。刻意不用真名 —— 自证不该把要挡的词再写一遍（findings/09）。
#:
#: **拼接构造，不在源码里写成字面**：这份自证自己也在被扫的那棵树里，写成字面 = 让闸
#: 拒绝发布这份文件（实测过：写成字面时沙箱 LEAKS=2、导出 rc=1）。
#: 代价要说清：拼接正是本闸**拦不住**的写法之一（findings/09 已把「拼音/缩写/语义换写」
#: 列为未知盲区）。这里用它不是为了绕门，是为了把**测试夹具**从被扫内容里摘出来；
#: 夹具必须落在扫描范围内（否则测不到接线），又不许让扫描器命中自己 —— 只有这一条出路。
FAKE_TERM = "zzprobe" + "term"
FAKE_DRIVE_PATH = "Q:" + "/probe/leak/" + "x.txt"
IGNORE = shutil.ignore_patterns(".git", "_local", "__pycache__", ".venv", "venv", "build", "dist")


def build_sandbox(root, tmp):
    """把 root 整棵树复制到 tmp/sandbox，排除 .git / _local。→ sandbox 路径"""
    sb = os.path.join(tmp, "sandbox")
    shutil.copytree(root, sb, ignore=IGNORE, dirs_exist_ok=False)
    return sb


def write_terms(sb, lines):
    d = os.path.join(sb, "_local")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "privterms.txt"), "w", encoding="utf-8") as f:
        f.write("# 自造词表（自证用，非 live）\n" + "\n".join(lines) + "\n")


def build_src(tmp):
    """假台账源 + 假出题规则。内容最小但**合法**，让 export.py 走完全流程。"""
    src = os.path.join(tmp, "src")
    os.makedirs(src, exist_ok=True)
    with open(os.path.join(src, "sonda_predictions.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"prediction_id": "p1", "written_at": "2026-09-29T00:00:00+08:00",
                            "horizon_hours": 24, "direction": "up", "threshold": 1,
                            "probability": 0.5}, ensure_ascii=False) + "\n")
    with open(os.path.join(src, "sonda_outcomes.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"prediction_id": "p1", "outcome": "HIT", "checked_at": "2026-09-29T01:00:00+08:00",
                            "detail": "selftest"}, ensure_ascii=False) + "\n")
    with open(os.path.join(src, "state_reads.jsonl"), "w", encoding="utf-8") as f:
        f.write(json.dumps({"read_at": "2026-09-29T00:30:00+08:00", "credits": 7},
                           ensure_ascii=False) + "\n")
    rule = os.path.join(tmp, "rule.json")
    with open(rule, "w", encoding="utf-8") as f:
        json.dump({"version": "selftest", "whitelist": [], "horizons_hours": [24],
                   "directions": ["up", "down"], "threshold": 1}, f)
    return src, rule


def run_export(sb, src, rule, strip_path=False):
    env = dict(os.environ)
    if strip_path:
        env["PATH"] = ""
    p = subprocess.run([sys.executable, os.path.join(sb, "tools", "export.py"),
                        "--src", src, "--rule", rule],
                       cwd=sb, capture_output=True, text=True, timeout=300, env=env)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def case(name, cond, note=""):
    print("  [%s] %s%s" % ("PASS" if cond else "MISS", name, ("  %s" % note) if note else ""))
    return bool(cond)


def no_literal_sample_in_source():
    """把「夹具不许在源码里写成字面」变成可失败的检查，而不是靠记。"""
    with open(os.path.abspath(__file__), encoding="utf-8") as f:
        src = f.read()
    bad = [s for s in (FAKE_TERM, FAKE_DRIVE_PATH) if s in src]
    if bad:
        print("  [MISS] 自证源码含字面坏样本 %r —— 闸会拒绝发布这份文件（findings/09 同族）"
              % (bad,))
        return False
    print("  [PASS] 自证源码不含字面坏样本（拼接构造）")
    return True


def pick(out, needle, n=2):
    return " | ".join(l.strip() for l in out.splitlines() if needle in l)[:300]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=REPO, help="被测仓（默认 = 本脚本所在仓）")
    a = ap.parse_args(argv)
    root = os.path.abspath(a.root)

    print("selftest_export_gate root=%s" % root)
    ok = [no_literal_sample_in_source()]
    with tempfile.TemporaryDirectory(prefix="owgate_") as tmp:
        src, rule = build_src(tmp)

        # ---- A 干净沙箱：导出必须成功，且闸的摘要必须出现在输出里 ----
        sb = build_sandbox(root, tmp)
        write_terms(sb, [FAKE_TERM])
        rc, out = run_export(sb, src, rule)
        ok.append(case("A 干净 → rc=0", rc == 0, "rc=%d" % rc))
        ok.append(case("A 闸留下摘要（跑过 ≠ 静默）",
                       "[gate]" in out and "LEAKS=0" in out, pick(out, "LEAKS=")))

        # ---- B 植入命中：必须拒绝，且点名 ----
        plant = os.path.join(sb, "findings", "zz_selftest_probe.md")
        with open(plant, "w", encoding="utf-8") as f:
            f.write("# 自证探针（故意植入，勿提交）\n\n词表命中：%s\n盘符路径：%s\n" % (FAKE_TERM, FAKE_DRIVE_PATH))
        rc, out = run_export(sb, src, rule)
        ok.append(case("B 植入命中 → 拒绝", rc != 0, "rc=%d" % rc))
        ok.append(case("B 拒绝时点名命中", "EXPORT_REFUSED" in out and "LEAK" in out, pick(out, "LEAK")))
        ok.append(case("B 措辞写明「拒绝产出」", "拒绝产出" in out))
        os.remove(plant)

        # ---- C 去掉词表：UNDECIDABLE（没查）不得当通过 ----
        sb3 = os.path.join(tmp, "sandbox_nolist")
        shutil.copytree(root, sb3, ignore=IGNORE)
        rc, out = run_export(sb3, src, rule)
        ok.append(case("C 无词表 → 拒绝（没查 ≠ 干净）", rc != 0, "rc=%d" % rc))
        ok.append(case("C 理由写明未跑/UNDECIDABLE",
                       ("UNDECIDABLE" in out) or ("rc=2" in out), pick(out, "字面层")))

        # ---- D PATH 剥空：cron 环境形态下仍要跑得起来 ----
        sb4 = os.path.join(tmp, "sandbox_nopath")
        shutil.copytree(root, sb4, ignore=IGNORE)
        write_terms(sb4, [FAKE_TERM])
        rc, out = run_export(sb4, src, rule, strip_path=True)
        ok.append(case("D PATH 剥空 → 仍 rc=0", rc == 0, "rc=%d" % rc))
        ok.append(case("D PATH 剥空 → 闸仍留摘要", "LEAKS=0" in out))

    print("SUMMARY %d/%d\n" % (sum(1 for x in ok if x), len(ok)))
    return 0 if all(ok) else 1


if __name__ == "__main__":
    sys.exit(main())
