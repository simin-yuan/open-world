# 05 · 执行件落地了，而它现在的结论是「无法判定」

> 2026-09-29 · 分支 `main` · 基线 `00b1c1e` · 本轮把 `GATE.md` §八 的执行件补上
> 产物：`verify/gate_stat.py` · `verify/selftest_gate_stat.py`

## 为什么要这一段

§八（「弃权即采纳基线」）2026-09-26 就签了，形态是外脑推的，门槛是持有者签的 —— 但它一直是
**一份跑不出数的判据**。本轮之前，仓库里没有任何东西能把「我到底有没有优于同题基线」算出来。
这不是缺文档，是缺执行件：没有它，§八 的每一个字都无法被证伪。

## 观测（判据直接给出的，本机可重跑）

```
$ python verify/gate_stat.py            # rc=2
gate_stat — GATE.md §八「弃权即采纳基线」执行件（只读、零 LLM）
  门槛（抄自 §八）：单侧 0.95 区间 · N0 >= 10 · 以窗口为单位

[观测] 规则网格 376 道 / 79 个窗口 · 两端可比读数 376 道
[观测] 缺基线 p_base 376 道 · 无我方处置记录 0 道 · 系统拒题 0 道
[观测] 可评题 N0=0 · 可评窗口 0
[观测] 前置条件 ①基线落账=False（data/sonda_baseline.jsonl 不存在 —— 前置条件①未落地）
       ②拒题拆分=False（0 行决策含 abstained_self/refused_system）③窗口聚类=True
REASON NO_EVALUABLE_QUESTION: 0 道规则题同时具备『世界已给答案 + 基线 p_base + 我方处置记录』
REASON N0_BELOW_MIN: 可评题 0 < 10
REASON CLUSTERS_BELOW_MIN: 可评窗口 0 < 2（单侧 t 区间需要 df>=1）
REASON P1_UNMET: data/sonda_baseline.jsonl 不存在 —— 前置条件①未落地
REASON P2_UNMET: 决策台账没有 abstained_self/refused_system 拆分

结论：无法判定 —— 这不是失败，是现有的台账还算不出这个数。上面点名了缺什么。
```

自检（证明它既能说不、也能说是）：

```
$ python verify/selftest_gate_stat.py   # rc=0
  CONTROL 真实台账 → UNDECIDABLE          PASS  rc=2 verdict=UNDECIDABLE lower=None
  T 单侧 95% t 分位点 vs 已知值             PASS  最大偏差 0.00005
  S1 契约完整/明显优于基线 → PASS            PASS  windows=141 rc=0 verdict=PASS lower=0.2038 N0=282
  S2 可评题 <10 → UNDECIDABLE(N0)         PASS  N0=2
  S3 缺基线 p_base → UNDECIDABLE(P1)      PASS
  S4 缺 abstained_self/refused_system → UNDECIDABLE(P2)  PASS
  S5 d≡0 → UNDECIDABLE(CI_INCLUDES_ZERO)  PASS
  S6 规则文件坏 → ERROR(exit 3)             PASS
结论：8/8。
```

`S1` 是这一段的关键：一份只会在任何输入上返回「无法判定」的脚本不携带信息。**契约齐全、
优势明显时它真的判 PASS**（单侧下界 0.2038 > 0，N0=282）—— 它不是恒真条件。

`T` 是分位数自算（本工具不引入 scipy）：df = 1 / 5 / 9 / 30 / 1000 五点上与教科书值最大偏差 5e-5。

## 工具契约（写进脚本头部，缺哪一项就红哪一项）

| 输入 | 缺了会怎样 |
|---|---|
| `data/question_rule.json` | 坏 → `ERROR`（仪器故障，与「无法判定」分开记） |
| `data/state_reads.jsonl` | 缺/空 → `ERROR` |
| `data/sonda_predictions.jsonl` | 我方事前概率 `p_mine` |
| `data/sonda_baseline.jsonl` | 缺 → `P1_UNMET`（**刻意不自行推导**：照旧基线是判据的一部分，工具去推它等于替基线改答案） |
| `data/sonda_decisions.jsonl` | 无 `abstained_self` / `refused_system` → `P2_UNMET` |

输出只有三值：`PASS=0` / `UNDECIDABLE=2` / `ERROR=3`。§八 没有「FAIL」这一值，本工具不新造。

## 候选解释（机制自洽，未验证）

- `p_base` 缺口是结构性的，不是数据丢了：§八 前置条件 ① 原文即写「现在门在弃权路径上不落
  `p_base`，须补」。所以 376 道全数缺，与门的表现一致。**未验证的环节**：本工具没有去读门的
  源码确认它到底在哪几条路径上没落 —— 依据是 §八 的原文与导出台账的一致缺失。

## 未证实（写成「未知」，不写成「没有」）

- 前置条件落地之后，真实台账会算出什么结论 —— **未知**。
- 门是否真的在弃权路径不落 `p_base`（源码级确认）—— **未查**。

## 本轮自己踩到的一个坑（已修，写在代码注释里）

第一版里「缺基线」的分支先 `continue`，于是 `unaccounted`（无我方处置记录）**永远显示 0**。
读起来像「我方处置记录齐全」，实际只是没走到那一步 —— **仪器把「没量」报成了「量到 0」**。
已改成两个计数各自独立统计、互不遮蔽。同族病见本仓 `findings/02`（空列表是仪器故障）。

## 顺带扫到的既有红（**不属本轮任务**，只记录）

本仓自己的 `verify/check.py` 在真实台账上现在是红的（这是它的输出，不是我加的判据）：

```
FAIL  [采集腿] 最新观测已 7.5h 前（硬线 6h）
FAIL  [决策腿] 决策账本已 32.6h 没有新行（硬线 24h）
FAIL  [批次] 2026-09-27T20:05:15+08:00 不完整：due=4 answered=0 abstained=0
```

- **观测**：`data/state_reads.jsonl` 最新 `read_at` = 2026-09-28T21:10:16；`data/sonda_decisions.jsonl`
  最新一行 = 2026-09-27T20:05:15；导出时刻 2026-09-28T21:20:14（以上三个数都在
  `data/EXPORT_STATE.json` 的 `newest` 里）。
- **候选解释（未验证）**：读数比导出时刻早 10 分钟，但导出本身已 7.3 小时前 —— 无法区分
  「采集在 21:10 停了」与「导出只截到那一刻的快照，之后本地还在写」。**未验证的环节**：导出脚本
  的取数窗口，本轮没读它。
- **未证实**：本地门现在是死是活 —— 未知，本轮没查（不属本轮任务）。
- 连带：`verify/selftest.py` 的「干净副本」对照用真实数据建，因此此刻也会红（rc=1），与本节改动无关。
  已入队为 `EXCURSION_10H/PLAN.md` 的 T7，归 sonda 线处理，本轮不动。
  → **2026-09-29 修订（R9/T8）**：上一段只对了一半，处置作废。对照红**确实**由 live 数据陈旧触发，
    但**因不在数据，在 `selftest.py` 自己**——它把「干净副本」定义成 live 数据的拷贝，于是对照跟着
    被测对象一起沉，脚本还把原因报成「本脚本或 check.py 坏了」。归 sonda 线的只有那三条腿的 FAIL；
    对照的定义是本仓的缺陷，已修（`verify/selftest.py`，见 `findings/07`）。
    **作废的是「与本节改动无关、本轮不动」这个处置，不是上面的观测。**

## 指纹与复现

| 文件 | 字节 | sha256（LF；= git blob） |
|---|---|---|
| `verify/gate_stat.py` | 19909 | `94fbff07e8123b5a41621a2937a8a463e9fca1a04357a5c07cafe5305d0aeab3` |
| `verify/selftest_gate_stat.py` | 10775 | `0d8a7630c7939e1324120046c4b12c52de409dd97969ae52ef51d3a3e4d69b8b` |

字节数与哈希取自 **git blob**（`git cat-file blob <sha> | sha256sum`），不是工作副本的临时状态。
注意本仓 `core.autocrlf=true`：在 Windows 上 clone 出来会是 CRLF，字节数与哈希都会变 ——
对账请用 `git cat-file blob HEAD:verify/gate_stat.py | sha256sum`。

复现三条：

```
python verify/gate_stat.py            # rc=2  UNDECIDABLE（真实台账）
python verify/selftest_gate_stat.py   # rc=0  8/8（含一个 PASS 正样本）
python verify/check.py                # rc=1  3 条 FAIL —— 既有红，见上
```

本轮**没有推远程**（推送 = 对外发布，按本线红线须授权人批）。CI 里加了这一步，
但 CI 此刻若跑会红在数据腿（同上），与本轮改动无关。
