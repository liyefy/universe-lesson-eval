# NB宇宙 Skills

`universe-lesson-eval`：先查代码，再验真实页面，模型处理科学语义、教学逻辑和感知判断；生成带证据和批阅功能的本地报告。

## 依赖

| 用途 | 依赖 |
| --- | --- |
| 安装、计划、证据校验、评分与报告 | **Python 3.11+**，仅标准库，无需 `pip install` |
| 下载和更新技能 | **Git**、可访问 GitHub 的网络；本仓库公开，下载与安装无需注册或登录 GitHub |
| AI 执行验收 | 能读取本地文件、执行命令的 AI 宿主（如 Codex），以及课程项目源码和当前项目规则 |
| 页面、截图、音视频验收 | 宿主可用的真实浏览器/媒体工具，以及可访问的测试页面 |
| 构建、lint、运行 NB宇宙 | 项目现有依赖；当前为 **Node.js 20.x + pnpm**，以项目 `package.json` 和 `AGENTS.md` 为准 |
| 专项检查（按需） | 项目提供的 `r3f-best-practices`、`universe-responsive-ui`、`universe-lesson-tts`；飞书登记另需已授权的客户端或 writer |

本仓库只提供验收技能。项目规则、其他专项技能和私有配置由课程项目提供，接入方式见 [项目配置说明](skills/universe-lesson-eval/references/project-setup.md)。缺少对应工具或资料的检查项会标为“未验证”；仅使用 Python 评分/报告脚本不需要 Node、pnpm、飞书或 TTS。

## 安装与使用

### 方式一：复制一段话给 AI

在**课程项目的 AI 对话**中复制下面整段，AI 会检查依赖、安装并自检；对话已有专题和测试入口时继续验收，否则在安装完成后提示补充。

```text
请将 https://github.com/liyefy/universe-lesson-eval 中的 universe-lesson-eval 安装到当前课程项目并使用。先确认项目根目录、读取项目规则，检查 Python 3.11+、Git 和仓库连通性；复用已有克隆或通过 HTTPS 匿名克隆到课程项目之外，再用仓库的 scripts/install.py --project "实际项目根目录" 安装，已安装时使用 --update 保留备份，保护现有改动和 .local 私有配置。该仓库公开，下载与安装无需 GitHub 账号或 Token。安装后读取项目 .agents/skills/universe-lesson-eval/SKILL.md，并运行其中 scripts/doctor.py --project "实际项目根目录" --require-project。若本对话已经明确专题、测试入口和范围，继续用这个技能验收：先代码、再真实页面，模型只处理剩余判断；否则先完成安装，再提示我补充这些信息。生成本地 HTML 报告，展示实际采集的证据图片和可播放音视频，并提供报告绝对路径与“复制给 AI 执行”入口。本次只安装和验收，课程修复、飞书登记、音频生成和远端发布按后续明确授权处理。
```

### 方式二：传统命令

在课程项目之外克隆，替换下面的项目路径后运行：

```powershell
git clone https://github.com/liyefy/universe-lesson-eval.git
cd universe-lesson-eval
python -B -X utf8 scripts/install.py --project "你的课程项目根目录"
```

然后进入课程项目，自检并在该项目的 AI 对话中使用：

```powershell
cd "你的课程项目根目录"
python -B -X utf8 .agents/skills/universe-lesson-eval/scripts/doctor.py --project . --require-project
```

```text
使用 $universe-lesson-eval 验收「专题名称」，测试地址是「实际页面地址」，范围是「整课或指定节点」。本次生成本地报告；音频尚未制作时按音频后置阶段检查。
```

宿主未自动发现技能时，让 AI 直接读取项目 `.agents/skills/universe-lesson-eval/SKILL.md`。Windows 可用 `py -3`，macOS/Linux 可用 `python3`，均需确认版本至少为 3.11。`doctor` 通过只表示安装和资料入口就绪，不代表课程已验收。

更新时回到独立技能仓库运行；安装器会先备份不同版本，保留项目私有配置：

```powershell
git pull --ff-only
python -B -X utf8 scripts/install.py --project "你的课程项目根目录" --update
```

报告位于课程项目 `.local/universe-evals/<任务ID>/`。打开 **`report.html`** 可直接看证据图片、播放录屏和音频；选择“确认修改/忽略/暂缓”并填写备注后，点击 **“复制给 AI 执行”**，粘贴到能读取本机项目的 AI 对话即可接续。复制内容包含绝对路径和当前批阅，只接续确认修改项；纯网页 AI 或另一台电脑需另外提供文件。分享报告时保留报告与证据目录的相对结构，并先检查其中的项目私有内容。
