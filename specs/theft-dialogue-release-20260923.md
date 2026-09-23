# 盗窃助手对话简化发布与验收记录（2026-09-23）

## 版本与范围

- 服务器仓库：`/root/PeiXianDB/stage2-task-spec-v1`，分支 `codex/theft-dialogue-simplification`，镜像源码提交 `cbb50b9695ced592fa18bb812a20d30a4370e664`。
- 发布镜像：`sha256:d948d79011280a79bf5b66b7ccb03f127ba6b3513d9b53d40f129c80d139f7ce`；继承发布前镜像，仅覆盖匹配的 Control、共享代码与前端静态资源。运行时使用 `/candidate` 路径。
- 站点：`https://36.134.45.38:19460/`，只重建 `peixian-alignment-20260917-console`；HTTPS 入口、两个账号的 Agent／Gateway／Relay 环境和数据卷未重建。
- 数据库仍为 schema v11；本次没有执行迁移。发布前建立 SQLite 一致性备份及原 Compose 配置副本，位于服务器私有目录 `/srv/peixian-alignment-20260917/backups/dialogue-20260923-1/`。备份不进入 Git。

## 验证

- 前端：84 项测试通过；`tsc --noEmit` 和 Vite 构建通过。构建仍提示上层 Bun tsconfig 缺失及大代码块，不影响本次构建退出状态。
- 后端定向：规划、任务、Run 和 OpenAPI 共 33 项通过。全量测试 1,055 项通过；另 16 项因测试容器起初缺少 Node 而失败，补齐 Node 后该文件 16/16 通过。图谱文件测试 26/26 通过。上述测试使用隔离测试容器与合成资料，没有调用真实资料接口。
- 镜像装配：容器从 `/candidate/control/app.py` 加载；线上 OpenAPI 3.1.0 提供 `POST /api/console/v1/sessions/{sid}/runs/{rid}/clarification/reject`；未经认证请求返回 401。
- 站点：HTTPS 根页面返回 200，引用的前端 JS 与镜像静态目录一致；Control、HTTPS 入口和两个账号运行容器均健康，Control 重启次数为 0。复核时四个账号仍在、两个 Runtime 为 ready，未见在途 Run。
- OpenAPI 文件 SHA256：`8a5963df0da6f0463a68b4970e3f6e50167d7d8099baec363cbbe6c6a4205761`；前端 `index.html` SHA256：`dc9030d1915f2d9781b84a00142b0afb79bc99e1f2d663150e14cfef6e38fd72`。

第一次镜像装配将文件写入 `/app`，而运行进程实际读取 `/candidate`，健康检查虽通过但新路由未生效。接口检查发现后，修正构建目标并再次重建、发布；最终镜像和上述验证均针对修正后版本。原镜像与备份仍保留。

## 尚未执行的交互检查

本轮未使用账号密码或付费模型发送用户级请求，未将“登录后自然语言追问、问答卡填写、真实资料调用”记为线上验收通过。建议由两名测试普通用户在现站点分别验证：无条件提问出现问答卡；填写条件后继续同一任务；选择“暂不回答”不触发取数；刷新后同一问题仍可恢复；来源不存在时不默认选取第一条。模型请求需计入既有每轮 40 次预算，失败和结果未知也计数，不自动重试。

## 回退

若发现站点功能异常，先停止新的写入，确认在途执行状态，再将 `compose.server.json` 中的 `console.image` 恢复为发布前镜像 `sha256:9d2eb42f8eb5b834280a962943e86ff29b35361e860c6c8f2f4bc92275164e7e`，仅重建 `console` 并复核健康、账号环境及路由。原 Compose 配置可从上述私有备份目录取回。不能用备份数据库覆盖发布后新增的用户记录；本次 schema 未变化，正常回退不需要恢复数据库。
