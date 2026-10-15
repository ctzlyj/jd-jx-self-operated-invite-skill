# 运行与恢复

Python 3.10+，无需第三方 Python 包。复用安装好的 WebCLI/Browser Bridge 与本人的 OSW 登录；浏览器仅处理任务专属后台页。未安装工具时由助手按本机 O2 指南安装、检查，不要求同事学习命令。

脚本默认发现 O2。在 Windows 有本机 O2 `scripts/windows_launch.py` 时自动使用其显式 UTF-8/stdio 路由；缺少该覆盖层或使用其他运行环境时，可通过 `--launcher-json` 传入已验证的命令数组。例如 `['python','/实际路径/toolbox.py','run','webcli','--']` 的 **JSON 双引号形式**，或者已核对的 Node + WebCLI main.js 路径。该数组只是 CLI 前缀，脚本自动追加 `browser <session> eval <JS> --tab <id>`。

不要把 Cookie、Token、设备参数放进前缀或查询 JSON。任何 CLI 空输出都不是成功回执；写入结果按未知处理，再回查，禁止因更换前缀重放。脚本不启用 shell，不通过 `cmd /c` 拼接 JavaScript；UTF-8 与中文按 argv 保留。

任务目录至少包含 `snapshot.json`、`state.json`、`result.json`、`result.csv`、`failures.csv`。这些都是本机业务资料，不随 Skill 分发。准备阶段读取页面真实过滤器；总数变化、页码不符、短页、重复 SPU、ERP 不匹配时拒绝提交不完整范围。

正常：`prepare` → `run --apply` → `verify`。`run` 自动先对账，再写未提交项，最后全量回查并输出结果。`verify` 不发邀请；`status` 不访问线上。已有明确失败不会在普通续跑中重复提交；用户要求重试失败时加 `run --apply --retry-failed`。即使重试失败也先回查。

写入前先持久化 `submitting`。宕机、超时或空回执后保留未知状态；续跑先从升级记录核对，未获得可靠结果的未知项继续保留，不再提交。其他明确未提交项可继续。登录失效、账号改变或整批平台权限错误停止后续写入；单项商品业务失败继续其他项。

同一任务通过 `run.lock` 防止同时提交。进程正常退出自动释放锁。若进程异常退出，助手先确认锁中的 PID 已停止，再清除该任务的锁；不要删除业务清单或回执。输出目录不能位于 Skill 目录里。需要改筛选或改目标账号时创建新任务目录，不能覆盖旧断点。

验证源码：`node --test tests/api.test.cjs` 与 `python -m unittest discover -s tests -p 'test_*.py' -v`。测试只用合成数据，包含上万 SPU、混合结果、丢失响应和恢复，不邀请任何真实商品。
