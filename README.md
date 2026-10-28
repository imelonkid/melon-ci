# melon-ci

melonkid 各项目共用的 GitHub Actions 可复用流水线（开发发布平台 P4，方案见私有仓库 melon-ops 的 `docs/release-platform.html`）。

**公开仓库，不含任何密钥**：密钥只在各项目的 GitHub Secrets / Environments 里，由调用方传入。

| 流水线 | 用途 | 状态 |
|---|---|---|
| [`pr-check.yml`](.github/workflows/pr-check.yml) | PR 检查：密钥扫描、运维规范、项目测试、镜像构建 | ✅ |
| [`server-release.yml`](.github/workflows/server-release.yml) | 服务端发布：门禁（发布窗口、main 的 CI 必须绿）→ 打 tag → 构建镜像 → 推镜像仓库 → 经部署入口部署 → GitHub Deployments 记录 | ✅ |
| [`server-rollback.yml`](.github/workflows/server-rollback.yml) | 服务端回滚（不受窗口限制，秒级） | ✅ |
| [`server-status.yml`](.github/workflows/server-status.yml) | 线上版本与最近部署事件 | ✅ |
| [`mp-release.yml`](.github/workflows/mp-release.yml) | 微信小程序发布：门禁 → 打 tag `mp-v` → 构建 → 经部署入口在固定 IP 主机上传为体验版（`mp-upload`）→ GitHub Release；提审 / 全量在微信后台 | ✅ |
| [`desktop-release.yml`](.github/workflows/desktop-release.yml) | 桌面端发布：门禁 → macOS 构建 → 对象存储 + 版本清单 + GitHub Release。`manifest: deploy`（默认，多端项目：清单经部署入口放服务端下载站）/ `oss`（独立桌面应用：清单也放对象存储，不需要部署入口）；`go-version` 构建前装 Go；`runner` 选 macOS 构建机；`sign: true` 用 Developer ID 正式签名并公证 | ✅ |
| [`npm-release.yml`](.github/workflows/npm-release.yml) | 库发布：门禁（main CI 绿，不查发布窗口）→ 打 tag → 测试 → 版本号按 tag 注入 → 发到 GitHub Packages → Release（说明取自 CHANGELOG） | ✅ |
| [`actions/release-gate`](.github/actions/release-gate/action.yml) | 各端共用的发布门禁：发布窗口（`check-window: false` 可关，库用）、main CI 全绿、打 tag | ✅ |
| `harmony-release.yml` | 鸿蒙发布 | 待 AGC 证书 |

## 使用

```yaml
# 项目仓库 .github/workflows/ci.yml
name: ci
on:
  pull_request:
  push:
    branches: [main]
jobs:
  check:
    uses: imelonkid/melon-ci/.github/workflows/pr-check.yml@v2
```

约定：`scripts/ci-test.sh` 存在就跑；`deploy/Dockerfile` 存在就构建镜像（`deploy/prepare-context.sh` 用来准备构建上下文）。

发布表单（项目仓库里调用发布流水线的 workflow）要自己写 `permissions`——`server-release`、`mp-release`、`npm-release` 不再自己声明，继承调用方：

```yaml
jobs:
  release:
    permissions: { contents: write, checks: read, deployments: write, packages: read }   # 不用私有包可去掉 packages: read
    uses: imelonkid/melon-ci/.github/workflows/server-release.yml@v2
    secrets: inherit
```

| 流水线 | 调用方要给的权限 |
|---|---|
| `server-release` | `contents: write`、`checks: read`、`deployments: write`；用私有包再加 `packages: read` |
| `mp-release` | `contents: write`、`checks: read`；用私有包再加 `packages: read` |
| `npm-release` | `contents: write`、`checks: read`、`packages: write` |
| `pr-check` | 不用给：自己声明了 `contents: read`、`packages: read` |

**私有包 `@imelonkid/*`**（GitHub Packages）：`pr-check` 的测试步骤、`server-release` / `mp-release` 的构建步骤都有环境变量 `NODE_AUTH_TOKEN`（= 本次运行的 `GITHUB_TOKEN`），项目的 `.npmrc` 引用它；镜像构建另传 BuildKit secret `npm_token`（Dockerfile：`RUN --mount=type=secret,id=npm_token NODE_AUTH_TOKEN=$(cat /run/secrets/npm_token) npm ci`），令牌不进镜像层。包那边要在 Package settings → Manage Actions access 里给用它的仓库读权限。

**库发布 `npm-release`**：`package.json` 的 `name` 是 `@imelonkid/<名>`、`publishConfig.registry` 指向 GitHub Packages，仓库里 `version` 固定 `0.0.0`（版本号按 tag 注入）；不查发布窗口；`CHANGELOG.md` 里有 `## vX.Y.Z` 一段就作为 Release 说明。示例见 melon-common。

发布 / 回滚需要仓库里有 `production` 环境（只允许 main 分支，需要 GitHub Pro 才能在私有仓库使用）：环境 Secret `DEPLOY_SSH_KEY`（主机部署入口的钥匙，只能操作本服务）、环境变量 `DEPLOY_HOST`（`deploy@<IP>`）与 `DEPLOY_KNOWN_HOSTS`；**镜像仓库（v2 起必需）**：环境变量 `ACR_REGISTRY`、`ACR_USERNAME`，环境 Secret `ACR_PASSWORD`。部署入口 deploy-agent 在私有运维仓库里。

**桌面端正式签名 `desktop-release` 的 `sign: true`**（默认关，照旧 ad-hoc 签名）：构建任务绑 `production` 环境，要这些环境 Secret，缺一项直接失败：

| Secret | 内容 |
|---|---|
| `MACOS_CERT_P12_BASE64`、`MACOS_CERT_P12_PASSWORD` | Developer ID Application 证书连私钥导出的 p12（base64）和它的导出密码 |
| `NOTARY_KEY_P8_BASE64`、`NOTARY_KEY_ID`、`NOTARY_ISSUER_ID` | App Store Connect API 密钥（公证用）：p8（base64）、Key ID、Issuer ID |
| `MACOS_PROVISION_PROFILE_BASE64` | 可选：Developer ID 描述文件（base64）。应用用到钥匙串访问组、iCloud 等受限权限才要，按应用各一份 |

分工：流水线把证书导入临时钥匙串（用完删除），经环境变量 `SIGN_IDENTITY`（证书全名）和 `PROVISIONING_PROFILE`（描述文件路径，配了才有）交给项目的发布脚本；**项目脚本负责签 .app**（由内到外签内嵌的程序，带 `--options runtime`、`--timestamp`）；构建完流水线再签 dmg、`notarytool` 公证、钉上公证票据，并用 `spctl` 复查。dmg 在 build 之后还会变，所以**安装包的 sha256 要在 publish 阶段算**。同一张证书和 API 密钥可以给同一个开发者账号下的所有应用用，但 Secret 按仓库各设一份。

## 版本

调用方固定在主版本（`@v2`）。不兼容的改动发新的主版本；兼容的改动把当前主版本 tag 移到新提交。

| 版本 | 变化 |
|---|---|
| `v2` 兼容更新（2026-10-28） | `desktop-release` 加 `sign`（Developer ID 签名 + 公证，默认关，默认行为不变）；补记 `runner` 输入（默认 `macos-14`） |
| `v2` 兼容更新（2026-10-20） | 新增 `npm-release`（库发布）；私有包 `@imelonkid/*`：PR 检查、服务端 / 小程序发布带读包令牌（测试与构建有 `NODE_AUTH_TOKEN`，镜像构建传 BuildKit secret `npm_token`）；发布流水线不再自己声明权限、继承调用方（用私有包的项目在发布表单加 `packages: read`）；`release-gate` 加 `check-window` |
| `v2` 兼容更新（2026-10-17） | 新增 `mp-release`（小程序发布） |
| `v2` 兼容更新（2026-10-15） | `desktop-release` 加 `manifest`、`go-version` 两个可选输入，默认行为不变 |
| `v2`（2026-10-14） | 服务端发布**必须配镜像仓库**（项目基线 v1）：没配直接失败，去掉「经 SSH 上传镜像」的回退 |
| `v1` | 首版；不再更新 |

## License

MIT
