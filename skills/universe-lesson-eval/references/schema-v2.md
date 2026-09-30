# 验收 JSON 契约 v2

与 [工具入口](automation.md) 配合使用。文本字段非空，布尔值不能用0/1，数值须有限。下面是字段说明，证据必须来自真实执行。v1 旧报告只走兼容门禁，不自动升级其证据或生成新版得分。

## PLAN 与 LOCK

- PLAN：version=2、audit_id、scope、sources、rules、inventory、cases。
- scope：topic/version/url/environment/build_id 均为非空字符串；coverage 为 full 或 focused，dimensions 为本轮维度列表。full 必须覆盖 science/interaction/motion/viewport/hypothesis 五维；focused 明确子集。每个声明维度必须有 case，无适用内容用有依据的 N/A case 表示。
- build_id 应可核对实际页面构建：部署产物指纹或本地源码/工作区指纹；不能只写“最新版”。运行环境与输入方式记入 environment，音频阶段记入来源与适用性。
- sources：`[{id,path,sha256,node_ids?}]`，path 为 PLAN 目录内非空来源快照的相对路径，sha256 为其实际哈希。snapshot 是本次已确认原文或现有文案底本，不是从结果倒造的期望。full 的课程底本必须带 `node_ids`，从原始需求/课程逐节点提取，不能从已选 cases 反推；所有来源的节点并集必须与 inventory 一致。工具只校验两份清单一致，不能证明提取没有遗漏原文。
- rules：`[{id,source,version,applicability}]`，source 引用 sources.id；版本和适用条件明确。冲突依据单列裁决；无法裁决的 case 不能记 fail/pass。具体条件有分歧时拆不同 rule ID。
- inventory：`[{node_id,required_rules:[rule_id]}]`；每个节点/规则组合至少有一个 case。按需要增加 `required_variants:[{rule_id,state,viewport:{width,height}}]`，可机械校验已列明的状态/设备组合没有遗漏。该字段不替代人工对原文完整性的核对。
- case：id/title/node/rule_id/source/expected，critical、allow_not_applicable 两个布尔值，dimension、engine、source_ids、required_evidence。source 是人读锚点，source_ids 必须包含本项 rule 引用的来源。critical 保留作风险信息，不是一票否决。
- engine=static 必须要求 code 证据；browser 必须要求 code+blackbox；model 必须提供 model_reason，并要求 analysis 和/或 blackbox，不能仅用 code 代签语义判断。
- required_evidence 是无重复的 code/blackbox/analysis 数组。含 blackbox 时需 blackbox_method（visual/interaction/listening）、state、steps 非空数组、viewport 的有限正数 width/height，单位 CSS px。可选 case.url 覆盖 scope.url。
- allow_not_applicable=true 必须冻结 not_applicable_reason；缺环境和没执行不能写 N/A。音频后置且尚未接入可预先允许声音专属项 N/A，其他内容照常检查。
- freeze 生成 LOCK，绑定 audit、计划哈希、来源快照与冻结时间。修改计划、来源、范围或构建必须新建 audit 和重新执行；锁用于防误改，不是防篡改认证。

## 视觉覆盖门槛

full 以及使用 `VIEW-01`、`VIEW-02`、`VIEW-03` 的 focused 计划必须声明 `scope.visual_contract_version=1`。旧 v2 缺少该声明时明确拒绝冻结和完整认证；旧文件保留供诊断，需要重新冻结新的 audit 并实际采集，不能只补字段继承旧成绩。其他 focused 静态/语义检查继续兼容。v1 仍可读取，`accepted` 不代表 v2 完整认证。

- full 的 `scope.viewports:[{width,height}]` 必须包含 1024×768，其他尺寸按已确认范围列明，禁止重复；focused 可以只列本次实际视口。
- full 的每个 inventory 节点必须有 `visual_requirements` 中的三项 `VIEW-01/02/03`，包括不适用项。focused 仅需声明本次引用的三项规则，不扩张成全课审查。每项为 `{rule_id,applicable,source_ids,rationale}`，适用性必须引用冻结规则来源；full 还须引用含本节点 `node_ids` 的课程来源。三项也要列入该节点的 `required_rules`。
- 有适用视觉要求的节点提供 `visual_states:[{state,panel,phase}]`。state 是能从公开 UI 到达的具体状态；panel 取 `open/closed/none/transition`；phase 取 `default/terminal/transition`。full 必有默认状态，存在关键科学终态、面板过渡或反向开关时列出具体状态；不存在某类过程时用 `visual_exclusions:[{phase,source_ids,rationale}]` 冻结依据，仅允许排除 terminal/transition，不要求静止课程凭空加入运动。
- full 中适用的 VIEW-02 必须同时覆盖 panel=open 与 closed。每个适用 rule × visual_states × scope.viewports 均必须有 case；删除任何一个已声明节点、面板状态或尺寸的 case 都会拒绝冻结。声明同一状态下的多个观测点时使用不同 state 名称。focused 仅认证实际列出的 case，`full_certification` 始终为 false。
- 适用三项视觉命题的 case 必须为 `engine=browser`、`dimension=viewport`、`required_evidence=["code","blackbox"]`、`blackbox_method=visual`，state 与视口属于冻结清单，且 `allow_not_applicable=false`。代码中的类名、`<View>`、CSS 子串、世界包围盒或 Canvas 外框均不能代签渲染效果；把 engine 改成 static/model 会拒绝冻结。
- full 的整个 viewport 维度（包括 VIEW-04/07 等其他呈现规则）也必须包含真实 blackbox：确定性检查采用 browser/code+blackbox，感知判断采用 model/blackbox，可加 analysis。除明确冻结的三项视觉 N/A 外，不接受 static case 作为完整视觉结论。调用链静态检查保存为 browser case 的辅助 code 产物；focused 可单列限定源码命题的非三项规则检查，但不能升级为整课认证。
- 不适用项必须冻结 `applicable=false` 和科学/产品依据；对应 case 的 `allow_not_applicable=true`、`not_applicable_reason` 与 rationale 相同，结果仅可为 not_applicable/unverified。浏览器不可用、未执行或来源争议不是 N/A。
- 适用 case 的 `viewport_assertions` 冻结量化阈值，由 `check_viewport.validate_assertions` 统一校验；运行后不能调整阈值来得到通过。VIEW-01 使用盒模型容差、背景参考颜色及四边像素阈值，VIEW-02 使用主体像素识别范围和中心容差，VIEW-03 使用主体识别范围和安全边距。具体字段、单位及未验证条件见 [viewport.md](viewport.md)。

以下是一个静态场景节点的矩阵片段，适用性的具体依据必须来自本次来源；不是所有课程都使用这组状态：

```json
{
  "visual_states": [
    {"state":"panel-open","panel":"open","phase":"default"},
    {"state":"panel-closed","panel":"closed","phase":"default"}
  ],
  "visual_exclusions": [
    {"phase":"terminal","source_ids":["lesson"],"rationale":"本节点是固定观察画面，没有独立科学终态"},
    {"phase":"transition","source_ids":["lesson"],"rationale":"来源确认此节点没有可操作的动画过渡"}
  ]
}
```

## REPORT 与证据

- REPORT：version=2、audit_id、executor、plan_sha256、results、issues。不得手填 score/grade/dimension_scores；得分由 gate 计算。
- result：id/status/reason/evidence，可选 executor 覆盖主代理；status 为 pass/fail/unverified/not_applicable。fail 必须带 issue_id。全部 case 必须有结果，重复或额外 ID 拒绝。
- evidence：kind/path/observation/executor/case_id/plan_sha256/build_id/captured_at/sha256。产物为报告目录内非空文件，路径允许相对或绝对；captured_at 带时区且不早于冻结。封装绑定元数据不代表采集真实性。
- code：path 指向 run_check 实际产生的 version1 记录，audit/plan/case/executor 匹配；超时/启动失败只能支持 unverified，非零退出不能支持 pass。非零还要核对是否断言失败而非工具配置故障。
- blackbox：另带 source/steps/method/state/viewport；实际 URL、状态、视口、方法及 build_id 必须匹配计划。保留模块路由并去凭据；页面重定向或环境偏离先修订计划，不当作产品缺陷。实际步骤文字可以更具体，不要求逐字复制计划。
- analysis：仅用于 model 项，文件保留真实语义判断、依据和范围；不能替代计划要求的运行时 blackbox。听觉不能只提交截图，动态过程不能只提交终态图片。
- pass/fail 均需齐全的计划证据。诊断性失败日志可另外保存；不能把来源不同、元数据不匹配的产物塞成合格证据，缺所需证据保留 unverified。

三项视觉 code 证据的 RUN.stdout 必须是 `check_viewport` 的结构化输出：

```text
{kind:"viewport-check", version:1, rule_id, node_id, state, viewport, source, build_id,
 checks:[{id,passed,actual,expected}], measurement:{host,scene,available,subject,edges},
 screenshot:{path,sha256}, measurement_artifact:{path,sha256}}
```

- 截图和原始 DOM 测量 JSON 都位于报告/PLAN 根目录内，绑定路径相对此根目录，且必须作为实际 `run_check --input` 输入。截图同时作为同 case 的 blackbox 原始图片证据；支持 PNG，以及检查器解码能力可用时的 JPEG/WebP，按真实字节识别，不依赖扩展名。只给 HTML、类名文本或无测量截图不能通过。
- 原始测量 JSON 保留实际 `source/build_id/node_id/state/viewport/captured_at` 以及公开 DOM 几何和截图路径。采集发生于 freeze 之后、离线断言执行之前。scope、case、raw、stdout、blackbox 的来源、状态、视口及构建必须匹配。
- host/scene/available 为 CSS 像素 `{x,y,width,height}`；subject 另带测量 method。VIEW-01 必须有四边盒模型与像素断言、`edges:[{side,samples,non_background_fraction}]`；VIEW-02 必须有实测主体与可用区、水平中心断言；VIEW-03 必须有主体四向安全边距断言。必需断言 ID 由检查脚本统一导出。容器矩形不代表实际画面覆盖。
- gate 还会用已绑定的原始测量 JSON、原始图片与冻结 PLAN 调用同一只读检查器重新计算，核对 RUN.stdout 的 checks、measurement 和 status。不能只构造 `viewport-check` 形状或把 `passed` 改为 true；actual、expected 或测量摘要与重算不一致时拒绝认证。重算不能可靠识别图像时仍为未验证，不把不确定结果写成产品缺陷。
- 工具驱动公开 UI、保存真实测量回执，再用只读脚本断言是允许路径；必须准确记录分工。三项像素/几何 profile 是有明确适用边界的测量适配器，不能证明所有科学主体都能用 RGB 分割；无法可靠测量即保持未验证，不放宽阈值或伪造框。图片内容与原始回执仍需观察核对，哈希和 schema 不能证明采集真实性、科学语义或执行者独立。

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

valid 表示契约与已提交证据绑定有效；complete 表示所有适用项已有实际结论，不代表无缺陷。缺少运行渠道、证据文件、命令未成功执行、只有源码断言或没有必需视觉测量时，原始 pass 会派生为 unverified；不伪造成产品 fail。原 REPORT 不改写，`derived_results` 保留 `reported_status/status/reason/diagnostics`，顶层 diagnostics 列出降级原因；覆盖、评分及 HTML/Markdown 都使用派生结论。已有证据的绑定错误、哈希漂移、非法计划仍为 invalid。声称 fail 的产品问题仍须完整执行证据和复核，不将诊断日志导出为确认缺陷。

coverage 保留范围、维度、预期/已报/已验/未验/N/A 数量及覆盖率。score 包含 value/grade/provisional/scope/active_budget/dimensions/deductions；存在未验证即无等级，全部未验证时无分数。`full_certification=true` 仅用于合法 full、所有项已验、无确认缺陷且至少一项实际通过；focused 和 v1 均为 false。hard_findings 完整列出严重问题。维度预算封顶不移除问题，不把局部评分冒充整课结论。
