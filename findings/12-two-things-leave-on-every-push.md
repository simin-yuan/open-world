# 12 · 一次 push 送走两样东西：树干净，信息不干净

> 2026-09-29。`verify/leakscan.py` 全程绿（`LEAKS=0`）的那棵树，本地领先远端 `main` 9 个提交 ——
> 这 9 条提交里有 **2 条的信息**带着机器本地痕迹。只查树的闸看不见这一面，一次 push 就会
> 把它写进 GitHub 的**永久**历史。本文记观测、能撑住观测的候选解释，和明确没验到的部分。

## 观测（都能在本机重跑出来）

| # | 观测 | 判据 |
|---|---|---|
| O1 | 树：`LEAKS=0 rc=0`。信息：`<upstream>..HEAD` **9 条里 2 条命中** | `python verify/leakscan.py` / `python verify/pushscope_gate.py` |
| O2 | 命中一：一条自动导出提交的**标题**里是本机绝对路径（22 字符，形状=盘符 + 仓路径） | 闸的打码输出 + `git log -1 <sha>` |
| O3 | 命中二：另一条提交的**正文**里有词表词（len=5，操作者标识串）；标题干净 | 同上 |
| O4 | 路径进标题的链路两端都核到：`tools/export.py::privacy_gate()` 打的**第一行**被导出作业取走当标题（`stdout.splitlines()[0]`，作业源码已读） | 两侧源码 |
| O5 | 这条链路是**本次改动自己引入的**：findings/10 把闸的打点加在了 stdout 最前面 | `git log` 对应两次提交 |
| O6 | 全仓可达提交 **24 条**（含全部 ref）扫一遍：`0` 命中；其中**已在上游**的 15 条也是 `0` 命中 | `python EXCURSION_10H/_t12_probe_all_msgs.py`（用闸的同一套规则对象） |

O6 的意思：**已推出去的历史没有被这个问题污染**（判据范围 = `rev-list --all` 的可达对象）。
不可达对象（dangling / 已 elide 的 reflog）不在里面 —— 那是未知，不写成「没有」。

## 候选解释（机制自洽，但只有 O4/O5 是被证据链钉住的那一环）

- 「树绿 = 可以发」这个直觉把**发布面**缩小了一半。一次 push 送走树**和** `<upstream>..HEAD`
  的每条 message；只扫一半的闸，会给出一个能骗过自己的绿。**（未验证的环节：无 —— 这是定义层面的事）**
- 摘要行被当成标题用，是导出作业的实现细节（取第一行）。所以「闸把自己的结论打在最前面」
  这个看去无害的动作，等于把闸的输出**放进了发布面**。**（未验证的环节：其它消费者是否也取第一行 —— 未查）**

## 处置

**A · 修发布面（三处，都不含「缩小检测面」）**

1. `tools/export.py`：先打摘要行（`exported_at=…`）、再打闸的结论 —— 标题回到原来的形态。
2. `verify/leakscan.py`：头行只印末段、词表行只印相对路径（原先印**绝对**根路径与词表路径）。
3. `verify/pushscope_gate.py`：自己的输出同样只印末段 / 相对路径。

**B · 补上另一半闸（新）**

- `verify/pushscope_gate.py`：只扫 `<upstream>..HEAD` 的 message；形状层（盘符 / UNC / AppData）
  + 本机词表层；**默认不回显命中样本**（打码成「长度」）—— 回显它抓到的泄漏的闸，自己就是
  泄漏源。已在上游的坏提交判 `0`（推不走的不是这一次的风险）；解析不到上游 / 词表读不到
  一律 `UNDECIDABLE`（查不到 ≠ 干净）。
- `tools/export.py::privacy_gate()`：**两道闸串联**接在导出出口（fail-closed），`FAIL` 优先于
  `UNDECIDABLE`，非 0 即 `EXPORT_REFUSED` → 不提交、不推送。
- CI：`selftest_pushscope_gate` + `falsify_pushscope_gate` 两步进 `freshness.yml`。

**C · 已存在的 2 条脏信息：改信息，不动内容**

- `EXCURSION_10H/_t12_reword.py`：对 `origin/main..HEAD` 逐条重建（同一棵树 + 同一作者与时间 +
  清洗后的 message，`git commit-tree`），写完跑一遍闸，失败**自动回滚**；`update-ref` 带 old 值
  做 CAS。数据提交的标题改用**它自己产物里**的 `exported_at` 重建（读产物，不猜时间）。
- 结果：9 条里改写 2 条，`HEAD 26f6fdf3 → 09b3fabc`，`git diff --stat <old> <new>` **空**（内容零改动），
  重建后闸 `rc=0`。回滚路径 = 脚本打印的 old sha。

## 判据清单（本轮实测）

| 判据 | 结果 |
|---|---|
| `verify/selftest_leakscan.py` | `cases=11 failed=0` |
| `verify/selftest_pushscope_gate.py` | `cases=9 pass=9 fail=0` |
| `verify/selftest_export_gate.py` | `SUMMARY 15/15` |
| `verify/falsify_pushscope_gate.py` | `falsify 3/3（对照 rc=0）`（判红失能 / 永远回显 / 范围含已推，各自红在对的用例上） |
| 实仓 `verify/leakscan.py` | `LEAKS=0 rc=0` |
| 实仓 `verify/pushscope_gate.py` | 修前 `rc=1`（2 命中）→ 修后 `rc=0` |

## 教训（写成能红的形式，不靠记）

1. **发布面是两样东西**，「一半绿」不是绿。另一半的判据见 `verify/pushscope_gate.py` 头部。
2. **工具的输出也是发布面**：谁把它折进别处，谁就把它的每一行当公开文本。姊妹条：findings/10。
3. **修实例 ≠ 修判据**。同一天里这个缺陷复现了三次：新写的闸里写了字面盘符候选 → 被旁边那道
   树闸判红；把这条教训**写进注释**（又写了形状）→ 又红一次。第三次之后改法是加可失败的检查
   （`selftest_leakscan.no_abs_root_in_output` / `…no_literal_sample_in_source` / G 用例的
   `must_absent`），不是「下次注意」。
4. **改历史必须留回滚**：只改 message、树零改动、CAS 写入、写完复跑闸、失败自动回滚 ——
   否则「改干净了」这句话本身没有证据。

## 未证实 / 不含

- **不含**：tag 名、分支名、reflog、stash、notes、PR 正文 —— 未查，不写成「没有」。
- **不含**：不可达对象（dangling / 已 elide 的 reflog）。重写后旧对象仍在本机对象库与 reflog 里，
  直到一次 `gc` —— 那是**本机**风险，不是发布面；本轮**没做** gc，所以不写「已清干净」。
- **未证实**：其它取 `stdout` 首行的消费者（若有）是否也把闸的输出贴到了别处 —— 未查。
