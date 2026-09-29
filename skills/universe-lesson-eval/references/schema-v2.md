# 验收 JSON 契约 v2

与 [工具入口](automation.md) 配合使用。文本字段非空，布尔值不能用0/1，数值须有限。下面是字段说明，证据必须来自真实执行。v1 旧报告只走兼容门禁，不自动升级其证据或生成新版得分。

## PLAN 与 LOCK

- PLAN：version=2、audit_id、scope、sources、rules、inventory、cases。
- scope：topic/version/url/environment/build_id 均为非空字符串；coverage 为 full 或 focused，dimensions 为本轮维度列表。full 必须覆盖 science/interaction/motion/viewport/hypothesis 五维；focused 明确子集。每个声明维度必须有 case，无适用内容用有依据的 N/A case 表示。
- build_id 应可核对实际页面构建：部署产物指纹或本地源码/工作区指纹；不能只写“最新版”。运行环境与输入方式记入 environment，音频阶段记入来源与适用性。
- sources：`[{id,path,sha256}]`，path 为 PLAN 目录内非空来源快照的相对路径，sha256 为其实际哈希。snapshot 是本次已确认原文或现有文案底本，不是从结果倒造的期望。
- rules：`[{id,source,version,applicability}]`，source 引用 sources.id；版本和适用条件明确。冲突依据单列裁决；无法裁决的 case 不能记 fail/pass。具体条件有分歧时拆不同 rule ID。
- inventory：`[{node_id,required_rules:[rule_id]}]`；每个节点/规则组合至少有一个 case。按需要增加 `required_variants:[{rule_id,state,viewport:{width,height}}]`，可机械校验已列明的状态/设备组合没有遗漏。该字段不替代人工对原文完整性的核对。
- case：id/title/node/rule_id/source/expected，critical、allow_not_applicable 两个布尔值，dimension、engine、source_ids、required_evidence。source 是人读锚点，source_ids 必须包含本项 rule 引用的来源。critical 保留作风险信息，不是一票否决。
- engine=static 必须要求 code 证据；browser 必须要求 code+blackbox；model 必须提供 model_reason，并要求 analysis 和/或 blackbox，不能仅用 code 代签语义判断。
- required_evidence 是无重复的 code/blackbox/analysis 数组。含 blackbox 时需 blackbox_method（visual/interaction/listening）、state、steps 非空数组、viewport 的有限正数 width/height，单位 CSS px。可选 case.url 覆盖 scope.url。
- allow_not_applicable=true 必须冻结 not_applicable_reason；缺环境和没执行不能写 N/A。音频后置且尚未接入可预先允许声音专属项 N/A，其他内容照常检查。
- freeze 生成 LOCK，绑定 audit、计划哈希、来源快照与冻结时间。修改计划、来源、范围或构建必须新建 audit 和重新执行；锁用于防误改，不是防篡改认证。

## REPORT 与证据

- REPORT：version=2、audit_id、executor、plan_sha256、results、issues。不得手填 score/grade/dimension_scores；得分由 gate 计算。
- result：id/status/reason/evidence，可选 executor 覆盖主代理；status 为 pass/fail/unverified/not_applicable。fail 必须带 issue_id。全部 case 必须有结果，重复或额外 ID 拒绝。
- evidence：kind/path/observation/executor/case_id/plan_sha256/build_id/captured_at/sha256。产物为报告目录内非空文件，路径允许相对或绝对；captured_at 带时区且不早于冻结。封装绑定元数据不代表采集真实性。
- code：path 指向 run_check 实际产生的 version1 记录，audit/plan/case/executor 匹配；超时/启动失败只能支持 unverified，非零退出不能支持 pass。非零还要核对是否断言失败而非工具配置故障。
- blackbox：另带 source/steps/method/state/viewport；实际 URL、状态、视口、方法及 build_id 必须匹配计划。保留模块路由并去凭据；页面重定向或环境偏离先修订计划，不当作产品缺陷。实际步骤文字可以更具体，不要求逐字复制计划。
- analysis：仅用于 model 项，文件保留真实语义判断、依据和范围；不能替代计划要求的运行时 blackbox。听觉不能只提交截图，动态过程不能只提交终态图片。
- pass/fail 均需齐全的计划证据。诊断性失败日志可另外保存；不能把来源不同、元数据不匹配的产物塞成合格证据，缺所需证据保留 unverified。

## 独立问题与复核

- issue：id/fingerprint/case_ids/dimension/severity/summary/actual/expected/impact/review。fingerprint 是已人工归并的稳定问题指纹，重复指纹拒绝；不是只按相似文本自动合并根因。
- issue 的全部 case_ids 必须是引用该 issue_id 的 fail，维度相同；同一问题跨设备/状态只扣一次，各失败结果和证据完整保留。
- severity 为 severe/moderate/minor。门禁计算固定扣分及维度封顶，见 [评分规则](labels.md)。科学/规则争议、环境问题保留 unverified，不能凑成产品扣分项。
- review：method/reviewer/confirmed=true/reason/evidence，evidence 使用上述完整对象并覆盖 issue 所有 case 的必需证据类型；复核产物与初审分开。
- method=rerun 仅限全部 case 为确定性检查，可由同一执行者真实再运行，但必须使用新的产物和更晚的命令开始时间，不能复制初审记录冒充重跑。同一 case 的 command、executable、规范化 cwd、inputs 路径与哈希、stdin 必须匹配首轮；输入列表顺序和每次的时间/耗时/输出不比较。使用不同命令交叉核对时走 independent。
- 任一 case 使用模型判断，则 method=independent；reviewer 与初审 result/evidence 执行者不同，先按中性步骤判断后比对候选结论。复核证据 executor 为 reviewer。身份字符串与哈希不能证明代理独立，主代理保留真实调度回执。
- 可选 code_location={path,line,component,state}：源码为真实绝对路径和存在的1基行号，报告器校验；不能确定根因时省略，不伪造最小 Diff。suggestion 为有依据的最小修正建议。
- 飞书可选字段 kind=product、certainty=confirmed、topic、location、environment、steps、evidence_summary、boundary、record_id，见 [飞书交付](feishu.md)。

## gate 派生输出

valid 表示契约与证据绑定有效；complete 表示所有适用项已有实际结论，不代表无缺陷。coverage 保留范围、维度、预期/已报/已验/未验/N/A数量及覆盖率。score 包含 value/grade/provisional/scope/active_budget/dimensions/deductions；hard_findings 完整列出严重问题。维度预算封顶不移除问题，不把局部评分冒充整课结论。
