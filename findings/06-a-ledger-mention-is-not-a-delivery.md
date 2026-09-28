# 06 · 台账里提过一次，不等于交付过

**观测**（本机可重跑）
`python verify/ledger_discipline.py --explain` 在真实台账
（`works/works_agenda.jsonl`）上的第一次输出，逐条 hit 如下：

```
T1 refs=2 hit=028e460
T2 refs=11 hit=-
T3 refs=8 hit=verify/gate_stat.py
T4 refs=3 hit=-
```

T3 的提交 `9ff00d5` 在台账里 `grep -c` = **0**，工具却说它「已覆盖」。命中的是另一条
更早的记录里的相对路径 `verify/gate_stat.py` —— 而那句原文写的是：

> 未查清：ERR 1 根因未定位、**verify/gate_stat.py 未落地**、…

**判据测的是字符串，不是状态。**「X 已交付」与「X 未落地」在字符串层面同形，任何基于
文本包含的覆盖性检查都会从这里漏过去，而且漏的方向是**假绿**（把没做的事报成做了）。

**修法**：R1 的产物引用收紧为「提交号 ∪ 绝对路径（盘符路径）」，相对路径一律不认；
并把这条真实样本固化成 `verify/selftest_ledger_discipline.py` 用例 K（必须判红）。
收紧后同一次运行对同一台账给出 `T3 hit=-`，红得正确。

**边界**（别把这条判据当它撑不住的东西）：即使收紧，R1 也只证明「这个字符串在台账里出现过」。
它不证明产物真实存在、不证明归属正确、不辨认反语。交付证明要么读盘
（`works/workline_check.py` 已管 delivered 产物的存在性），要么读 VCS。R1 是覆盖性线索，
不是交付证明。
