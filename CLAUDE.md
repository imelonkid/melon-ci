# melon-ci

可复用的 GitHub Actions 流水线（**公开仓库**）：PR 检查、服务端发布 / 回滚 / 状态、桌面端发布、小程序发布、库发布（npm）、发布门禁。业务仓库用 `uses: imelonkid/melon-ci/...@v2` 调用（`v1` 不再更新）。

## 边界（强制）

项目地图与契约见运维仓库 `$OPS_REPO/docs/09-projects.md`。

- **本项目负责**：流水线本体（`.github/workflows/*.yml`）、发布门禁（`.github/actions/release-gate`）
- **本项目不负责**：业务代码；**坐标与密钥**（一律由调用方的 secrets / vars 提供，本仓库公开，零敏感信息）；门户（melon-portal）
- **契约**：
  - 对业务仓库：当前主版本（`@v2`）的输入与权限。破坏性改动发新的主版本，不移动旧 tag 去破坏现有调用方；兼容改动才移动当前主版本 tag
  - 对门户：任务名（job `name`）、步骤名、run-name 约定被门户的编排绑定。**改任务名 / 步骤名时，同日改运维仓库 `portal/config.json` 的绑定和 melon-portal 内置流水线的默认绑定**
  - 对部署入口：只调用 deploy-agent 公开的指令

## 约定

- 不写任何主机地址、IP、端口、内网网段、服务器路径；不在日志里打印 secrets
- 步骤要有中文 `name`（门户和 Actions 页面都显示它）
- 权限：发布流水线（`server-release`、`mp-release`、`npm-release`）不自己声明 `permissions`，继承调用方——被调用方多要一项而调用方没给，整条流水线起不来；需要的权限写在文件头注释和 README 里
- 私有包：读包令牌只经环境变量 `NODE_AUTH_TOKEN` / BuildKit secret `npm_token` 传，不写进镜像层、不打印
- 提交信息 `<类型>(<范围>): <中文描述>`
