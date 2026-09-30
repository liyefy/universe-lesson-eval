# 项目与安装位置

本技能可装在项目目录或用户技能目录，不能通过固定数量的 `../` 推断当前项目。

- `SKILL_ROOT`：本次实际加载的、包含 SKILL.md 的目录；所有 scripts/references/assets 相对它解析。
- `PROJECT_ROOT`：本次用户指定的项目根目录或当前仓库根目录；项目根 `AGENTS.md`、更近层级规则、源码和日志命令相对它解析。不要把独立的技能发布仓库当成课程项目。
- 项目文件、外部规则及相关技能只从用户指定或当前项目已确认的位置读取；不扫描其他项目、凭据或私人会话。

## 项目本地配置

如项目有未公开规则或反馈目标，读取 `PROJECT_ROOT/.local/universe-lesson-eval/config.json`。这是项目私有配置，不随技能安装、更新或发布同步。格式：

```json
{
  "version": 1,
  "rule_documents": [],
  "feedback_url": null
}
```

`rule_documents` 填项目相对路径或本机绝对路径；按需增加 `topic_registry` 与 `shared_index` 指向项目相对的专题注册表和公共能力索引。`feedback_url` 仅记录用户指定的目标，不代表写入授权。不在这里保存密码、API 密钥、访问令牌或 Cookie；外部服务使用正常授权渠道。

先确认本地配置已被项目 Git 忽略，再写入私人路径或内部地址。没有配置时，从用户给定资料和项目规则解析，不猜另一位维护者的电脑目录或默认飞书表。缺失依据只影响依赖它的项，记未验证，不虚构规则。

## 项目能力与按需依赖

- 根 `AGENTS.md`、专题注册表、公共组件索引、需求和语言/设计规则由项目自己提供，发布包不包含这些私有资料。
- 项目要求 RCL/logs 时执行其现有命令；独立运行合成工具测试时不伪造项目日志。执行前核对 package.json 中实际脚本与 Node 引擎版本。
- 审查 R3F、完整响应式或已接入音频时，使用项目现有 `r3f-best-practices`、`universe-responsive-ui`、`universe-lesson-tts`。在项目 `.agents/skills/` 或宿主实际技能目录查找；缺失且为该项所必需时说明依赖，保留未验证，不自行安装未知来源。
- 核心工具、PNG 测量和 JSON 导出只用 Python 3.11+ 标准库，不依赖上述技能或任何飞书客户端。JPEG/WebP 像素测量及其门禁复算需要可选的 Pillow；没有解码器时标为未验证。自动化黑箱需要宿主已允许的浏览器工具；模型判断需要可用模型。缺少工具不能补造证据。
- 飞书写入另依赖项目已配置并获授权的客户端与 writer，见 [feishu.md](feishu.md)；仅本地导出无需任何凭据。

```powershell
# 在项目根运行；全局安装时用实际 SKILL_ROOT 替换脚本前缀。
python -B -X utf8 .agents/skills/universe-lesson-eval/scripts/doctor.py --project . --require-project
```

doctor 仅检查依赖和已配置资料是否存在，不验证浏览器、科学内容或登录状态，也不输出内部地址及规则完整路径。
