# 修改与发布回执

本轮源码、镜像和 19460 发布已完成。初次生产切换申请被自动审批审查拒绝；用户随后明确授权发布本次候选，按授权完成备份和正式切换。

## 版本

- 本地服务器提交：`d04384bd5833102325ad1edae9b8296e9531472f`
- 分支：`codex/adaptive-dialogue`，工作区 `/root/PeiXianDB/adaptive-dialogue`。
- 候选镜像：`peixian-control:adaptive-dialogue-20260924`
- 镜像 ID：`sha256:38445d44614b258ea3931c90f359f66eda9d6a9e3cbc19451c25901cd73f1620`
- 线上已切换 `peixian-control:adaptive-dialogue-20260924`；原 r2 镜像保留回退。
- Gateway、Agent、前端均未切换；无 GitHub 推送。

## 验证

候选源码修复与插件测试 25 通过；相同用例在实际候选镜像中 25 通过。其他问答、表格、前端接口测试 29 通过，16 个既有跳过不算通过。

扩大回归有 3 个既有失败：旧版评分默认值断言；两个 schema v6 测试夹具接口失败。全部已在未修改的 r2 基线源码中复现，不作为本轮通过项。

本机测试初次因未设置模块路径、缺少 argon2 依赖未运行；随后使用服务器匹配镜像的隔离容器。容器挂载路径首次不符合夹具层级，调整为完整只读仓库后运行。新增完整调度测试首次因夹具未授权 question 失败，补齐与实际原生配置一致的授权后通过。没有为通过测试放宽执行授权。

新旧镜像的 833 个静态文件哈希完全一致，清单摘要 `51d09ffa1bb44d279e237989545a4312c99c94a0bcdcb375952baa378597ac9a`。

模型请求：0；真实供应方请求：0；双账号浏览器与模型整体验收：未执行。已上线声明仅覆盖匹配镜像发布与运行检查；不能表述为完整模型行为或真实供应方链路验收通过。

## 发布与运行核查

第一次实际切换后，Control 启动恢复机制把两个账号置为待恢复，直接恢复 normal 被拒绝；脚本回退 r2。随后进入 repair_only，由原 Worker 完成恢复，再恢复 normal。第二次按“切换 → repair_only 恢复 → normal”发布成功，未绕过环境校验，也未恢复旧数据库覆盖新记录。

发布后核查：

- Control 镜像和源码身份匹配；新提示词 SHA-256 为 `766ef1dec1711bcbd8571cd0761d963c7658d479ae7d4688fc73790e631373be`。
- maintenance=normal；Worker=active。
- A/B 均 ready/open、recovery_required=0；配置版本分别 74、46，各有 8 个插件。
- HTTPS 首页 200；未登录 /api/console/v1/me 为 401。
- HTTP 实际返回的 index、JS、CSS 哈希与 r2 一致，页面样式未改。
- 浏览器工具启动失败（trusted Node process exited unexpectedly），未取得页面交互或双账号模型对话的验收证据。

备份与日志在 `/srv/peixian-adaptive-dialogue-20260924`；包含两次切换前的匹配配置、完整 SQLite 在线备份、网络信息、构建和发布日志。备份 integrity_check=ok。受保护备份不纳入本地交付 ZIP。

新策略从后续新 Run 生效，已有会话可继续，新 Run 会继承可用任务上下文。旧 Run 不补写、不重算，旧失败标记不自动消失。

回退应恢复 r2 Control 与对应 Compose/platform 配置，重接管理网络，通过 repair_only 等待 Worker 恢复再转 normal；不覆盖数据库、不删数据卷。Gateway 与账号插件版本不变。
