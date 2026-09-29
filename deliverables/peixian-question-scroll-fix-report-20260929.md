# 沛县控制台追问卡片与流式回答抖动修复报告（2026-09-29）

## 状态与范围

本轮前端代码已修改并通过本地定向验证，**2026-09-29 09:39（北京时间）已正式发布**。用户明确与后端沟通并授权本轮忽略后端活动任务，因此本次只放宽了发布脚本的空闲门槛；仍以切换前实际运行的 Console 镜像为父镜像，核对后端文件一致，并保留镜像身份、服务健康和自动回滚检查。未制作私网部署包，未修改“停止生成”逻辑或任何后端接口。

## 排查事实与根因

1. 原追问表单位于 `.composer-area`，而该区域是 `.conversation` 中不收缩的底部 flex 子项。卡片出现会增加底部区域高度，直接压缩 `.messages-scroll` 的 `clientHeight`。原 `scheduleFollowScroll()` 再通过 `requestAnimationFrame` 写入 `scrollTop = scrollHeight`，于是存在“消息区先缩小、下一帧再追底”的两阶段位移。
2. 原聊天区已有 `min-height: 0`、固定高度约束和单个主要滚动容器，但自动追底仅响应消息与投影更新，没有统一响应卡片、输入区和视口尺寸变化。浏览器默认滚动锚定可能与应用追底同时调整位置。源码中未发现聊天区的第二套周期性自动追底；`scrollIntoView` 仅用于来源链接和关联消息的主动定位。
3. 原 Markdown 表格待完成状态占据至少 56 px 高度。逐字符浏览器夹具在来源表格表头成形时，测得回答区域从 97.75 px 降到 80.09 px，单次回落约 **17.66 px**。这属于投影占位与正式表格高度切换，不能把所有抖动都归因于 Markdown 重解析。另有 `marked` 生成的列表、表格序列化空白变化，但夹具中的已完成段落、表格和首个来源链接节点保持了身份，未测到它们反复卸载。
4. 原 `FollowScroll` 已把“跟随”作为独立状态，向上滚动会退出跟随；缺少的是内容从当前阅读锚点上方增长时的位置补偿。只保留 `scrollTop` 会把读者推向不同的内容。
5. 追问提交原本要求所有题目作答；当其他页未答时，按钮被禁用并按全局规则降至 50% 不透明度，但界面没有指出缺哪一题，因此看起来像鼠标悬停导致按钮变灰。

## 代码修改

- `src/pages/Chat.tsx`：把待确认事项、澄清问题和下一步追问卡片放在消息滚动区末尾，输入区保持固定。消息增长、卡片变化和“回到底部”统一请求 `ChatScroll` 处理；用户滚轮、触摸、键盘及拖动继续驱动独立的 `FollowScroll` 状态。
- `src/chat-scroll.ts`：新增单一滚动写入入口。观察消息滚动容器、消息列表与卡片区域的尺寸变化；同一轮更新合并请求。跟随时按 `scrollHeight - clientHeight` 即时对齐底部；阅读历史时用可见段落或卡片节点的相对位置补偿上方内容增长，锚点失效则保留原位置。卸载时清理观察器和待执行帧。
- `src/styles.css`、`src/chat-dialogue-v2.css`：只在聊天消息滚动容器关闭浏览器滚动锚定，明确即时滚动；移除表格进度提示的布局占位但保留辅助技术状态；卡片进入消息流后取消其内部纵向滚动，避免嵌套滚动。未设定固定卡片高度或裁切卡片内容。
- `src/SmoothMarkdown.tsx`：仅当实际可见投影文本变化时请求滚动更新；待表格状态变化本身不触发追底。停止生成既有逻辑保持不变。
- `src/BusinessConfirmations.tsx`：最后一页有未答题或未完成的“自行填写”时列出题号并提供返回入口；保留全部作答后提交的校验。有效提交按钮悬停为清晰蓝色，忙碌态仍禁用。

## 本地验证与测量

- `npm run typecheck --workspaces=false`：通过。
- `VITE_ENABLE_GRAPH_PREVIEW=false npm run build --workspaces=false`：通过；Vite 仅提示已有的大块资源体积告警。
- 本地候选构建首页 SHA-256：`f63dff3469f4a1bfc3f27373e999903db93e367856897674f436117a71744f9a`；入口脚本 `/assets/index-C7TczqKg.js`、样式 `/assets/index-B04nGFbd.css`。正式发布前若重新构建，须重新核对哈希。
- `node --experimental-strip-types --test tests/stream-markdown.test.mjs`：10/10 通过，覆盖逐字符来源链接、表格、中文句末和跟随意图。
- `python tests/answer-stability-browser.py`：Chromium 逐字符测试段落、标题列表、代码块、来源表格；投影文本未回退，回答区域无高度回落，已完成段落、表格和首个来源链接节点保持身份。追问未答提示、返回、全部答完后启用、蓝色悬停及提交中禁用均通过；无页面异常。DOM `textContent` 的换行空白随列表和表格结构变化，测试将其单独记录，未将其误报为可见文字丢失。
- `python tests/scroll-stability-browser.py`：模拟从不足一屏到溢出、持续增长、卡片新增／变长／移除、上方段落增长、阅读历史、恢复跟随、视口变矮、输入区增高、窄屏换行及下一轮。卡片三次变化中 `clientHeight` 均保持 600 px；阅读历史时上方内容增长 361 px，`scrollTop` 从 87 增至 448 px，原可见锚点位置误差不超过 1 px；下方内容和卡片增长不拉动阅读位置。跟随状态下各阶段 `scrollTop` 均等于有效底部；无页面异常。

这些是本地合成数据和浏览器布局测试，尚不能替代真实账号及线上录屏验收。真实模型可能输出不同的长段落、图示或异步内容，需要正式发布后继续观察。

## 后端对齐与正式发布

2026-09-29 09:26 的首次检查中，Console 为 `sha256:71ac6da1a478e66de36c0ad47b5ecef9feca409f611d4fe66b976357820d7d55` 且健康；后端仓库 `/root/PeiXianDB/theft-prompt-entry` 的 HEAD 为 `178bfb328a5bf5341a245dcc908cb86742be7a83`，工作树有未提交修改。`check-release-idle.py` 报告第一个 Gateway 有 `native_running=2`、`waiting_question=2`、`total=4`。因此原计划暂停。随后用户明确与后端沟通，授权直接发布；这些活动任务不再作为本次前端切换的门槛。

09:34 再次核对，Console 和 HTTPS 均为 `healthy`，worker 为 `active`，Console 镜像仍是上述 ID，运行用户为 `10001:10001`；未发现并行 Docker 构建或部署进程。候选从该生产镜像构建，仅清空和替换 `/candidate/static`，保持运行用户不变。上传的 65 个前端文件与本地文件数一致，`index.html` SHA-256 都是 `f63dff3469f4a1bfc3f27373e999903db93e367856897674f436117a71744f9a`。候选与父镜像的 `/candidate/control`、`/candidate/shared` 共 157 个后端文件哈希清单完全一致，清单 SHA-256 为 `3f3f67c7ceb0c1bb8862c1aa1860605ddb8053d91ba95eef4dc0d75e6863ccf9`。

正式镜像标签为 `peixian-control:question-scroll-20260929-r1`，镜像 ID 为 `sha256:b2afe14c3de62207216e2299812b0fa5b8dff08f97fe7bc98ed73efaf4b5677c`，前端修订标签为 `a9eae1994`。09:39 使用 `deploy/peixian/releases/20260929-scroll/release.py` 只重建 Console；切换后 Console、HTTPS 均为 `healthy`，worker 为 `active`，Console 日志显示 Uvicorn 启动完成。服务器 `https://127.0.0.1:19460/` 的首页哈希与候选一致，入口 JS `/assets/index-C7TczqKg.js` 和 CSS `/assets/index-B04nGFbd.css` 均返回 200；公网 `https://36.134.45.38:19460/` 返回 200 并引用这两个资源，`/openapi.json` 仍返回 200。09:41 后端源码 HEAD 仍为 `178bfb328a5bf5341a245dcc908cb86742be7a83`，工作树有 13 项未提交状态；实际运行的后端文件以父镜像逐文件哈希一致性为准。

发布前配置备份：`/srv/peixian-alignment-20260917/platform.before-ui-scroll-20260929-093952.json` 和 `/srv/peixian-alignment-20260917/runtime/generated/compose.server.before-ui-scroll-20260929-093952.json`。若需回滚，先核对当前 Console 镜像和后端发布状态，将两份备份分别恢复为 `platform.json` 与 `runtime/generated/compose.server.json`，再执行 `docker compose -f /srv/peixian-alignment-20260917/runtime/generated/compose.server.json up -d --no-deps --no-build console`，核查 Console、HTTPS 健康和旧入口资源。回滚目标为 `peixian-control:frontend-stop-20260929-r1` / `sha256:71ac6da1a478e66de36c0ad47b5ecef9feca409f611d4fe66b976357820d7d55`。发布脚本在切换验证失败时也会自动恢复这两份原始配置并启动旧 Console。

## 未完成验收

- 真实登录态的连续生成、卡片交互及与用户录屏逐帧对比：当前环境没有可复用的登录态或测试账号，本次只完成本地浏览器夹具和正式入口、资源、服务健康验证；不能据此声称线上交互已逐帧验收。
- 后端后续独立发布：本次镜像保留了切换时运行的后端文件。若后端团队随后替换 Console 镜像，需要重新核对前端资源是否被覆盖。
- “停止生成”真正终止及流式传输设计：明确不属于本轮修复。

## 后端后续发布与源码同步（2026-09-29 11:19）

后端团队随后将生产 Console 更新为 `peixian-control:question-probe-20260929-r2`，实际镜像 ID 为 `sha256:af094ada74a26a9bfeb10f2de15818f94708e423a3439825d8d12eb357a87545`，Console、HTTPS 仍为 `healthy`。该镜像的正式入口依然引用 `/assets/index-C7TczqKg.js` 与 `/assets/index-B04nGFbd.css`，线上 `index.html` SHA-256 仍是 `f63dff3469f4a1bfc3f27373e999903db93e367856897674f436117a71744f9a`；因此本轮前端并未被后端发布覆盖，无需再次切换生产镜像。后端源码 `/root/PeiXianDB/theft-prompt-entry` 当时的 HEAD 为 `cb721c1257e936ba5e41b38b4efc25dd4bbe49d8`。

前端修复和本报告已推送至 `https://github.com/zblds-a/opencode-peixian.git` 的 `question-card-stability` 分支。服务器另建独立源码目录 `/root/PeiXianDB/frontend-question-scroll-20260929` 跟踪该分支；它与后端工作目录隔离，生产运行资源仍来自上述镜像。后续若再次修改前端，须重新构建并发布，单纯拉取源码不会改变线上资源。
