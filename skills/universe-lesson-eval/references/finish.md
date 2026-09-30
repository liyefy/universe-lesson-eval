# 合并与报告交付

主代理只汇总检查索引、机器结果和需要裁决的疑点，详细证据留在文件中。先按 [工具入口](automation.md) 合并并运行 gate，不让模型手算得分、替缺项补通过或省略未验证边界。

## 生成可读报告

```powershell
python -X utf8 .agents/skills/universe-lesson-eval/scripts/render_report.py --plan PLAN.json --report REPORT.json --lock LOCK.json --output-dir rendered --project PROJECT_ROOT
```

输出 report.md、report.html、gate-result.json、review-decisions.json，目录内同名输出存在时拒绝覆盖。输入必须通过 v2 门禁；已有未验证项可以出报告，但显示暂计分且不授予等级。完整范围与局部范围分别标明，严重问题紧邻分数显示，全部原始/实际扣分可核查。

`--project` 指定真实课程项目根目录，省略时使用当前工作目录；全局安装或从其他目录渲染时必须显式传入，不能让指令指向技能发布仓库。脚本和输入、输出路径均在报告中解析成绝对路径。

- Markdown 使用真实绝对文件路径及1基行号链接，图片直接显示；不强迫所有缺陷交截图，命令日志、录屏或音频按证据类型交付。
- HTML 提供可见图片、可播放音视频、完整检查记录展开区和逐问题批阅。核对实际打开后的文字、链接、证据及窄窗口表现；渲染成功不等于课程通过。
- 问题正文只写实际、预期、影响和最小建议；代码定位可确定时才给路径/行号/组件/状态，不猜根因或提供未经核对的“可直接替换”补丁。
- 无已确认问题仍保留完整覆盖、未验证与 N/A 理由，不能只写“全部正常”。结果中的严重问题、暂计分和范围提示不得为了精简而隐藏。

## 批阅持久化

HTML 的确认修改/忽略/暂缓以及备注按 audit+plan+report 哈希保存于当前浏览器 localStorage。存储不可用会明确提示；导出 JSON 可长期保存，页面不声称直接改写磁盘。

导入仅接受同一报告、完整无重复问题集合和合法决策。浏览器导出后，使用工具再次校验并保存到新文件：

```powershell
python -X utf8 .agents/skills/universe-lesson-eval/scripts/review_decisions.py --report REPORT.json --input downloaded-decisions.json --out decisions-confirmed.json
```

批阅不修改原始缺陷、证据、得分或工单状态，也不自动触发修复。后续任务依据用户明确指令实施。需要将决策纳入新的展示时，render_report 可带 --decisions；原报告变更后旧批阅不能直接套用。

## 一键交给 AI

报告顶部的“复制给 AI 执行”把绝对路径、报告身份/哈希与**点击时的完整批阅及备注**合成任务指令；直接粘贴到有本机文件访问能力的 AI 对话即可接续，不必先下载 JSON。只交接 approve 的修复，ignore/defer/unreviewed 不进入修改范围；没有 approve 时复制的是报告解读任务。接手者先核对项目规则、版本、哈希与原始证据，保存并校验这份批阅，再做最小修复及针对性复验。

页面“查看给 AI 的完整指令”随选择、备注、导入与恢复实时更新。剪贴板不可用时展开并选中指令供手动复制，只有实际写入剪贴板成功才提示已复制。复制不执行任何修复或远端操作，外部发布仍遵守当前对话授权。

纯网页 AI 或另一台电脑不能靠绝对路径读取本机文件，须另行提供报告、证据和目标项目。最终交付同时给出 report.html 的可点击绝对路径并说明复制入口；不要只给 report.md，也不要把初始 review-decisions.json 当作页面最新批阅。旧版已生成 HTML 不会自行增加按钮，须保留原报告并渲染到新目录。

## 收尾

按 [飞书交付](feishu.md) 处理本轮已授权登记；本地验收或工具试跑不写远端。完成后记录实际静态/运行时/模型覆盖、缺口、报告位置及同步回执。项目采用 RCL 时更新本任务分片并运行其 logs:finish 与 pnpm logs:check；其他项目按自身规则收尾，不假定存在这些脚本。工作受阻按项目规则记录，不把评分生成当作真实专题验收完成。
