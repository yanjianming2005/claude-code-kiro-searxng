# Claude Code + Kiro Gateway + SearXNG

一套可自行安装、仅监听本机的 Claude Code 兼容接入方案：

- Kiro Gateway 提供 Anthropic API 兼容接口。
- 中文 `WebSearch` 交给本地 SearXNG，聚合百度、必应、360 和搜狗。
- 英文 `WebSearch` 保留 Kiro 原生搜索。
- SearXNG 故障或无结果时，中文搜索自动回退 Kiro。

本项目减少对 Anthropic 官方账号登录链路的直接依赖，但不承诺规避任何平台风控。请遵守 Kiro、AWS、Anthropic 及搜索引擎的服务条款，只使用自己有权访问的账户和数据。

## 运行结构

```text
Claude Code / VS Code
        |
        | Anthropic API :8767
        v
   Kiro Gateway
      |       |
      |       +-- 中文查询 --> SearXNG :8768
      |                         |-- 百度
      |                         |-- 必应（zh-CN）
      |                         |-- 360 搜索
      |                         +-- 搜狗
      |
      +-- 模型请求 / 英文搜索 --> Kiro
```

默认情况下，两个服务都只绑定 `127.0.0.1`。如需让局域网其他电脑使用，只开放 Gateway 的 `8767`；SearXNG 的 `8768` 始终留在服务端本机。

## 前置条件

1. macOS 或 Linux。
2. Docker Desktop，或带 Docker Compose v2 的 Docker Engine。
3. 已安装并登录 Kiro IDE，或者已经执行过 `kiro-cli login`。
4. 已安装 Claude Code。

安装程序会自动寻找以下凭据之一，不会复制或上传凭据：

- `~/.aws/sso/cache/kiro-auth-token.json`
- `~/.local/share/kiro-cli/data.sqlite3`

## 一键安装

```bash
git clone https://github.com/yanjianming2005/claude-code-kiro-searxng.git
cd claude-code-kiro-searxng
./scripts/install.sh
```

如果这台电脑要作为局域网 Gateway 服务器，首次安装改为：

```bash
GATEWAY_BIND_HOST=0.0.0.0 ./scripts/install.sh
```

安装脚本会：

1. 检查并启动 Docker Desktop。
2. 检测本机 Kiro 登录凭据和 Profile ARN。
3. 自动生成本机 Gateway API Key 与 SearXNG secret。
4. 检测 `127.0.0.1:8118`；若存在，则让 Gateway 通过该代理连接 Kiro。
5. 构建并启动两个容器。
6. 检查 Gateway，并实际执行一次中文聚合搜索。
7. 生成仅保存在本机的 `.env` 和 `.claude-env`。

安装完成后，在当前终端执行：

```bash
source ./.claude-env
claude
```

如需每次打开终端自动生效，可以把下面一行加入 `~/.zshrc`：

```bash
source "/你的仓库绝对路径/.claude-env"
```

`.env` 和 `.claude-env` 已加入 `.gitignore`，不要把它们发给别人或提交到 GitHub。

## Claude Code 正确配置

安装脚本自动生成的配置等价于：

```bash
export ANTHROPIC_BASE_URL="http://127.0.0.1:8767"
export ANTHROPIC_API_KEY="安装程序生成的本机密钥"
unset ANTHROPIC_AUTH_TOKEN

export ANTHROPIC_MODEL="claude-opus-5"
export ANTHROPIC_DEFAULT_OPUS_MODEL="claude-opus-5"
export ANTHROPIC_DEFAULT_SONNET_MODEL="claude-sonnet-5"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="claude-haiku-4.5"
export CLAUDE_CODE_MAX_CONTEXT_TOKENS="1000000"
export CLAUDE_CODE_MAX_OUTPUT_TOKENS="128000"
```

必须清除 `ANTHROPIC_AUTH_TOKEN`，否则 Claude Code 可能优先采用已有登录令牌，并跳过本地 API Key 配置。

### VS Code 插件

如果从 Dock/Finder 启动 VS Code，它通常不会继承终端里的环境变量。可在 Claude Code 插件设置中加入：

```jsonc
{
  "claudeCode.disableLoginPrompt": true,

  "claudeCode.environmentVariables": [
    {
      "name": "ANTHROPIC_BASE_URL",
      "value": "http://127.0.0.1:8767"
    },
    {
      "name": "ANTHROPIC_API_KEY",
      "value": ""
    },
    {
      "name": "ANTHROPIC_AUTH_TOKEN",
      "value": "复制 .env 中的 PROXY_API_KEY"
    },
    {
      "name": "CLAUDE_CODE_SKIP_AUTH_LOGIN",
      "value": "1"
    },
    {
      "name": "ANTHROPIC_MODEL",
      "value": "claude-opus-5"
    },
    {
      "name": "ANTHROPIC_DEFAULT_OPUS_MODEL",
      "value": "claude-opus-5"
    },
    {
      "name": "ANTHROPIC_DEFAULT_SONNET_MODEL",
      "value": "claude-sonnet-5"
    },
    {
      "name": "ANTHROPIC_DEFAULT_HAIKU_MODEL",
      "value": "claude-haiku-4.5"
    },
    {
      "name": "CLAUDE_CODE_MAX_CONTEXT_TOKENS",
      "value": "1000000"
    },
    {
      "name": "CLAUDE_CODE_MAX_OUTPUT_TOKENS",
      "value": "128000"
    },
    {
      "name": "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC",
      "value": "1"
    }
  ]
}
```

终端 Claude Code 和 VS Code 插件的认证写法不同：

- 终端 CLI 使用 `ANTHROPIC_API_KEY`，并 `unset ANTHROPIC_AUTH_TOKEN`。
- VS Code Claude Code 2.1.221 的 Agent SDK 宿主模式使用 `ANTHROPIC_AUTH_TOKEN`。
- VS Code 中把 `ANTHROPIC_API_KEY` 显式设为空字符串，是为了覆盖登录 Shell 从 `~/.zshrc` 继承来的非空值；不要删除这个空值，也不要填入真实 Key。
- `ANTHROPIC_AUTH_TOKEN` 的值必须与服务端 `.env` 中的 `PROXY_API_KEY` 完全相同。

保存后使用 `Cmd+Q` 完全退出 VS Code，再重新打开。只执行 `Developer: Reload Window` 有时不能清除旧 Extension Host 的环境和认证缓存。

## 日常命令

```bash
# 启动并检查
./scripts/start.sh

# 查看实时日志
./scripts/logs.sh

# 健康检查 + 中文搜索实测
./scripts/health-check.sh

# 停止并移除容器（不会删除本机 Kiro 凭据）
./scripts/stop.sh

# 更新代码后重建
git pull
docker compose up -d --build
```

服务地址：

| 服务 | 地址 |
|---|---|
| Kiro Gateway | `http://127.0.0.1:8767` |
| Gateway 健康检查 | `http://127.0.0.1:8767/health` |
| SearXNG | `http://127.0.0.1:8768` |

## 供局域网其他电脑使用

服务端 `.env` 设置：

```env
GATEWAY_BIND_HOST=0.0.0.0
GATEWAY_PORT=8767
```

修改后重新创建 Gateway 容器：

```bash
docker compose up -d --force-recreate kiro-gateway
```

在服务端查看局域网 IP：

```bash
# macOS Wi-Fi
ipconfig getifaddr en0

# Linux
hostname -I
```

假设服务端地址是 `192.168.0.88`，其他电脑配置：

```bash
export ANTHROPIC_BASE_URL="http://192.168.0.88:8767"
export ANTHROPIC_API_KEY="服务端 .env 中的 PROXY_API_KEY"
unset ANTHROPIC_AUTH_TOKEN

export ANTHROPIC_MODEL="claude-opus-5"
export ANTHROPIC_DEFAULT_OPUS_MODEL="claude-opus-5"
export ANTHROPIC_DEFAULT_SONNET_MODEL="claude-sonnet-5"
export ANTHROPIC_DEFAULT_HAIKU_MODEL="claude-haiku-4.5"
export CLAUDE_CODE_MAX_CONTEXT_TOKENS="1000000"
export CLAUDE_CODE_MAX_OUTPUT_TOKENS="128000"
```

客户端可先验证：

```bash
curl http://192.168.0.88:8767/health
```

### 大正文从本地文件更新 KM

Kiro 偶尔会在生成较长的 MCP 工具参数时中断。若完整正文已经保存为本地文件，安装仓库提供的文件桥接工具后，Claude Code 只需生成文章 ID 和文件路径，正文由本机直接读取并提交，不再经过模型输出通道：

```bash
claude mcp add --scope user jemy-km-file -- \
  python3 "$(pwd)/scripts/km_file_mcp.py"
```

重启 VS Code 后会出现 `update_article_from_file` 工具。示例任务：

```text
使用 update_article_from_file，把 KM 2180 更新为 /tmp/km2180_restore.md 的完整内容。
```

默认只允许读取 `/tmp` 和当前用户主目录内的 UTF-8 文件，单文件上限 10 MiB。可通过 `KM_FILE_ALLOWED_ROOTS`、`KM_FILE_MAX_BYTES` 和 `KM_MCP_URL` 调整。

`8768` 不需要也不应该监听 `0.0.0.0`：Claude Code 只访问 Gateway，Gateway 在服务端内部调用 SearXNG。

该接口是普通 HTTP，仅适合可信局域网。不要在路由器上做公网端口映射；跨网络访问建议使用 VPN 组网或带 HTTPS 的反向代理。API Key 应通过安全渠道发给同事。

## WebSearch 路由

Gateway 根据查询文本中是否存在汉字进行路由：

| 查询 | 路由 |
|---|---|
| `深圳南山区二手房均价` | SearXNG 中文聚合 |
| `中山 Lanbowan property price` | SearXNG 中文聚合 |
| `Python 3.14 release notes` | Kiro 原生 WebSearch |

中文结果会转换为 Claude Code 认识的 `web_search_result`，因此无需修改 Claude Code 的工具名。每次最多返回 12 条去重结果。

## 代理配置

安装时若检测到本机 `127.0.0.1:8118`，会自动写入：

```env
VPN_PROXY_URL=http://host.docker.internal:8118
```

注意：容器中的 `127.0.0.1` 是容器自身，所以必须使用 `host.docker.internal` 访问宿主机代理。

如果你的代理端口不同，修改 `.env` 后重建：

```bash
docker compose up -d --force-recreate
```

中国搜索引擎默认直连，不经过该代理。

## 故障排查

### `Unable to connect to API (ConnectionRefused)`

```bash
docker compose ps
./scripts/health-check.sh
./scripts/logs.sh
```

确认 `8767` 和 `8768` 没有被其他程序占用。

### VS Code 仍跳转 Claude 登录页

按下面顺序处理：

1. 执行 `claude auth logout`，清除已经失效但优先级更高的 Claude OAuth 凭据。
2. 确认 VS Code 设置包含 `claudeCode.disableLoginPrompt: true` 和 `CLAUDE_CODE_SKIP_AUTH_LOGIN=1`。
3. 确认 `ANTHROPIC_API_KEY` 是空字符串，真实 Gateway Key 只写入 `ANTHROPIC_AUTH_TOKEN`。
4. 使用 `Cmd+Q` 完全退出 VS Code，再重新打开。

如果日志出现 `OAuth refresh token is no longer valid` 或 `OAuth tokens found in secure storage`，说明旧 OAuth 尚未清理干净。

### `Could not resolve authentication method`

这是 VS Code 2.1.221 Agent SDK 宿主模式没有采用 `ANTHROPIC_API_KEY` 的典型错误。此时请求通常还没有到达 Gateway，因此重启 Gateway 没有作用。

按上面的 VS Code 配置改用 `ANTHROPIC_AUTH_TOKEN`，并将 `ANTHROPIC_API_KEY` 显式置空。可以用以下方式区分故障位置：

```bash
# 客户端查看 Claude Code 扩展日志
# VS Code: View -> Output -> Claude Code

# 服务端查看 Gateway 是否收到 POST /v1/messages
./scripts/logs.sh
```

如果客户端报错时服务端没有对应的 `POST /v1/messages`，问题在 VS Code 本地认证；如果已经收到请求并返回 401，再检查 `ANTHROPIC_AUTH_TOKEN` 与 `PROXY_API_KEY` 是否一致。

### `incomplete chunked read`

Gateway 默认会在尚未向客户端输出内容时自动重试两次；如果回答已经输出了一部分，则把断流转换成合法的截断结束，避免盲目重放导致文本或工具调用重复。可在 `.env` 调整：

```bash
STREAM_BODY_MAX_RETRIES=2
STREAM_BODY_RETRY_BASE_DELAY=0.5
STREAM_GRACEFUL_EOF=true
TRUNCATION_RECOVERY=true
```

`STREAMING_READ_TIMEOUT` 只控制等待时间，无法阻止上游主动关闭连接。

### `Web search failed`

先直接打开 `http://127.0.0.1:8768`，再运行：

```bash
./scripts/health-check.sh
docker compose logs --tail=100 searxng
```

### Gateway 无法刷新 Kiro Token

重新登录 Kiro，然后重启：

```bash
kiro-cli login
./scripts/start.sh
```

如果使用 Kiro IDE，请打开 Kiro 确认登录状态，再重新运行 `./scripts/install.sh`。

### VS Code 一直跳登录页

1. 确认 Gateway 健康检查返回成功。
2. 确认插件设置包含 `ANTHROPIC_BASE_URL` 和 `ANTHROPIC_API_KEY`。
3. 删除插件设置中的 `ANTHROPIC_AUTH_TOKEN`。
4. 完全退出并重启 VS Code。

## 安全边界

- 仓库不包含任何共享账户、Token、Profile ARN 或固定 API Key。
- 每位使用者必须用自己的 Kiro 登录凭据。
- Gateway 默认只监听本机，可显式开放给可信局域网；SearXNG 始终只监听本机。
- 不要提交 `.env`、`.claude-env`、`credentials.json`、`state.json` 或日志。
- 如果怀疑本机密钥泄露，删除 `.env` 后重新运行安装脚本即可生成新密钥。

## 开发与测试

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python -m pytest -q
```

本仓库基于 [jwadow/kiro-gateway](https://github.com/jwadow/kiro-gateway)，保留原项目 AGPL-3.0 许可证。上游原始说明见 [docs/UPSTREAM_README.md](docs/UPSTREAM_README.md)。SearXNG 配置遵循其官方设置和 Search API。
