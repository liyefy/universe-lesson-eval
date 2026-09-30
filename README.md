# NB宇宙 Skills

面向科学课程的验收技能。当前仓库只发布 **`universe-lesson-eval`**：先用代码检查确定性要求，再用真实浏览器验证交互，最后让模型处理科学语义、教学逻辑和视觉/听觉判断。

工具负责冻结验收计划、拆分小任务包、校验覆盖与证据、去重评分、生成可批阅的 HTML 报告和问题 JSON。子代理按独立任务和复核需要使用；不会为每条检查创建一个代理，也不会让模型重复计算已由代码确定的结果。

## 依赖

| 能力 | 依赖 | 是否必需 |
| --- | --- | --- |
| 计划、证据、评分、报告、本地导出和安装脚本 | **Python 3.11+**，仅标准库；无需 `pip install` | 必需 |
| 克隆和更新本仓库 | Git；也可下载仓库 ZIP 后解压 | 按安装方式 |
| 让 AI 按技能完成验收 | 支持本地 `SKILL.md` 的宿主，如 Codex；可用的文件和命令工具 | 完整工作流需要 |
| 浏览器断言、截图和实际听音 | 宿主已授权的真实浏览器/媒体工具及可访问的测试页面 | 验对应项时需要 |
| 科学语义、教学充分性和感知判断 | 可用模型；确认含模型判断的缺陷还需独立执行者复核 | 验对应项时需要 |
| 构建、lint、运行 NB宇宙项目 | 项目源码及其现有依赖；NB宇宙当前要求 **Node.js 20.x + pnpm**，以项目当前 `package.json` 和 `AGENTS.md` 为准 | 运行项目检查时需要 |
| R3F、完整响应式、已启用旁白的专项检查 | 项目已有 `r3f-best-practices`、`universe-responsive-ui`、`universe-lesson-tts`，按涉及范围读取 | 可选专项依赖，本仓库不提供 |
| 把问题登记到飞书 | 用户授权、项目已配置的客户端/writer；项目可提供 `feishu-task-runner` 和 `universe-feedback-audit` | 可选；**本地导出不需要** |

本仓库不包含 NB宇宙应用、项目私有规则、其他专项技能、内部反馈表或任何服务凭据。仅使用评分/报告脚本不需要 Node、pnpm、浏览器、飞书或 TTS。技能不会自动生成音频、上传资源、修改课程或登记反馈。

缺少浏览器、规则或专项依赖时，对应验收项保留“未验证”；不能用静态通过冒充实页已验收。评分、缺口和严重问题分别报告；有未验证项时不给完整评级。

## 安装到 NB宇宙项目（推荐）

在任意工作目录克隆独立仓库，然后指定**已经存在的课程项目根目录**：

```powershell
git clone https://github.com/liyefy/nb-universe-skills.git
cd nb-universe-skills
python -B -X utf8 scripts/install.py --project "你的 NB宇宙项目路径"
```

安装结果是 `<项目>/.agents/skills/universe-lesson-eval/`。安装器先校验发布文件清单、哈希和脱敏规则；只复制技能，不修改项目 `AGENTS.md`、源码、其他技能和 `.local` 私有配置。目标已存在时会停止，更新方法见下文。

Windows 可按环境用 `py -3` 代替 `python`；macOS/Linux 可用 `python3`。先确认解释器版本至少为 3.11。私有仓库需要先获得访问权限并完成正常 GitHub 登录，不把令牌写进命令或仓库 URL。

如果团队约定技能只在本机使用，将 `/.agents/skills/universe-lesson-eval/` 加入项目 `.git/info/exclude`；如需团队跟踪则按项目约定处理。安装器不会擅自改动这些约定。

## 安装到个人 Codex 技能目录

在本仓库目录运行：

```powershell
python -B -X utf8 scripts/install.py
```

默认安装到 `$CODEX_HOME/skills/universe-lesson-eval`；未设置 `CODEX_HOME` 时为 `~/.codex/skills/universe-lesson-eval`。也可以通过 `--dest "技能目录"` 指定其他宿主实际识别的目录。

在支持 `skill-installer` 的 Codex 中，也可以直接发送：

```text
使用 skill-installer 安装 https://github.com/liyefy/nb-universe-skills/tree/main/skills/universe-lesson-eval
```

同一项目选择项目安装或全局安装之一，避免两份同名技能版本混用。安装后在下一轮对话调用；宿主未自动发现时，直接让它读取实际安装目录的 `SKILL.md`。全局安装的脚本始终位于实际技能目录，课程源码仍从当前项目读取。

## 项目私有配置

项目根规则、课程原文、专题注册表和公共组件索引仍由课程项目提供。完整接入规则见 [project-setup.md](skills/universe-lesson-eval/references/project-setup.md)。

如果需要固定内部规则位置或反馈目标，在项目中创建 `.local/universe-lesson-eval/config.json`，**先确认该路径被项目 Git 忽略**：

```json
{
  "version": 1,
  "rule_documents": [],
  "feedback_url": null
}
```

`rule_documents` 填你的规则文件路径；可选 `topic_registry`、`shared_index` 填项目相对路径。`feedback_url` 只表示目标，不构成写入授权。不把密码、API 密钥、Token 或 Cookie 放入配置。没有配置时，技能从当前项目规则和用户给定资料解析；不猜维护者的个人目录或内部表。

在项目根验证项目内安装：

```powershell
python -B -X utf8 .agents/skills/universe-lesson-eval/scripts/doctor.py --project . --require-project
```

全局安装时，用实际安装目录替换脚本前缀。`doctor` 只检查技能文件、已配置资料和项目入口是否存在；不会访问外部服务，也不输出私有地址和规则完整路径。`project_ready: true` 不代表专题效果已验收。

## 使用

在课程项目的 AI 对话中发送，例如：

```text
使用 $universe-lesson-eval 验收指定专题。先读取当前项目规则和需求，
冻结范围与节点，先做代码检查，再验真实页面，模型只处理不能确定判断的项。
本次只生成本地报告，不登记飞书。
```

说明专题、实际测试页面和本次范围；音频尚未制作时明确制作阶段。具体命令见 [automation.md](skills/universe-lesson-eval/references/automation.md)，数据格式见 [schema-v2.md](skills/universe-lesson-eval/references/schema-v2.md)。

报告默认存放在课程项目 `.local/universe-evals/<任务ID>/`。报告可能包含源文、页面地址、截图和本机路径，**不会随技能发布**；如需共享实际报告，另行检查内容和授权。HTML 批阅不触发课程修改或远端写入。

报告中选择“确认修改/忽略/暂缓”并填写备注后，点击 **“复制给 AI 执行”**，再粘贴到能读取本机项目文件的 AI 对话。指令包含项目、报告和证据入口的绝对路径、报告哈希及点击时的完整批阅；AI 只接续“确认修改”的问题，没有确认项时先解读报告。无需先下载批阅 JSON，复制权限不可用时可在“查看给 AI 的完整指令”中手动复制。

渲染报告时用 `render_report.py --project "课程项目根目录"` 指明目标项目，其他必填参数见工具说明；省略时使用当前工作目录。跨电脑或纯网页 AI 不能仅凭绝对路径读取本机文件，需要另行提供材料。旧 HTML 不会自动升级，请保留原报告并渲染到新目录。

## 更新与备份

在独立技能仓库中更新，再重新安装：

```powershell
git pull --ff-only
python -B -X utf8 scripts/install.py --project "你的 NB宇宙项目路径" --update
```

全局安装时省略 `--project`；自定义目录则继续使用原 `--dest`。不同版本会先完整备份旧技能，再替换；相同内容保持不变。项目安装的备份位于 `<项目>/.local/skill-backups/`；全局/自定义安装的备份位于技能目录上一级的 `skill-backups/`。备份放在技能发现目录之外，避免宿主重复加载。私有配置不在技能目录中，更新会保留它。

若有自己的技能修改，先比较备份和新版本，再决定迁移哪些修改。恢复时将当前技能目录移到技能发现目录之外，再把安装器返回的备份目录放回原安装位置；不要删除唯一备份。

## 验证与维护

```powershell
python -B -X utf8 scripts/check_release.py
python -B -X utf8 -m unittest discover -s tests -v
python -B -X utf8 -m unittest discover -s skills/universe-lesson-eval/tests -v
```

`release-manifest.json` 是明确的发布文件清单和 SHA-256；新增文件须先审阅并加入清单。修改现有文件后运行 `python -B -X utf8 scripts/check_release.py --refresh` 更新哈希，再运行上述验证。脱敏检查覆盖个人路径、内部飞书地址、常见凭据和未经审阅的 URL；它是辅助检查，不能证明任意文本绝无敏感信息，发布前仍需审阅差异。

GitHub Actions 配置在 Windows/Linux、Python 3.11/3.14 上运行上述检查。测试数据均为合成材料，测试通过只证明工具行为，不代表任何真实课程通过验收。

复制指令的 JavaScript 回归测试另用 Node.js 20+；未安装 Node 时该项会明确跳过，其余 Python 工具仍可独立运行。CI 会检查 Node 可用，确保这一项实际执行。
