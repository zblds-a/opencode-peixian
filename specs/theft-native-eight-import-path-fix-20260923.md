# 盗窃助手提示词加载路径与匹配镜像修正记录（2026-09-23）

## 发现与影响

在回答“系统提示词保存在哪里”时，对正在运行的 Control 容器执行了实际 Python 模块导入检查。初次八插件镜像将更新后的代码复制到 `/app/control` 和 `/app/gateway`，但镜像的工作目录与 Python 导入路径仍为 `/candidate`。因此初次部署的运行进程实际加载旧版 `/candidate/control/agents/profiles/theft_prompt.md`；`/app` 中的新提示词虽与服务器源码一致，却没有被运行进程使用。初次发布记录中关于“新原生执行链路已经随镜像运行”的表述不能单凭包目录和环境 `ready` 成立。

发现时的 SHA-256：服务器分支及容器 `/app` 盗窃提示词均为 `d46eb8f6c2909808a597faf3dba87b03b9b5301d6999739fa867505c4c9198c2`；运行导入目录 `/candidate` 为 `6acfc61d2d7f757b7870e331444a2e5bc9e7afc98a6782b1d53eb7b67863b244`。前者为新版 2.0.0 自然语言和八工具规则，后者为旧版固定方法规则。

## 修正

源码提交 `e7c9452b6c5d1ed60ec57349f1fb1751ddad9e05` 将两个匹配 Dockerfile 的复制目标改为运行时实际导入目录 `/candidate/control`、`/candidate/gateway` 和 `/candidate/shared`。新镜像在无网络、无持久卷的隔离容器中完成 Control/Gateway 应用导入；Control 导入的 `registry.py`、新 `data_plugin_policy.py` 位于 `/candidate/control`，盗窃提示词 SHA-256 与服务器源码一致。

| 当前运行组件 | 镜像摘要 |
|---|---|
| Control | `sha256:f62199e15bf6b8fa4d689efca4d06b88b7e6153bbea686c81cb9c59b24e23b5b` |
| 两个普通测试账号的 Gateway | `sha256:6ff10ebfeded2dbee34faa4dc5bd23bb194032bdaaf2bb6be20cd4d6f5a735bf` |

发布前私有配置检查点位于 `/srv/peixian-eight-stage-20260923/platform.pre-import-fix.json`；数据库在线副本位于同目录 `control.pre-import-fix.sqlite3`，`quick_check=ok`，创建时包含 182 条业务 Run，SHA-256 为 `f49e1f348c295cdf721d5dcd175a95b602f08228b846a45f336592f0e439fd09`。此前完整备份仍保留。

目标站点镜像与容量检查通过。无在途 Run 和环境任务时暂停 Worker、原子更新平台镜像摘要、执行原有 `platform-manage.py up`，确认 Control 已加载新提示词后恢复 Worker。账号 A、B 依次通过现有 `apply` 状态机更新；最终两项任务均为 `succeeded`，环境均为 `ready`，两个 Gateway 的实际镜像摘要一致。站点首页 HTTP 200。前端源码和静态资源未修改。

## 运行路径与版本边界

- 可编辑服务器源码：`/root/PeiXianDB/eight-data-tools/services/peixian-control/control/agents/profiles/theft_prompt.md`。
- 当前 Control 容器实际读取的发布副本：`/candidate/control/agents/profiles/theft_prompt.md`。容器中的 `/app` 副本不再作为运行依据。
- `theft.json` 在同一 `profiles` 目录，声明助手 ID、版本和 `prompt_file`；`agents/registry.py` 按此绑定读取文件，`agents/runtime.py` 将平台规则与助手提示词组合到本轮请求。
- 规划器 `control/theft_planner.py`、统一语言规则 `control/scenario_context.py`、受控回答规则 `control/controlled_answer.py` 另有各自的内置约束；某轮冻结请求还包含本轮任务和范围信息。因此单个 Markdown 文件不是一轮请求全部最终 system 内容。
- 修改服务器工作树文件不会热更新正在运行的容器；必须构建匹配镜像并按环境更新流程发布。

本次验证证明了**运行镜像加载新源码和两账号环境切换**。模型在实际用户对话中是否选择八工具、是否完成意图核对和来源展示，仍需单独的用户级联调；供应方真实接口和非空双链路验收仍未完成。
