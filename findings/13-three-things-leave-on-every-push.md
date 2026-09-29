# 13 · 一次 push 送走三样东西：树干净、信息干净，中间那版 blob 不干净

> 2026-09-29。`verify/leakscan.py`（树）与 `verify/pushscope_gate.py`（待推提交信息）**双双全绿**，
> 本地领先远端 `main` 10 个提交 —— 这 10 个提交的范围里仍有 **3 个 blob / 8 处命中**带着
> 词表词与机器盘符路径。它们**只在中间某个提交里存在**（后来被改干净了），所以前两道闸都看不见。
> 一次 push 就会把它们写进 GitHub 的永久历史。本文记观测、能撑住观测的候选解释、和明确没验到的部分。

## 观测（都能在本机重跑出来）

| # | 观测 | 判据 |
|---|---|---|
| O1 | 树：`LEAKS=0 rc=0`（files=44）。信息：`commits=10 LEAKS=0 rc=0` | `python verify/leakscan.py` / `python verify/pushscope_gate.py` |
| O2 | 同一范围的对象内容：`objects=93 blobs=42 **LEAKS=8** allowlisted=21 rc=1` | `python verify/history_gate.py` |
| O3 | 42 个 blob 里 **14 个不在 HEAD 树里**（只存在于中间提交）；8 处命中全部落在这 14 个里 | 闸的 `B0` 行 + 每处命中后的 `[只在中间提交里 · 树闸看不见]` |
| O4 | 3 个脏 blob 的身份：`findings/05-…md` 两版（L2-term，len=5）、`verify/ledger_discipline.py` 一版（L2-term ×2 + S1 盘符 ×3，len=39/52/53） | 打码输出 + `git cat-file blob <sha>` |
| O5 | 不套豁免时同一范围是 29 处命中，其中 21 处正是树闸**已经给过理由**的豁免（形状规则自己的源码就在范围内） | 加 `LS.ALLOW` 前/后两次运行 |
| O6 | 自证 11/11（含核心用例：**同一夹具上 `leakscan.scan()` rc=0 而本闸 rc=1**）；变异 3/3；发布路径自证 15/15 | `python verify/selftest_history_gate.py` / `falsify_history_gate.py` / `selftest_export_gate.py` |

## 候选解释

- `git push` 送走的是 `<upstream>..HEAD` 的**新对象集**，不是 HEAD 的树。所以「一个文件在中间提交里
  带过敏感串、随后被改干净」这个**最普通**的编辑历史，正好落在两道闸的缝里：树闸量的是终点，
  信息闸量的是 message，**没有一道闸量过中间态**。**（未验证的环节：无 —— 这是定义层面的事，
  且 O3/O6 已把它变成可重跑的证伪）**

- 本仓这 3 个脏 blob 是**修法自身留下的**：findings/05 的人名、`verify/ledger_discipline.py` 写死的
  本机路径，都在更晚的提交里被改干净了（那两次「去泄漏」提交本身是对的）——它们把**树**修干净了，
  同时把「修之前的样子」永久留在了范围内。**（未验证的环节：这三处是否曾在某个时刻被 push 过 —— 见下）**

- 豁免必须两道闸共用：给范围内容闸单独发明一套豁免，它就会因为「形状规则的源码天然含形状」
  永远红；而一道永远拒绝的闸和没有闸等价（findings/10 同族：闸要能被满足，才谈得上拦得住）。

## 处置（本轮做了）

- 新闸 `verify/history_gate.py`（`scan_history()`，进程内可调）：范围 = `<upstream>..HEAD` 的对象，
  形状层 + 字面层，**沿用树闸同一份 `ALLOW`**，命中样本默认打码（它的 stdout 也会被折进下一条提交信息），
  每处命中标出「只在中间提交里 / 也在 HEAD 树里」并点名涉及的提交。
- 接进发布路径：`tools/export.py::privacy_gate()` 由两道闸变三道闸，任一非 0 一律拒绝产出（fail-closed），
  拒绝措辞已更新为点名三道闸与 findings/09、10、12、13。
- 接进 CI：`selftest_history_gate.py` + `falsify_history_gate.py` 两步（`if: always()`），summary 加一行。
- 自证与变异都在**自造本地裸仓**里跑（不联网、不读 live 仓），核心用例是「树闸绿而本闸红」。
- **未处置**：那 8 处命中仍在范围内的中间提交里（处置 = 重写这批未推提交的树，是下一轮的事；
  在它落地之前，导出腿会因本闸而**拒绝产出** —— 这正是闸存在的意义）。

## 未证实 / 不含

- **不含**：tag 名、分支名、reflog、stash、notes、PR 正文 —— 未查，不写成「没有」。
- **不含**：不可达对象（dangling / 已 elide 的 reflog）。重写后旧对象仍在本机对象库与 reflog 里，
  直到一次 `gc` —— 那是**本机**风险，不是发布面；本轮没做 gc，所以不写「已清干净」。
- **未证实**：这 3 个脏 blob 会不会**已经被 push 出去过**。`origin/main` 现在停在 `00b1c1e`，
  而这三个 blob 只存在于领先它的提交里 —— 以本地引用为准它们没出去过；但「远程此刻的 main
  是否被别处改写」本闸不判（那是 `bridge_landed` 的活，且它那双腿 T11 起仍断着）。
- **不含**：二进制 blob（前 4KB 含 NUL 一律跳过并计数）—— 本工具不判二进制里嵌的信息。
- 闸不判语义换写（同音 / 拼音 / 缩写 / 拆分拼接），与 leakscan 同一条盲区。
