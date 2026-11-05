# 运行与恢复

Python 3.10+，无需第三方 Python 包。复用安装好的 WebCLI/Browser Bridge 与本人的 OSW 登录；浏览器仅处理任务专属后台页。未安装工具时由助手按本机 O2 指南安装、检查，不要求同事学习命令。

## 首次自检（doctor）

```text
python scripts/invite.py doctor
```

逐项检查并输出 JSON：Python 版本（`python`）、O2 命令（`o2`）、WebCLI/浏览器桥接（`webcli`）、任务目录可写性（`task-dir`，默认 `~/jx-invite-tasks`，可用 `--state-dir` 指定）、ERP 登录（`erp-login`）。浏览器检查自动开任务专属后台标签 `https://osw.jd.com/cz/bundling/pop2Self/jxCenter`，读取真实登录接口中的 ERP 后立即释放标签，不触碰工作浏览器。全部 `ok: true` 才继续 prepare；任何失败项的 `next` 字段给出采销可直接照做的下一步（含缺 O2 时的 pip 安装命令）。

脚本默认发现 O2。在 Windows 依次在 `~/.joycode/skills`、`~/.codex/skills`、`~/.agents/skills`、`~/.claude/skills` 下查找 O2 Skill 的 `scripts/windows_launch.py`（目录名 `o2`，或 `skill-<id>` 目录中 SKILL.md frontmatter `name: o2`），找到且同环境有 `python.exe` 时自动使用其显式 UTF-8/stdio 路由；**找不到时直接使用 `o2 launch webcli` 命令**，不依赖任何特定安装位置。O2 命令本身缺失时给出 pip 安装提示并停止。需要覆盖自动发现时，可通过 `--launcher-json` 传入已验证的命令数组。例如 `['python','/实际路径/toolbox.py','run','webcli','--']` 的 **JSON 双引号形式**，或者已核对的 Node + WebCLI main.js 路径。该数组只是 CLI 前缀，脚本自动追加 `browser <session> eval <JS> --tab <id>`。

不要把 Cookie、Token、设备参数放进前缀或查询 JSON。任何 CLI 空输出都不是成功回执；写入结果按未知处理，再回查，禁止因更换前缀重放。脚本不启用 shell，不通过 `cmd /c` 拼接 JavaScript；UTF-8 与中文按 argv 保留。

任务目录至少包含 `snapshot.json`、`state.json`、`result.json`、`result.csv`、`failures.csv`。这些都是本机业务资料，不随 Skill 分发。准备阶段读取页面真实过滤器；总数变化、页码不符、短页、重复 SPU、ERP 不匹配时拒绝提交不完整范围。

正常：`prepare` → `run --apply` → `verify`。`run` 自动先对账，再写未提交项，最后全量回查并输出结果。`verify` 不发邀请；`status` 不访问线上。已有明确失败不会在普通续跑中重复提交；用户要求重试失败时加 `run --apply --retry-failed`。用户要求看板清零时加 `run --apply --resend`，只重发仍显示在看板上的待升级（40/99）商品。即使重试或重发也先回查。

写入前先持久化 `submitting`。宕机、超时或空回执后保留未知状态；续跑先从升级记录核对，未获得可靠结果的未知项继续保留，不再提交。其他明确未提交项可继续。登录失效、账号改变或整批平台权限错误停止后续写入；单项商品业务失败继续其他项。

同一任务通过 `run.lock` 防止同时提交。进程正常退出自动释放锁。若进程异常退出，助手先确认锁中的 PID 已停止，再清除该任务的锁；不要删除业务清单或回执。输出目录不能位于 Skill 目录里。需要改筛选或改目标账号时创建新任务目录，不能覆盖旧断点。

验证源码：`node --test tests/api.test.cjs` 与 `python -m unittest discover -s tests -p 'test_*.py' -v`。测试只用合成数据，包含上万 SPU、混合结果、丢失响应和恢复，不邀请任何真实商品。
