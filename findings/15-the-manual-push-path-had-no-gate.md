# 15 · 手动 push 那条门：把「没有闸的那条路」补上一道 fail-closed 的 pre-push 闸

**一句话**：发布路径原先只有一条腿有闸（自动导出 job 的出口，T10 做的）；
**手动 `git commit && git push` 这条腿一道闸都没有** —— 实测那次泄漏（findings/08）
正是手动提交进去的。本轮把这条腿补上，并且让「装了没有」本身变成可失败检查。

T14（R16）自己点名的未处置项里就有这一条（manual commit path / hooks 为空）。
机制线的队列到 R16 已清空（done=14, todo=0，elapsed 8.94h/10h），本轮按 R12–R16
的先例新开一件，只做这一件。

## 做了什么（四个部件）

| 部件 | 作用 |
|---|---|
| `verify/prepush_gate.py` | 闸体：进程内调树闸 + 待推提交信息闸 + 待推对象内容闸（**与 ① 共用同一批函数**，不另写一套标准）。rc 0/1/2/3，FAIL 优先于 UNDECIDABLE；写 `.git/prepush_gate.log` 一行留痕 |
| `tools/git-hooks/pre-push` | 模板（进仓，可 review）：git 调它 → 它调闸体。任一非 0 = 拒绝本次 push；定位全用 shell 内建，解释器 / git 走 sidecar，不靠 PATH |
| `tools/install_git_hooks.py` | 安装器 + `--check`：装上 + 写下两个 sidecar；`--check` 红在四件事上 —— 没装 / 内容漂移 / sidecar 失效 / **core.hooksPath 被改指（装了等于没装）** |
| `verify/selftest_prepush_hook.py` + `verify/falsify_prepush_hook.py` | 夹具自证 26 断言（9 组用例）+ 变异证伪 4/4 |

判据不是「代码里写了什么」，是两样硬证据：**远端 ref 动没动** + **留痕日志（rc 几）**。

## 实测（新鲜）

```
selftest  SUMMARY 26/26          （9 组用例：绿路 / 树脏 / 信息脏 / 词表缺 / 无 PATH+sidecar /
                                  无 PATH 无 sidecar / --no-verify 旁路 / hook 被改 / hooksPath 改指）
falsify   SUMMARY 4/4            （对照组 case_a 绿；三个变异体分别被 case_b|c|d、case_d、case_h 抓住）
install   installed sha256=5c3534449007278eb26246774703346aee6e9d663a81c90902bfe1231dd5c2af
          template  sha256=5c3534449007278eb26246774703346aee6e9d663a81c90902bfe1231dd5c2af  bytes=3717
--check   rc=0（内容一致 / 两个 sidecar 在 / core.hooksPath 未设置）
四道闸    leakscan files=53 LEAKS=0 rc=0 ｜ pushscope commits=12 LEAKS=0 rc=0
          ｜ history blobs=45 LEAKS=0 rc=0 ｜ ledger 3/3 rc=0        （均为装完 hook 之后的新鲜跑）
```

## 夹具当场抓出的两个真 bug（不摆夹具两个都不会被发现）

1. **MSYS 形态路径喂给了原生 python**：hook 里 `pwd` 出来的是斜杠打头那种路径，进原生
   `python.exe` 会被重新解释 —— 闸报「can't open file 临时目录下的 prepush_gate.py」，
   即临时目录被拼到了当前盘符根下。绿路用例（case_a）当场红。
   修法：对 shell 的文件测试用 MSYS 形态、对 python 的 argv 用 `pwd -W` 的原生形态
   （Linux 无 `pwd -W` 时退回 POSIX 形态）。
2. **留痕断言写错**：日志行是 `<时间戳> rc=<n> base=<sha>`，先写成 `endswith("rc=1")`
   —— 断言永远为假、却看起来在测东西。改成解析 `rc=` 字段。
   教训同族：**「断言写了」不等于「断言在测那件事」**。

附带一次自击：模板第一版把踩到的路径样本原文写进了注释，**树闸当场把自己的新文件判红**
（S1/S2 共 4 处）。这与 findings/12 同族（写闸的人也在自己那道闸的扫描面里）——
所以模板里只描述形状、不复写样本。

## 判据边界（这一节比结论重要）

- **只在装了 hook 的本机克隆上生效**。`git push --no-verify` 直接绕过 —— 自证里
  case_g **专门把这个洞测出来**（远端照动、日志无新行），不是假装它不存在。
  别的机器 / CI 上没有这道闸。
- 只盖 git 这一条出口；飞书 / X / 邮件 / 网页表单不在这里。
- **取不到基时拒绝**（新分支首推、本地无 remote-tracking ref）→ UNDECIDABLE=2。
  这是 fail-closed 的代价，写在明面上：停是可逆的，发布不是。
- 不判二进制里嵌的信息、不判语义换写法（同 leakscan 的边界面）。
- **对本机自动导出 job 的影响未验证**：装了 hook 之后，导出 job 的 push 也会先过这道闸
  （这是有意的：脚本路径与手动路径共用一条门）。但「下一次 21:20 的导出还推不推得动」
  只能等它自己跑 —— 本轮**不能**用一次真 push 去验（那就是对外发布）。
  桥的输出腿当前仍是断的（T11 已交出去，不在本线处理），所以这一条也没法从「有没有推成功」上间接看。

## 门 / 花费

未加域名、未花钱、未注册平台、**未真 push**、未放宽任何既有判据或阈值。
新增的都是收紧（多一道拒绝口）。
