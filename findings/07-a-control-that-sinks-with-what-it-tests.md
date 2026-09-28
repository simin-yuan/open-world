# 07 · 跟着被测对象一起沉的对照，不是对照

**观测**（本机可重跑）

改前（提交 `853d831`），`python verify/selftest.py` 里红的不是七个坏样本，是那**一个**对照：

```
对照 干净副本            rc=1 **本脚本或 check.py 坏了**
样本 A 导出腿停摆 48h     rc=1 PASS（这条闸说不）
样本 B 采集腿断流 9h      rc=1 PASS（这条闸说不）
… 七个坏样本全 PASS
结论：1 项没过 —— 这条闸的可证伪性不成立。
```

同一时刻 `python verify/check.py` 打的是另外三件事：
`[采集腿] 最新观测 9.8h 前（硬线 6h）` · `[决策腿] 决策账本已 34.9h 没有新行（硬线 24h）` ·
`[批次] 2026-09-27 due=4 answered=0`。这三条说的是 **live 台账数据陈旧**。两者不是一回事，
但输出把它们混成了一句指控。

**根因**（本机可复现）

`verify/selftest.py` 原来的 `build()` 只有一句 `shutil.copytree(REPO/data → 临时目录/data)`：
所谓「干净副本」= **当前盘上数据的拷贝**。live 一陈旧，控制组跟着陈旧。于是：

- 对照红的**是 live 的新鲜度**，脚本却把它写成「本脚本或 check.py 坏了」——归因错误；
- 七个坏样本全绿，只有**「这条闸能不能说通过」这唯一一格**红了。套件看起来 7/8 还行，
  缺的恰是关键的那一格。全绿的是否定侧，塌的是肯定侧。

**为什么它不只是噪音**

`.github/workflows/freshness.yml` 里 `selftest.py` 是**第一步**。GitHub Actions 默认语义下
一步失败即终止该 job，于是对照一红，`selftest_gate_stat.py` 与 `check.py` **都不跑**——
「四条腿到底怎么样」在 CI 日志里根本看不到，只剩一句针对 `check.py` 的栽赃。
（本机跑不了 CI，故此处只声称：workflow 的步骤内容与默认语义如此，日志会被挡住；
不声称「CI 当前是什么颜色」。）

同族：这个包里的 01（只读面会撒谎）、02（空列表是仪器故障）、06（提过一次不等于交付过）——
共同点都是**结论所依赖的那个前提没人验**。这条是新的一支：**对照的前提是「它干净」，而干净由谁保证？**

**修法**（不是开白名单，是换掉对照的取材）

1. 控制组改成 `build_clean()`：按 `check.py` 的契约**现造**一份合法台账（时间戳现取、
   条数自洽、规则 sha 对齐）。**必须每次重建** —— 写成只读快照的话，它会自己变陈旧，
   落进同一形态（F3 实测打红）。
2. 七个坏样本也都建在这份自造样本上：一处只坏一条腿，live 的噪声不再混进来。
3. live 台账**另外跑一次，只作观测**，标签写死「红 = 数据陈旧，不判本脚本/check.py」，**不计分**；
   并把它的 FAIL 行原样打出来 —— 该被看见的信息不再被前一步挡在门外。
4. CI 的后两步加 `if: always()`：只让它们照跑照打印，**不改判定**（job 该红的还是红）。

**证伪**（`EXCURSION_10H/_t8_falsify.py`，4/4；输出 `EXCURSION_10H/evidence/t8_falsify.json`）

| 探针 | 期望 | 实测 |
|---|---|---|
| BASE 自造样本 | 绿 | rc=0 |
| F1 控制组换成 live 快照（=旧定义） | 红 | rc=1 |
| F2 自造样本里删掉 `sonda_decisions.jsonl` | 红 | rc=1（`data/… 不存在`） |
| F3 自造样本整份时间戳回拨 7 小时 | 红 | rc=1（`[采集腿] 7.0h 前`） |

F1 证明这条红确实由旧定义造成（不是空改）；F2 证明控制组真把样本喂给了 `check.py`（不是跑了个寂寞）；
F3 证明「每次重建」是承重的，不是装饰。

**边界**（别把这条判据当它撑不住的东西）

- 修的是**对照的取材**，不是 `check.py` 的判据，也没动任何阈值。三条 live FAIL 一条没少，
  live 观测仍然 RED；那三条的处置仍归 sonda 线。
- `build_clean()` 是 `check.py` 契约的**手写镜像**：`check.py` 加一条腿就得同步改它，
  否则对照会红。这是刻意留的摩擦（判据变了得有人知道），但它是**手工同步**，
  不等于「契约自动一致」——别把这条当成自动对账的证明。
- 本轮未改 CI 判定语义（`always()` 只加打印不减判定）、未加域名、未发布任何东西。

## 指纹与复现

| 文件 | 字节 | sha256（LF；= git blob） |
|---|---|---|
| `verify/selftest.py` | 11168 | `ee82ed4133369ab82e26c5ec4755e3754fd82b78aff93ae92b604b398f375095` |
| `.github/workflows/freshness.yml` | 1821 | `cba5afb85be8841a26a366edaf4b568fb8d03d01df3247ae480fcf61c676be7f` |
| `README.md` | 13242 | `c5663950e04c72346f67254bc028627aec7ed44bcd696f2d474d4851d8fbbb4e` |

字节数与哈希取自 **git blob**（`git cat-file blob <ref>:<path> | sha256sum`），不是工作副本的临时状态。
本仓 `core.autocrlf=true`：Windows 上 clone 出来是 CRLF，字节数与哈希都会变 —— 对账请用 blob。

复现：

```
python verify/selftest.py            # rc=0 8/8（自造对照 PASS + 7 个坏样本；live 观测另列，不计分）
python EXCURSION_10H/_t8_falsify.py  # rc=0 4/4（BASE 绿 / F1–F3 红）
python verify/check.py               # 仍 rc=1 —— 三条 FAIL 是 live 数据陈旧，归 sonda 线
```
