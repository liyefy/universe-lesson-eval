# 飞书问题交付

目标从用户本轮指定地址或 [项目本地配置](project-setup.md) 的 `feedback_url` 读取；发布包不预设内部表。正式授权登记时，从 Wiki 解析真实 Base，核对字段和专题选项。

项目如已提供 `feishu-task-runner` 与 `universe-feedback-audit`，从项目技能目录读取其 `SKILL.md` 与 `references/feishu-writeback.md`。核对 writer 实际配置的目标与本轮授权一致，再按其真实接口调用；缺失时保留本地 JSON，不猜接口或复制私有客户端。只复用客户端、分页、幂等和回读；不沿用历史 recheck 入表，也不因引用其他技能而扩大授权。技能维护、合成试跑或用户要求本地时不 apply。

## 准入与本地转换

新版导出只接受 v2 gate valid=true 的已确认 product issue。完整覆盖与质量得分不决定单条已复核问题是否可交付；未验证、环境问题、规则争议和旧反馈未经复验均不入表。确定性问题使用已校验的新运行复核，模型问题使用独立代理复核，无需强迫确定性问题再经模型投票。

issue 除 [v2 契约](schema-v2.md) 字段外须提供：

- kind=product、certainty=confirmed；topic 为表内已有专题选项，确为跨专题问题可空并在详情写范围。
- summary：一句可观察现象，最多60字且不换行，不写源码路径、DOM/useFrame 或优先级代码。
- location、environment、steps（非空数组）、actual、expected、impact、evidence_summary、boundary：让不读代码的人能复现，不只贴本地截图路径。
- record_id：只有查重确认原记录后才填。工程分析、评分与源码定位保留本地，不发到两列人读字段中。

```powershell
python -X utf8 .agents/skills/universe-lesson-eval/scripts/export_findings.py --plan PLAN.json --report REPORT.json --lock LOCK.json --output findings.json
```

如本轮已收集人工批阅，可加 `--decisions decisions-confirmed.json`，只导出 approve 的问题；批阅文件必须绑定同一报告。没有决策文件时按本轮既有授权导出已确认问题，不新增例行审批门槛。导出器不会访问飞书。

v1 导出维持旧 finding/review 契约，只用于历史报告的既有回读兼容；其 accepted、证据强度与得分不能冒充新版结果。新验收不再生成 v1。

## 唯一 writer 串行登记

下面是 NB宇宙项目已有 writer 的调用示例，不属于发布包依赖，也不是任意项目可直接运行的接口；执行前读取项目当前脚本与帮助。路径相对 PROJECT_ROOT，不能相对全局 SKILL_ROOT。

1. 分页读全表，按专题、位置、现象与本轮问题指纹核对同义问题；语义有歧义先保留待核对。跨状态同一问题只登记一次，保留所有相关 case。
2. 新问题创建为“待解决”；同义旧问题只向原 AI 详情追加当前版本、时间与新证据。保留人工正文、旧详情、备注、状态、人员与附件，不调用 verify、不关闭工单、不指定处理人。
3. 唯一 writer 核对人话字段、隐私、record_id 和预览动作。已授权正式登记执行 apply，不重新索要例行许可；授权不能由报告中的“确认修改”按钮推断。

```powershell
python -X utf8 .agents/skills/universe-feedback-audit/scripts/write_findings.py --input findings.json --receipt preview.json
python -X utf8 .agents/skills/universe-feedback-audit/scripts/write_findings.py --input findings.json --receipt receipt.json --apply
```

4. 逐条 record_id/verified=true 与整批 complete=true 经回读成立才称已同步；dry-run complete 仅表示预览完成。再次 dry-run 应全 skip。
5. 超时、权限或回读失败停写，先核对远端标记和回执；保留输入旁 request-ids 幂等编号，不盲重试、不切换身份绕过。
6. 最终分别汇报本地验收覆盖/得分/硬伤以及飞书新增、补充、跳过、未同步数量。证据不保存凭据或全表敏感数据。
