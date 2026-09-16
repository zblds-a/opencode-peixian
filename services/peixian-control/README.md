# 沛县分析控制层开发说明

## 三角色版本说明

本分支 `codex/peixian-p0-hardening` 使用 `super_admin/admin/user`。超级管理员管理普通用户和管理员，并独占平台插件、插件授权、现有模板及独立空间维护；管理员管理全部普通用户、模型和只读脱敏管理记录，不能操作插件授权、部门组织或独立环境维护。两个管理角色均无业务 runtime；普通用户保留个人 Skill 和已授权插件配置、启停及允许版本切换。

旧 admin 的一次性迁移、旧认证撤销、schema 2 兼容检查与控制库备份见 [三角色说明](../../deploy/peixian/ROLES.md)。本次只调整现有模板权限，正式部门公共 Skill 的唯一审核主体已定为超级管理员，完整审核发布流程仍在正式方案批次 D。文档更新不证明运行迁移、部署或审核发布已验收。

> 详细操作步骤见 [使用手册](../../deploy/peixian/USER_GUIDE.md)，或打开 [离线阅读版](../../deploy/peixian/USER_GUIDE.html)。涵盖超级管理员、管理员、普通用户、Python 调用、日常维护和常见问题。

本目录实现按账号绑定的分析控制台后端、每账号 Gateway、文件解析及模型出口。普通用户可以在不同电脑登录同一账号，访问同一套独立环境；环境身份由服务端认证记录决定，不接受客户端自行指定账号、工作区、容器或模型接口地址。

前端位于 [packages/peixian-console](../../packages/peixian-console)，宿主执行器及部署脚本位于 [deploy/peixian](../../deploy/peixian)。部署、迁移、备份和回退步骤见 [控制台操作手册](../../deploy/peixian/CONSOLE_OPERATIONS.md)。本文件面向开发和契约维护，不包含密钥值、真实账号记录或用户正文。

## 组件职责与数据边界

| 组件 | 职责 | 持有的数据与权限 |
| --- | --- | --- |
| control / FastAPI | 登录、账号与授权管理、个人资源路由、配置任务、审计、公开 API、前端静态文件 | 自己的控制数据库与插件包存储。保存账号元数据、技能及模板配置、文件元数据索引和加密后的运行配置；不挂载所有账号的 HOME、workspace 或 files 卷，也没有 Docker socket |
| 每账号 Gateway | 校验控制层私有认证，固定转发到该账号 Agent，处理文件上传、解析、预览、下载及插件连接测试 | 只挂载该账号 workspace 和 files；自己的托管配置只读；不挂载模型出口凭据目录 |
| 每账号 Agent | 固定版本 OpenCode 的会话、模型调用及已批准技能和插件运行 | 独立 HOME/workspace，files 只读，托管配置只读；只连接该账号内部网络 |
| 每账号 model-relay | 平台模型 ID 映射、固定目标请求、注入上游认证、流式转发 | 仅挂载该账号模型出口配置；不挂载 workspace/files；只连接该账号内部网和专属出口网 |
| 宿主 Worker | 领取任务、按固定模板开通/应用/暂停/恢复环境、检查实际就绪状态 | 可信宿主上的 Docker CLI 权限和独立执行器凭据；不把 Docker socket 挂到 Web 或 Agent，不执行来自用户的任意 Docker 命令 |

控制层通过各账号专属管理网络调用 Gateway。每账号的管理网只连接控制层和该 Gateway；不同账号不共用内部网、管理网或出口网。Gateway 与 model-relay 禁用 IP 转发。账号归属在每次请求时由 Cookie/Bearer 身份绑定，前端隐藏按钮不构成权限控制。

“不挂载所有账号卷”不表示控制层不处理用户内容：授权上传、下载及文件文本引用仍会经过控制层内存和 HTTP 转发。管理员公开 API 不提供读取用户会话、文件或业务结果的入口；控制层自身是可信路由与认证边界。

解析器和插件测试子进程共用该账号容器的 UID 与挂载范围。清理环境变量、限制资源及超时用于控制进程，不构成另一套文件系统沙箱。插件是管理员批准的可执行代码，技能是模型指令；两者都不能代替账号容器、网络和服务端授权边界。

## 目录导航

| 路径 | 作用 |
| --- | --- |
| control/app.py | 身份校验、普通业务 API、文件引用、SSE、异常脱敏、应用组装 |
| control/live_text.py | 有界的临时助手正文缓存、单账号单流写入及历史读取覆盖 |
| control/catalog.py | 个人技能、模板复制、授权插件配置与连接测试 |
| control/administration.py | 三角色账号/模型管理；super 专属插件、模板和环境任务；两管理角色只读脱敏审计 |
| control/plugin_schema.py | 可渲染配置表单限制、递归凭据脱敏与空密码保留 |
| control/store.py | SQLite 事务、账号/授权/任务状态、敏感配置加密 |
| control/worker_api.py | 独立执行器认证、任务租约、配置一致性快照、受限迁移接口 |
| control/openapi.py | 基于实际路由的显式 OpenAPI 契约 |
| gateway/app.py | 每账号文件接口和受限 Agent 代理 |
| gateway/storage.py、safe_fs.py | 原始上传配额、文件记录、Linux 目录 FD 与安全路径操作 |
| gateway/parse_queue.py、parser.py | 单并发解析队列与受限解析子进程 |
| gateway/model_relay.py | 每账号 OpenAI 兼容模型出口 |
| gateway/plugin_test.py、plugin_probe.mjs | 超级管理员发布插件的命名 test 导出探测 |
| examples/console_client.py | httpx 客户端：认证、文件、会话、事件、消息与停止生成 |
| tests、gateway/tests | 合成数据与 MockTransport/TestClient 回归，不调用真实模型 |
| docs/openapi.json | 可交付的静态 API 文档 |

## 对外 API 与认证

唯一公开业务前缀为 `/api/console/v1`。控制层通过自己定义的接口调用 Gateway，不把原生 OpenCode 全部接口直接透传给浏览器。

| 分组 | 公开路径示意 | 说明 |
| --- | --- | --- |
| 登录与个人认证 | /auth/login、/auth/logout、/me、/me/password、/tokens | Cookie 登录、个人主动改密、个人访问令牌创建/撤销 |
| 模型 | /models | 仅返回本账号获授权的平台模型 ID 与展示信息 |
| 会话 | /sessions、/sessions/{sid}/messages、/sessions/{sid}/abort | 只处理当前账号固定工作区的会话 |
| 事件 | /events | SSE 变更通知，客户端随后刷新消息和会话状态 |
| 文件 | /files、/files/{fid}/text、preview、download；/results | 上传内容与结果文件使用不透明 ID，不接收任意本地路径 |
| 技能与插件 | /skills、/templates、/plugins | 个人技能；超级管理员模板；已发布且授权的插件及个人配置 |
| 确认 | /permissions、/questions 及各自回复接口 | 只处理本账号会话的权限确认和问题 |
| 管理 | /admin/users、models、plugins、templates、jobs、audit | 按 ROLES.md 三角色、目标账号类型与字段白名单分别校验，不提供用户业务数据读取接口 |

/admin/audit 只读脱敏，支持 actor 精确账号 ID、action 固定动作和 result=success/denied/failed 筛选，最多返回 500 条匹配记录；不提供任意内部负载读取。三角色控制库使用 PRAGMA user_version=2，旧 admin 单次迁为 super_admin 并撤销其旧认证；新建 admin 没有 runtime。部署前使用控制库备份和镜像兼容检查，详见 ROLES.md。

完整的方法、请求体、状态码和具体路径以 [OpenAPI](docs/openapi.json) 为准。Gateway 私有文件接口有 metadata、rename、parse 等能力，不代表控制台公开了同名接口。原生 config/auth/MCP/PTY/shell/任意命令接口没有被公开。

浏览器登录设置 HttpOnly、SameSite=Strict 的 `px_session` Cookie，最长 8 小时。Cookie 写请求必须携带 login/me 返回的 `X-CSRF-Token`，并通过 Origin 校验。Python 可使用个人创建的 Bearer Token；个人令牌有效期 30 天，不需要 Cookie 的 CSRF 头。不要将 Cookie 值当作个人 Bearer Token。

登录后不再执行首次强制改密。个人主动改密、管理员重置密码、停用账号、注销或撤销令牌会按各自规则撤销认证；SSE 连接持续核验当前认证。三角色与目标账号类型逐接口校验；super_admin/admin 都不能通过普通业务 API 查看某个用户的数据。login/me 的 capabilities 为服务端生成，不接受客户端自报权限。

`/internal/worker/*` 只接受 `X-Worker-Key`，不是普通 Bearer API。其配置快照可能含运行凭据，仅供可信宿主执行器使用。Gateway 的全部私有请求另用 `X-Peixian-Key`；Gateway 到 Agent 使用固定用户名 opencode 的 Basic Auth。

## 会话、文件与引用语义

消息请求只接受 `text`、`model_id`、`skill_ids`、`file_ids` 四个字段。模型 ID 来自 /models，不是直接填写上游模型名称或地址。单次最多选择五个技能和五个文件，不接受原生 parts、任意文件 URL、目录或账号选择参数。

提交消息返回 202 与 accepted/run_id，仅表示请求已接受；run_id 不是独立结果查询资源。客户端应先订阅 /events，再提交消息，收到变更后读取 /sessions/{sid}/messages 及会话状态。SSE 的 data 仅为 connected/updated 通知，不是模型正文增量。同一会话应串行提交；停止操作使用 /abort。

原生生成中的正文增量不保证立即写入历史数据库，因此控制层使用 `LiveTextCache` 临时补齐消息读取。缓存按账号、会话、消息和文本片段隔离；只有已确认的助手正文可以覆盖同账号原生历史中的现有文本片段，不新增消息或暴露 reasoning、工具原始负载。原生完成、错误或文本结束记录优先。已知插件凭据在返回正文前脱敏；未完成或中止回复尾部若匹配凭据前缀，会暂扣该后缀，后续普通文本消除匹配后才正常显示。

默认边界为单文本片段 256 KiB、单账号正文 1 MiB、全部正文 4 MiB，按 UTF-8 字节计量；这不是进程总内存上限。另限制 128 个文本片段、256 条消息元数据、8,192 个已见事件 ID 和 32 个流写入者；缓存闲置 TTL 为 300 秒，写入者租约为 15 秒并持续续租。达到限制时丢弃相应临时缓存，不把截断片段标为完整答案。

每账号只有一个原生 SSE 连接负责向缓存写入，其他浏览器连接只接收业务刷新通知。事件 ID 仅用于去重，不按 ID 排序。连接释放或租约失效会清除该账号临时缓存；接管连接不补发历史 delta，不保证断线期间正文连续，最终仍以原生持久化消息为准。当前实现要求 control 单进程、单 uvicorn worker；增加进程或副本前必须另行设计共享缓存和写入者协调，不能仅增加 `--workers`。

文件规则如下：

- 单文件最大 20 MiB，包含 multipart 边界的请求最大 21 MiB；每账号原始上传总量为 1 GiB。实际字节计量，上传并发会预留容量，失败和删除后释放，服务启动时重新统计。
- files 卷按不透明文件 ID 保存原始内容与解析结果。原始上传总配额不包含解析文本/元数据和 workspace 结果，部署时仍需监控这部分磁盘空间。
- 支持 TXT、MD、CSV、XLSX、文本 PDF、DOCX；不执行 OCR、宏、公式计算、外部链接获取或 Office 自动化。XLSX 使用保存的公式缓存值。
- 状态包括 uploading、queued、parsing、ready、partial、no_text、unsupported、failed。扫描 PDF 无可提取文本时为 no_text；加密文档为 failed，错误类别 encrypted_document。
- 来源块保留文本行号、CSV 行号、XLSX 工作表与行号、PDF 页号、DOCX 段落或表格行号。ready 表示支持的文本提取过程完成，不保证图像、扫描层或全部版式语义都已提取。
- 解析最多保留 1,000,000 字符和 10,000 个来源块，达到上限标 partial/truncated。单次解析 60 秒、384 MiB 地址空间、200 MiB ZIP 解包预算，单账号队列并发为 1。
- 预览另外限制为 20,000 字符和 100 个来源块；预览 truncated 不等于原文件解析被截断。模型引用读取 /text，不读取 /preview。

**不完整解析禁止直接发给模型。** 当 /text 的 status=partial 或 truncated=true 时，控制层在提交模型之前返回 413：

> 所选文件仅完成部分解析，请拆分文件后重新上传；可在我的文件查看已提取范围

即使客户端提交这些文件 ID，也不会将已提取片段静默当作全文。正常 ready 且未截断的文件继续可引用；其来源块加入模型输入。文字、技能及文件合计另受 18,000 UTF-8 字节预算约束，文件引用总计还限制 24,000 字符；超限明确拒绝，不自动删减后提交。

## 技能与插件配置应用

超级管理员发布插件 ZIP 后，版本不可覆盖。用户只能选择已启用、已授权的发布版本，并按该版本表单保存自己的配置。GET /plugins 返回 `schemas` 版本映射；编辑旧版不能无条件套用最新版 schema。

配置表单只支持明确属性、关闭额外字段的嵌套对象，以及基础标量和非凭据标量数组。使用 writeOnly 或 password 格式标记的字段递归脱敏，响应只返回布尔状态树 `credentials_configured`。空密码字段可保留原值。脱敏始终依据已安装版本；该版本停用或元数据缺失时不会改用新版规则回显旧配置。

技能、授权、模型和插件变更通过任务应用到独立环境。HTTP 保存成功不代表 Agent 已生效，需检查环境状态以及 revision/desired 是否一致。执行器读取同一事务中的任务修订与配置快照，再按固定模板应用；Gateway 启动时捕获修订号，不能通过更新文件伪装已重载。

技能 test 只检查是否已加载。插件 test 调用管理员包实际提供的命名 test 导出；supported=false 表示未提供连接测试，不能当作连接通过。插件代码只能使用对应账号已配置的运行权限与网络，不因安装操作自动获得宿主或任意数据服务访问权。

## 配置变量

下面是代码默认值或语义，不是凭据内容。生产凭据由部署与执行器准备为独立文件；开发测试使用自己的临时合成文件。

### control

| 变量 | 默认值 | 用途 |
| --- | --- | --- |
| CONTROL_DATA | /data | 控制数据库及发布插件包目录 |
| CONTROL_KEY_FILE | /run/secrets/control-key | Fernet 加密配置的密钥文件；备份数据库时必须保留对应密钥 |
| WORKER_KEY_FILE | /run/secrets/worker-key | 独立宿主执行器认证文件，至少 32 字符 |
| ADMIN_PASSWORD_FILE | /run/secrets/admin-password | 全新库无超级管理员时初始化账号 admin（角色 super_admin）的密码文件，初始化要求至少 16 字符 |
| CONSOLE_STATIC | /app/static | 前端构建产物目录；目录存在时提供静态资源与 SPA |
| CONSOLE_ORIGINS | http://127.0.0.1:14090,http://localhost:14090 | 逗号分隔的精确允许 Origin |
| COOKIE_SECURE | 未设置 | 值严格为 true 时，为登录 Cookie 设置 Secure；HTTPS 部署应配套启用 |
| MAX_RUNTIMES | 4 | 已保留环境名额的最大数量；暂停后释放名额但保留数据 |

### Gateway 与 model-relay

| 变量 | 默认值 | 使用组件与用途 |
| --- | --- | --- |
| WORKSPACE | /workspace | Gateway，只允许该账号 workspace |
| FILES_ROOT | /files | Gateway，该账号上传与解析目录 |
| MANAGED_ROOT | /managed | 两者都有，但挂载源必须不同：Gateway 配置与插件探测；Relay 模型配置 |
| INTERNAL_TOKEN_FILE | /run/secrets/gateway-token | Gateway，控制层调用的私有令牌文件 |
| OPENCODE_PASSWORD_FILE | /run/secrets/opencode-password | Gateway，固定 Agent Basic Auth 密码文件 |
| OPENCODE_URL | http://agent:4096 | Gateway，只连接该账号 Agent |
| BUN_EXECUTABLE | /usr/local/bin/bun | Gateway 插件测试，固定已安装的 Bun 程序；测试需显式设置以避免跳过 |
| ACCOUNT_ID | 必填，无默认 | Relay，必须与每个已配置模型的 allowed_user 一致；Gateway 可收到该变量，但身份校验依据私有令牌与挂载边界 |

Relay 的 model-relay.json 只允许预配置的平台模型 ID、上游模型 ID、基地址、API key 和账号归属。真实密钥仅由 Relay 注入；Agent 使用本地模型出口地址与占位凭据。允许超级管理员或管理员显式配置内网 HTTP 服务；HTTPS 校验证书，不跟随重定向，不读取宿主代理环境。

Gateway 生产模式要求 Linux 目录 FD 安全操作；Windows 降级只用于显式构造 Settings(require_linux=False) 的本地测试，没有环境变量可开启生产降级。上传配额和解析上限是代码常量；当前部署必须保持每个 Gateway 只有一个 uvicorn worker。

## 开发环境

镜像使用 Python 3.12 和固定依赖锁；Gateway 镜像还包含 Bun 1.3.14。requirements.txt 是直接依赖清单，requirements.lock 是镜像安装使用的完整锁。更新依赖时同时维护锁与对应测试，不在已运行的生产容器中临时安装包。

在本目录创建独立 Python 环境：

~~~powershell
py -3.12 -m venv .venv
& '.\.venv\Scripts\python.exe' -m pip install -r requirements.lock
~~~

Linux 对应使用 python3.12 -m venv .venv 与 .venv/bin/python。无外网部署应使用已准备的本地 wheel 和镜像归档，流程见部署目录文档。

独立开发配置准备完成后，控制层进程入口为：

~~~powershell
& '.\.venv\Scripts\python.exe' -m uvicorn control.app:app --host 127.0.0.1 --port 14090 --workers 1 --no-access-log
~~~

该命令不会开通账号容器；完整环境需要容器化控制层与宿主 Worker。宿主运行的临时控制进程不能直接解析各账号管理网络的 Docker DNS 名称。不要让开发实例指向现有生产 CONTROL_DATA 或复用现有凭据。

前端项目脚本为 bun run dev、bun run typecheck、bun run build。Vite 固定监听本机 5178，并将 /api 代理到本机 14090。开发登录写请求的 Origin 是前端端口，需要将对应本机开发 Origin 加入独立开发控制层的 CONSOLE_ORIGINS；默认生产列表不包含 5178。构建产物由 control 的 Dockerfile 复制到 /app/static。

宿主执行器入口为 ../../deploy/peixian/console-worker.py。可配置控制层回环地址、凭据文件、状态目录、镜像标签和最大名额；它拒绝非回环控制地址，通过宿主锁防止多个执行器并发管理同一状态目录。生命周期及迁移操作使用部署脚本，不通过普通用户 API 传入命令。

## OpenAPI 与 Python 客户端

在线契约路径为 /openapi.json；未启用 Swagger/ReDoc 页面。静态交付件为 [docs/openapi.json](docs/openapi.json)。

~~~powershell
& '.\.venv\Scripts\python.exe' export_openapi.py
~~~

导出仅读取实际路由，不进入 lifespan，不初始化 Store，不读取部署凭据，也不连接模型或账号环境。自定义输出使用 --output。control/openapi.py 的 install_openapi(app) 已在路由注册结束后挂接；build_openapi(app) 可生成不使用缓存的新文档。

添加或修改公开 API 时，同步其显式请求体、响应体、角色与安全方案，再重新导出。未补契约的新业务或内部路由会使生成失败。测试还核对 endpoint 的 body_fields 白名单，避免服务实际接受的字段与文档脱节。内部 Worker 标记 x-internal，不能在客户端生成时误认为个人 Bearer 可调用。

[httpx 示例](examples/console_client.py) 包含 Cookie/CSRF 与个人令牌、上传/等待解析/下载、会话、SSE、异步消息和停止生成。示例中真实发送问题的方法会调用模型；离线测试使用 MockTransport，不执行真实模型调用。

SDK 的 `wait_for_file` 只有在 status=ready 且未标记 truncated 时才返回可引用文件；partial 或 truncated=true 会立即抛出 ConsoleError，提示拆分后重新上传，不继续提交模型。其他终止失败状态也不会被当作解析成功。该客户端检查与服务端 413 拒绝相互独立，直接调用 HTTP 也不能绕过服务端规则。

## 测试与验收

在本目录执行回归。下例使用独立项目临时目录；pytest 的 basetemp 必须是本次新建专用目录，不能指向任何账号数据或已有备份。

~~~powershell
$testScratch = Join-Path (Get-Location) 'gateway/.scratch'
New-Item -ItemType Directory -Force -Path $testScratch | Out-Null
$env:TEMP = $testScratch
$env:TMP = $testScratch
$testBase = Join-Path $testScratch ([Guid]::NewGuid().ToString('N'))
# 已安装 Bun 时显式设置 BUN_EXECUTABLE 为其绝对路径。
& '.\.venv\Scripts\python.exe' -m pytest tests gateway/tests -q -rs --basetemp $testBase
~~~

不设置 BUN_EXECUTABLE 会跳过插件进程测试；Windows 无创建符号链接权限时也会跳过对应用例。跳过不能记为隔离通过。Linux 还必须执行真实目录 FD、符号链接替换、管道拒绝及资源限额测试。

已构建 Gateway 测试镜像时，可使用独立无网络临时容器运行 Linux 回归：

~~~powershell
$testMount = (Resolve-Path 'gateway/tests').Path
docker run --rm --pull never --network none --user 10001:10001 --read-only --cap-drop ALL --security-opt no-new-privileges:true --memory 512m --cpus 1 --pids-limit 128 --tmpfs '/tmp:rw,nosuid,nodev,size=128m,mode=1777' --mount ('type=bind,source=' + $testMount + ',target=/app/gateway/tests,readonly') --env BUN_EXECUTABLE=/usr/local/bin/bun --workdir /app --entrypoint python peixian-gateway:console-r1 -m pytest gateway/tests -q -rs -p no:cacheprovider --basetemp /tmp/gateway-tests
~~~

该测试容器只挂测试源码，不挂现有账号卷，也不连接账号网络。模型与 Gateway HTTP 使用 MockTransport，插件探测只加载合成模块。

部署后的 [HTTP 隔离验收脚本](../../deploy/peixian/console-isolation-acceptance.py) 使用两个专用合成账号，覆盖格式解析、跨账号资源、管理员边界、CSRF、令牌撤销和旧 SSE 连接关闭；会创建并清理合成文件与空会话。它不应使用真实业务账号，不会发送有效模型请求。运行前需确认环境 ready，传入本地专用凭据文件，报告只保留脱敏检查结果。真实模型能力、旧数据迁移、备份与回退分别验收，不能用编译通过、HTTP 202 或单次健康检查代替。
