# 沛县公安前端交接与正式发布回执（2026-09-29）

## 1. 本轮结论

已修复用户点击聊天输入框的“停止生成”后，前端继续播放已缓存回答的问题，并完成正式发布。点击时先在前端冻结当前运行已显示的字符和 Markdown 投影，再向后端发送既有 `/abort` 请求；后端请求明确失败时恢复显示。未修改后端代码、API、消息结构、Gateway 或 Agent；未制作私网部署包。

本轮也把上一提交 `0735c733c` 的 `source_answer` 来源列表格逐单元格显示改动一并纳入正式静态构建。前端代码提交为 `ed97ccee114a36b32c32585bf5f4d0be0eeed45e`，其父提交为 `0735c733cf2772fa2ca67f7aaf3e049c5358e535`。

## 2. 根因与前端改法

原“停止生成”处理先等待 `/sessions/{id}/runs/{run_id}/abort`（无活动 run 时调用会话 `/abort`），其间 `SmoothMarkdown` 的 `requestAnimationFrame` 仍按约 70 ms 的节奏递增可见字符数。后端状态即使变为 `cancelled`，原逻辑也只标记输出中断，没有终止本地文字播放。后续 `/messages` 快照、实时片段或组件重新挂载，还可能继续展示停止前已收到但尚未播放的文字。

现在 `Chat.tsx` 在点击事件内同步设置当前会话/run 的停止显示标记，并把按钮置为“正在停止…”，然后再发 `/abort`。`SmoothMarkdown.tsx` 看到标记即取消下一帧、停止更新字符数及 Markdown 投影。每个文本 part 的可见字符数和投影均按稳定 ID 缓存，因此同一 run 的消息刷新或组件重挂也维持点击时的可见内容。停止请求明确失败则清除标记，允许继续播放。新问题成功受理或切换/新建会话时清除旧标记，避免影响后续运行。后端仍负责真正终止模型执行；前端冻结仅保证界面立即停止输出。

在组件浏览器复测中还发现：中文句号后紧接汉字时，原流式投影只在句号处于字符串末尾或后面有空格时提交句子，导致下一汉字到达后可见句子短暂回退。`stream-markdown.ts` 已改为中文句末符号无需空格即可稳定提交；英文句末仍要求空格或结束，避免误识别小数点等。

| 文件 | 改动 |
| --- | --- |
| `packages/peixian-console/src/pages/Chat.tsx` | 点击即设置当前 run 停止显示状态；异步调用原 `/abort`；失败恢复；会话/新 run 清理；传递停止状态与投影缓存。 |
| `packages/peixian-console/src/SmoothMarkdown.tsx` | 停止时取消 RAF，冻结可见字符及投影；重挂载沿用投影缓存。 |
| `packages/peixian-console/src/stream-markdown.ts` | 修正无空格中文句末的可见内容回退。 |
| `packages/peixian-console/tests/stream-markdown.test.mjs` | 增加中文句末回归验证。 |
| `packages/peixian-console/tests/stop-reveal-harness.html`、`stop-reveal-harness.tsx`、`stop-reveal-browser.py` | 合成浏览器夹具：点击停止、晚到缓存、重挂载及停止失败后的恢复。 |

## 3. 代码与构建基线

- 本地工作树：`H:\Projects\opencode-peixian\.question-card-fix`，分支 `question-card-stability`。仓库远端 `zblds`：`https://github.com/zblds-a/opencode-peixian.git`。
- 前端源码提交：`ed97ccee114a36b32c32585bf5f4d0be0eeed45e`；正式构建设置 `VITE_ENABLE_GRAPH_PREVIEW=false`。
- 当前服务器后端仓库 `/root/PeiXianDB/theft-prompt-entry` 在发布前 HEAD 为 `227fc92a687ea4e7d3a7621995fff90f064d4a86`，工作树只有原有 `.backup-*` 未跟踪目录。**本轮不以该提交重新构建后端**，而是以发布前实际运行且健康的 `peixian-control:minimal-input-20260928-r12` 镜像 ID 为固定父镜像；其继承的旧 `org.peixian.backend.revision` 标签不能单独作为当前后端源码对齐证明。
- 固定父镜像：`sha256:45e9edc201088fd1a28b4d5846a59a1d67c6f857525a4e9f30171503d0ee7c91`，`linux/amd64`，运行用户 `10001:10001`。
- 正式镜像：`peixian-control:frontend-stop-20260929-r1`，镜像 ID `sha256:71ac6da1a478e66de36c0ad47b5ecef9feca409f611d4fe66b976357820d7d55`。新镜像仅清空、替换 `/candidate/static`；没有从运行容器执行 `docker commit`。
- 构建目录：`/root/build-ui-ed97ccee1/`。构建归档 SHA-256 为 `fb4de76855682e8c0aaa33ac88f0c5f8b0d602ead14c89b42d424e8b840211b3`。本地与镜像内首页 SHA-256 均为 `3f1d859910073b78b580db0541a407a7e0f35bd8562ec9ff96069e5f0227b760`。
- 父镜像和候选镜像中 `/candidate/control`、`/candidate/shared` 的 157 个后端文件逐文件一致；文件清单树 SHA-256 为 `3f3f67c7ceb0c1bb8862c1aa1860605ddb8053d91ba95eef4dc0d75e6863ccf9`。仓库留存 `deploy/peixian/releases/20260929-stop/` 下的 Dockerfile、核验与发布脚本。

## 4. 定向验证

1. `npm run typecheck --workspaces=false` 通过。
2. `VITE_ENABLE_GRAPH_PREVIEW=false npm run build --workspaces=false` 通过。Vite 提示部分既有大块资源较大，构建退出码为 0。
3. `node --experimental-strip-types --test tests/stream-markdown.test.mjs`：10/10 通过，包括逐字符拆包、来源链接、表格行、中文句末连续输入与阅读位置状态。
4. `python tests/stop-reveal-browser.py`：本地 Vite + Chromium 合成页面通过。点击停止后可见文字立即不变；追加缓存及重挂载仍不继续显示；模拟停止请求失败后可继续追上新增文本。
5. 发布前执行服务器 `check-release-idle.py`：两个 Gateway 的活动数均为 0，无等待追问/权限，`publishing=[]`。
6. 发布后 Console、HTTPS 为 `healthy`，worker 为 `active`；`https://127.0.0.1:19460/` 首页 SHA-256 与本地构建一致，入口 JS `/assets/index-js1DF52O.js` 和 CSS `/assets/index-BRAfITZk.css` 均返回 200；Console 日志显示 Uvicorn 正常启动。

本轮未在真实登录账号下触发一次线上模型生成后点击停止，因此**不能据合成浏览器测试声称已完成登录态端到端验收**。尤其应观察后端 `/abort` 受理时间与真实模型执行停止情况；前端只承诺点击后可见输出即时冻结。如果 `/abort` 明确失败，界面会恢复播放并显示错误。切换历史会话后按已持久化消息正常显示，不会永久裁切服务端记录。

## 5. 配置、回滚与后端边界

发布脚本在重建 Console 前保存了以下配置：

- `/srv/peixian-alignment-20260917/platform.before-ui-stop-20260929-082235.json`，SHA-256 `d2610d2d96bb72de9ded41c91db0b4404193a07a4636e3db6398f05c5ad99fd0`。
- `/srv/peixian-alignment-20260917/runtime/generated/compose.server.before-ui-stop-20260929-082235.json`，SHA-256 `f2028474e1926f53d4738f82afb8d9e4adba231986d53ae86c54bf8ba7f928bd`。

当前 `platform.json` 的 `images.control` 为 `peixian-control:frontend-stop-20260929-r1`，Compose 的 Console image 固定为新镜像 ID。仅重建 Console。回滚前运行 `/root/PeiXianDB/check-release-idle.py`，确认无运行中的任务及并行发布；再将上述两份备份分别恢复为 `platform.json`、`runtime/generated/compose.server.json`，执行：

```bash
docker compose -f /srv/peixian-alignment-20260917/runtime/generated/compose.server.json up -d --no-deps --no-build console
```

回滚目标是 `peixian-control:minimal-input-20260928-r12` / `sha256:45e9edc201088fd1a28b4d5846a59a1d67c6f857525a4e9f30171503d0ee7c91`。发布脚本自身在健康检查失败时也会自动恢复旧配置并重启旧 Console。

本轮无需后端修改接口或数据格式。如果真实登录态复测发现 `/abort` 返回成功但任务仍持续执行，应由后端追查取消请求与模型执行器之间的终止链路；前端现在会先冻结界面，但不能代替后端终止计算。

## 6. 新对话接手提示

从 `H:\Projects\opencode-peixian\.question-card-fix` 的 `question-card-stability` 分支继续前端工作。先核对服务器当前 Console 镜像、后端新提交与 `check-release-idle.py`，不要假设本回执里的 r12 基线仍是最新；后端可能独立发布。若继续处理流式回答，请区分后端收到的完整文本快照、本地约 70 ms 的可见文字播放，以及 Markdown 的安全投影。`source_answer` 表格在含“来源”列时逐格显示普通列，来源链接完整后才显示短编号；停止按钮现在冻结的是**可见投影**，包括尚未播放的缓存内容。新对话应优先做真实登录态的停止按钮观察，再决定是否调整动画节奏。
