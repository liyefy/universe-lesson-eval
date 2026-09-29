# 自动化执行与工具入口

新验收使用 [v2 契约](schema-v2.md)；评分标准见 [labels](labels.md)。工具仅用 Python 3.11+ 标准库，以下命令以项目内安装为例，在 PROJECT_ROOT 执行。全局安装时将 `.agents/skills/universe-lesson-eval` 替换为实际 SKILL_ROOT 的绝对路径，含空格时加引号；不要切到技能目录运行项目检查。定位方法见 [project-setup.md](project-setup.md)。所有输出拒绝覆盖，续跑使用新文件名；合成样例不得上传产品反馈。

## 执行顺序

1. 建立本次报告目录和 sources/，保存实际采用的规则、需求或底本文案快照。依据提取与规则适用性由主代理核对；工具不能从不完整清单推导出遗漏要求。
2. 为 case 选择 `static`、`browser` 或 `model`；能写可靠断言时用前两者。browser 是在真实页面运行代码断言，不等同模型看截图。只有无法确定性判断的项才填写 model_reason 并委派模型。
3. 冻结计划，拆小任务包，先运行确定性检查，再补语义/感知证据。共享页面串行访问，脚本不会自动创建代理。
4. 保存原始输出并封装证据。缺陷按独立问题归并；确定性项独立重跑，模型项由不同执行者复核。所有必要证据不足时保留 unverified。
5. 合并分片，运行门禁，由脚本评分并生成报告。不要让模型手算分数或凭任务总结补造缺项。

```powershell
python -X utf8 .agents/skills/universe-lesson-eval/scripts/report_gate.py freeze PLAN.json LOCK.json
python -X utf8 .agents/skills/universe-lesson-eval/scripts/task_packets.py split --plan PLAN.json --lock LOCK.json --out-dir packets --batch-size 6
```

任务包按 engine、rule_id、blackbox_method 分组，包含相关来源、预期及 case ID；默认每包最多 6 项，可按任务调整。单一规则可覆盖相关节点，不要求每项创建一个代理。packet 源文件路径指向只读快照；原始完整计划由主代理保管。不同 worker 证据存入同一报告根目录下各自子目录。

## 运行代码与自动化黑箱

```powershell
python -X utf8 .agents/skills/universe-lesson-eval/scripts/run_check.py --plan PLAN.json --case-id CASE --executor ACTOR --out run.json --timeout 60 --input SOURCE -- python -X utf8 CHECK.py
python -X utf8 .agents/skills/universe-lesson-eval/scripts/record_evidence.py --plan PLAN.json --case-id CASE --artifact capture.png --metadata observation.json --report-dir REPORT_ROOT --out evidence.json
```

- run_check 的 `--` 后是可执行文件和 argv，不接受 shell 或 cmd/ps1 包装；Windows pnpm 使用符合项目版本要求的 Node 可执行文件和实际 pnpm.cjs 路径。可选 cwd、stdin、input、encoding。不要通过它启动常驻服务。
- RUN 记录命令、输入哈希、时间、输出、退出码、超时/启动失败；命令退出 0 只支持已经审查过的断言。启动失败和超时不判产品缺陷。
- rerun 保持同一命令、可执行文件、目录、输入路径/哈希和 stdin，使用新 RUN 路径真实再执行；不比较时间/耗时/输出。需要不同命令交叉验证时使用 independent。
- 浏览器断言同时保留 code 运行记录与真实 blackbox 产物，记录当时实际 URL、构建标识、CSS 视口、状态及操作；不能调用私有 Store/内部回调来跨过用户操作。浏览器工具支持的公开 UI 断言也属于代码执行，应保存原始工具回执；需要 RUN 格式时用真实执行脚本捕获，不手填假命令。
- 交互只能由浏览器工具完成时，先保存公开 DOM/AX/测量的原始回执，再用 run_check 执行只读脚本，对这些实测值作断言，同时交付真实 blackbox 证据。记录清楚“工具驱动交互、脚本校验采集值”，不能把后者说成驱动过浏览器；不能保存真实回执时保持未验证。
- record_evidence 从已有产物计算哈希和 case/plan 绑定。metadata 提供 kind/executor/observation/build_id/captured_at；blackbox 还提供 source/state/viewport/steps/method，均应来自实际采集。工具不会替你观察，不把计划值自动填成实测值。
- 不能真实听音时 listening 项保持 unverified；音频后置按冻结阶段 N/A，不能用静音截图或媒体事件替代听觉。
- 证据文件应在报告根目录内；采集后冻结产物，截图查看和原始回执核验仍有必要，哈希不证明内容真实。日志和 URL 去凭据。

两个 `--out` 不同：run_check 自己的输出路径每次更新；子命令 argv 必须保持相同。对默认把 JSON 写到 stdout 的 compare_copy，用下列包装即可将完整结果保存进 RUN，无需再给子命令传 `--out`：

```powershell
python -X utf8 .agents/skills/universe-lesson-eval/scripts/run_check.py --plan PLAN.json --case-id CASE --executor ACTOR --out initial-run.json --input COPY.json -- python -X utf8 .agents/skills/universe-lesson-eval/scripts/compare_copy.py COPY.json
python -X utf8 .agents/skills/universe-lesson-eval/scripts/run_check.py --plan PLAN.json --case-id CASE --executor ACTOR --out review-run.json --input COPY.json -- python -X utf8 .agents/skills/universe-lesson-eval/scripts/compare_copy.py COPY.json
```

## 合并与门禁

每份 shard 提供 version=2、audit_id、plan_sha256、executor、results、issues。路径全部相对最终 REPORT.json 所在目录，不能相对 worker 分片位置。相同问题由主代理显式归并成一个 issue，多个失败 case 引用同一 issue_id；不要让每包各扣一次。

```powershell
python -X utf8 .agents/skills/universe-lesson-eval/scripts/task_packets.py merge --plan PLAN.json --lock LOCK.json --part worker-a.json --part worker-b.json --executor MAIN --out REPORT.json
python -X utf8 .agents/skills/universe-lesson-eval/scripts/report_gate.py check PLAN.json REPORT.json LOCK.json
```

重复/额外结果、跨版本分片和重复 issue 均拒绝。默认缺项拒绝合并；只有显式 `--allow-incomplete` 才将未交付 case 填为“未收到执行结果”的 unverified，不补通过。门禁无效的合并产物保留供诊断，修订使用新文件。

v2 退出码：0=报告有效且适用项均已检查（可以有已确认缺陷）；1=报告有效但有未验证；2=契约/证据无效。分别查看 valid、complete、coverage、score、hard_findings，退出 0 不代表无缺陷或授权发布。v1 保留原 accepted/退出码语义，仅用于读取旧报告，不作为新版完整验收。

PowerShell 的外层工具有时把所有非零原生命令映射成退出1；需区分时读取命令后的 `$LASTEXITCODE`，或在单命令调用末尾显式 `exit $LASTEXITCODE`。记录原始脚本码，不把外层返回码误报成 gate 契约。

## 文案对照

```powershell
python -X utf8 .agents/skills/universe-lesson-eval/scripts/compare_copy.py COPY.json --out copy-result.json
```

COPY 保留 `{version:1,comparisons:[{id,source:{anchor,paragraph},expected,actual,actual_origin}]}`；actual 可空。默认逐字符对照；显式 --layout-whitespace 仅折叠布局空白，保留数字、单位、否定词和标点。退出 0=相同、1=差异候选、2=输入错误，始终不宣称 runtime_verified。

`prohibited_terms` 是历史兼容的候选词表字段；可配置全局及每行 `approved_terms` 白名单。词典命中仅提供上下文候选及 present_in_expected，不自动判“未经课标授权”。`--max-clause-length` 是本轮来源适用范围内的扫描参考值（默认18），警告不直接计分；缺失 actual 不改为检查 expected。此工具接收已提取文本，不解析 JSX 或替代真实页面采集。

## 验证工具自身

```powershell
python -B -X utf8 -m unittest discover -s .agents/skills/universe-lesson-eval/tests -v
```

测试是本地合成契约与短命令，不等于专题实页验收。工具升级增加可复现的误判/漏检边界用例；独立前向试跑只给真实请求和最少原始材料，不透露预期答案。
