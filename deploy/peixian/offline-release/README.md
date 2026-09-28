# 沛县平台私网离线交付（amd64，2026-09-28）

本包用于**全新单机安装**，适配目标为国产 Linux 欧拉系的 x86_64 主机。目标机的准确发行版尚未知，必须先执行探测；当前服务器上的验证不能替代目标机验收。镜像、前端字体、Python wheels 和前端构建依赖均在包内，安装过程不需要公网。

## 目录与版本依据

- `source.tar.gz`：`source-commit.txt` 指定提交的源码快照；包括前后端、前端自托管字体及许可证、正式 Dockerfile。
- `images/*.tar`：Control、Gateway、Agent、代理及两种构建基础镜像。`images.ids` 固定每个 tag 的完整 image ID。
- `wheels-worker/`、`wheels-control/`、`frontend-node_modules.tar.gz`：离线安装和重建所需依赖。
- `SHA256SUMS`：包内文件校验。任何文件校验失败都应重新传输整个包，不能忽略错误。
- `probe-host.sh`：只读环境探测。`install.sh`：全新安装。`build-from-source.sh`：按固定输入离线重建 Control 和 Gateway。

Control 和 Gateway 由同一源码提交构建；Agent 使用已经发布并校验 ID 的 `peixian-agent:20260928-r13`，在本包中赋予 `peixian-agent:euler-20260928` 标签。它不是从当前运行容器导出的。代理也由固定镜像 ID 交付。镜像标签的具体 ID 以 `images.ids` 为准。

## 宿主前提与只读探测

预装 Docker Engine、Docker Compose v2、Python 3.11+（含 `venv`）、systemd、`acl`（`setfacl`）、`tar`、`sha256sum`；本包不含系统 RPM。Docker 数据盘应留足镜像导入空间，CPU/内存按 `platform.json` 的运行实例数和资源策略配置。主机架构必须为 x86_64，Docker daemon 必须运行 Linux/amd64 容器。

```sh
sh probe-host.sh | tee host-report.txt
```

探测脚本自身只读、不写文件、不联网、不读取或输出密码和私钥；上例由操作者通过 `tee` 保存报告。`failures` 必须为 `0`。重点核对 `os_id/os_version`、`architecture/docker_architecture`、Docker/Compose/Python 版本、`docker_free_kib`、SELinux、已占用端口、路由和 Docker 网段。目标欧拉版本与内核不满足 Docker 的实际要求时，先由现场运维修复宿主环境；不得强行导入不匹配的架构镜像。

## 一次性配置与安装

1. 将整个包复制到目标机，保留目录结构。复制 `platform.template.json` 为包外的 `platform.json`，将 `REPLACE_PRIVATE_HOST` 改为可由客户端访问、与证书匹配的私网 DNS 名或 IP。
2. 将正式证书和匹配私钥放在 `tls.certificate`、`tls.private_key` 指向的绝对路径；权限由现场运维控制。根据探测结果确认 `network_pool` 不与主机、Docker、业务网络重叠，并调整 `max_runtimes`、CPU/内存预算及端口。模板中的 `feature_scopes` 为空，创建用户后按需填写该私网用户的实际 ID；不要复制公网上的用户 ID。
3. 在目标机执行：

```sh
sudo sh install.sh /absolute/path/to/platform.json
```

安装器先运行探测和 `sha256sum -c`，再导入并核验镜像 ID、安装离线 Python 依赖、运行平台现有 `init/check/up` 流程、启用 `peixian-private-worker.service`、检查本地 Control 健康。安装器检测到已存在的正式配置或 service 时会拒绝重复全新安装，避免覆盖现有数据。初始管理员密码保存在由 `platform-manage.py init` 生成的 `data_root` 所对应的 secrets 目录；按命令输出路径读取并妥善保管。**包内不含生产密钥、账号、模型令牌或业务数据。**

默认 HTTPS `19460/tcp` 对客户端开放，Control `14099/tcp` 仅监听本机。安装后从管理界面配置私网模型地址、凭据、插件/业务数据连接和用户权限，再定向验证聊天、插件、历史会话、线索、图谱及重启恢复。

## 运维命令

```sh
sudo systemctl status peixian-private-worker.service
sudo systemctl restart peixian-private-worker.service
sudo systemctl stop peixian-private-worker.service
sudo journalctl -u peixian-private-worker.service -n 200 --no-pager
sudo /opt/peixian-private/20260928/venv/bin/python \
  /opt/peixian-private/20260928/source/deploy/peixian/platform-manage.py status \
  --config /etc/peixian-private/platform.json
```

主机重启后，Docker Compose 服务采用 `restart: unless-stopped`，worker 由 systemd 自动启动。重启验收需检查以上 service、容器健康状态及 HTTPS 登录。升级或回滚应先备份数据与配置，再按平台现有 `backup/restore` 流程和目标镜像 ID 操作；不要运行全新安装器覆盖旧实例。

## 离线重新构建

本包同时提供固定源码快照、基础镜像、前端依赖和 Python wheels。需重建 Control/Gateway 时运行：

```sh
sudo sh build-from-source.sh /var/tmp/peixian-rebuild-20260928
```

脚本校验包及基础镜像 ID，使用随包 Node 20 在禁网容器中运行前端 typecheck/build，再使用 `--network none --pull=false` 构建 Control/Gateway。重建会生成新的本地镜像 ID；上线前应重新做定向验证并更新镜像校验清单。Agent 采用包中固定的正式镜像，若其源码或运行时需升级，应单独发布有源码提交、二进制构建记录和新镜像 ID 的 Agent 版本。

## 常见问题

| 现象 | 检查和处理 |
| --- | --- |
| `fail.architecture` 或镜像平台不符 | 仅支持 amd64；在对应架构重新编译和打包，不要强制运行。 |
| Docker/Compose/Python/ACL 探测失败 | 由现场运维安装并启动要求版本，重新运行探测。Python 需要可用的 `venv` 与 `pip`。 |
| SELinux 拦截 bind mount 或证书读取 | 查看 audit/journal；检查文件标签、目录执行权限及安装时设置的 UID 10001 ACL。按欧拉系统策略修复标签，不建议直接关闭 SELinux。 |
| `server_port_occupied` | 用 `ss -lnt` 核对 `19460`/`14099`，改用空闲端口并同步 `public_url`、防火墙及证书配置。 |
| 网段冲突或容量不足 | 根据探测报告换未使用的私网 `/16`–`/24` 网段；按主机资源调小运行实例或补足 CPU、内存、磁盘。 |
| TLS 检查失败 | 检查证书与私钥匹配、文件路径、权限和完整链；客户端需信任私网 CA。 |
| `SHA256SUMS` 或 image ID 不符 | 停止安装，重新传输包；不要修改校验文件绕过检查。 |
| 容器正常但无法聊天 | 检查私网模型地址、凭据、相关插件和数据服务可达性；查看 Control、Gateway 及 worker 日志。首次包不携带线上配置。 |
| 字体加载失败或显示回退字体 | 在浏览器网络面板检查本站 `/assets/*.ttf` 返回 200，并核对 Control 镜像 `static` 中的文件；无需访问 Google Fonts/CDN。 |
| 重启后执行器不恢复 | `systemctl status` 与 `journalctl -u peixian-private-worker.service`；检查 Docker 服务、配置路径和镜像 ID。 |

## 已知边界

本轮在现有服务器构建并做定向验证。目标欧拉主机版本未提供，因此尚未完成该主机的实际兼容与重启验收。私网模型、证书、业务网络和数据服务由部署方提供并在现场联调。
