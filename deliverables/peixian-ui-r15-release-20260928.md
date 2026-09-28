# 沛县公安前端合并发布回执（2026-09-28，r15）

## 1. 范围与结果

本轮把两个对话中针对 **`packages/peixian-console`** 的前端改动合并后，已发布到正式站点。2026-09-28 20:35（北京时间）发布脚本返回 `PRODUCTION_DEPLOYED`；Console、HTTPS 均为 `healthy`，宿主 worker 为 `active`。未制作私网一键部署包，未修改后端 API、业务代码、Gateway 或 Agent 镜像。

合并内容：

| 来源 | 前端改动 |
| --- | --- |
| 本对话 | 流式 Markdown 缓冲完整表格行与来源链接；固定表格列宽、窄屏横向滚动、保留已完成行及来源链接 DOM；合并自动滚动；同一会话运行刷新时保留追问卡与已选项，避免重复 `/result` 请求导致卸载重挂。 |
| 另一对话「分析停止生成仍返回内容的原因」中的沛县 Console 工作 | 当前回答文字播放完成后才显示“下一步分析”追问卡；“查看执行过程”默认折叠；去掉追问卡内重复的“下一步分析”标题。合并时加入一次显示后保持可见的闩锁，避免后续消息增量使卡片再次消失。 |

另一对话还改过 `packages/app` 的 OpenCode 会话停止显示逻辑。它不属于沛县 Console 前端，也不进入本轮 Control 镜像；该目录的改动保留在原工作树，本轮未改动或发布。

## 2. 源码、构建和镜像

- 前端及合并源码提交：`6cc9efc7ccc23e06eb3b89d3e03242f8f78588d5`，其父提交链含 `3bedf7a73`（流式表格）与 `6404d139f`（追问卡稳定）。构建时 `VITE_ENABLE_GRAPH_PREVIEW=false`。
- 后端固定基线：`peixian-control:minimal-input-20260928-r2`，镜像 ID `sha256:fab95db567990491c7addadaca6ab2be13a08fa183ef911155cfb1346f57a1aa`。新镜像使用该**固定镜像 ID**，通过 Dockerfile 清空并替换 `/candidate/static`；没有从运行容器执行 `docker commit`。
- 正式镜像：`peixian-control:combined-20260928-r15`，镜像 ID `sha256:2c32fe56d4f3710ea5fe3bf29052d477e6aa9853a8ec440f7fb06a69744fc681`。镜像标签 `org.peixian.frontend.revision=6cc9efc7...`、`org.peixian.backend.base.image=sha256:fab95db...`。
- 前端构建包 SHA-256：`01e9c8926b816b1ebf320d4d1b86b344354babd494f055a8c37580214bdbb3d6`；静态首页 SHA-256：`a0a00e0d05c07c44a24cb32c80394862598c970cc417fb55bbbbd07390983669`。
- 对比基础与新镜像，`/candidate/control`、`/candidate/shared` 共 157 个文件的路径和内容树哈希均为 `808dd9c60ecbfc9e99c3e37b4cd7ba4c36e7f2d65557b062b1a0b7dc30f5eeaa`。只变更前端静态文件。
- Gateway 保持 `peixian-gateway:model-view-3.6.4-20260928`（`sha256:efdadc976ffcf8eb771a1aa5dbc1fd843bd062e64ad7fc6214bb22364270edce`）；Agent 保持 `peixian-agent:20260928-r13`（`sha256:b43b190e1fd14afeb05259b09f4c0c4b9941f7053feb8ddcc9fce8bac1b63b4c`）。

**后端源码缺口：** 发布时 `/root/PeiXianDB/theft-prompt-entry` 的 HEAD 为 `a1f61422366bd60f82290a109e24f51dd141a133`，但当前 r2 镜像中的 12 个后端运行文件与服务器未提交工作树一致，而非该 HEAD。用户已选择以固定 r2 镜像 ID 发布并记录这一缺口。因此本轮镜像的后端二进制/文件内容由固定父镜像可追溯，但尚不能仅从 `a1f614223` 重新构建出相同的后端内容；继承的 `org.peixian.backend.revision=a1f614223...` 标签也不足以说明完整实际源码。后端应提交 r2 的这些运行文件及相关测试，提供提交 SHA，并核对其文件哈希与 r2 镜像一致。此项无需改变 API 或前端数据结构。

## 3. 发布步骤、检查与回滚

- 构建目录：`/root/build-ui-6cc9efc7c/`；仓库中的对应 Dockerfile 和发布脚本位于 `deploy/peixian/releases/20260928-r15/`。发布前执行既有 `check-release-idle.py`：两个 Gateway 的 `activity.total=0`，无等待追问或权限，也无并行 Docker 构建/部署。
- `platform.json` 的 `images.control` 已切换为正式标签；`runtime/generated/compose.server.json` 的 Console 固定为新镜像 ID。仅重建 Console，HTTPS、Gateway、Agent、worker 均未重建。
- 备份：`/srv/peixian-alignment-20260917/platform.before-ui-r15-20260928-203429.json`（SHA-256 `b6a3b172fc4764061522a9847b423492fb754d23b53fc19df9d3eaaf598c77ba`）；`/srv/peixian-alignment-20260917/runtime/generated/compose.server.before-ui-r15-20260928-203429.json`（SHA-256 `431095e870280cdc4f2bf492d3d9c19c56195e50f9e6f2d366eec94c157d3872`）。
- 回滚时先运行 `/root/PeiXianDB/check-release-idle.py`，将上述两份备份分别恢复为 `platform.json` 与 `runtime/generated/compose.server.json`，再执行 `docker compose -f /srv/peixian-alignment-20260917/runtime/generated/compose.server.json up -d --no-deps --no-build console`，等待 Console 和 HTTPS 变为 `healthy`。回滚目标为 `peixian-control:minimal-input-20260928-r2` / `sha256:fab95db...`，不会回退后端 r2。

## 4. 定向验证与限制

- 前端 `npm run typecheck`、`VITE_ENABLE_GRAPH_PREVIEW=false npm run build`、`git diff --check` 通过；流式 Markdown 逐字符拆包等 6 项单元测试通过。
- 合并前的浏览器夹具已确认追加表格行时旧行与来源链接保持同一 DOM 节点、来源点击可展开详情、360px 容器可横向滚动。合并后重新执行 typecheck/build，未在真实登录会话中重复这些交互。
- 线上首页及入口 JS/CSS 均返回 HTTP 200；线上首页 SHA-256 与本次构建一致。Console、HTTPS 为 `healthy`，worker 为 `active`；新 Console 日志显示应用正常启动。未做完整聊天、插件、历史会话、图谱和追问的登录态端到端验收，因此这些功能的线上交互效果仍需业务侧观察。
- 本轮发布未制作私网部署包；本文件和发布脚本是本次线上发布记录，不替代目标欧拉服务器验收。
