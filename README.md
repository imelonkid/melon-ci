# melon-ci

melonkid 各项目共用的 GitHub Actions 可复用流水线（开发发布平台 P4，方案见私有仓库 melon-ops 的 `docs/release-platform.html`）。

**公开仓库，不含任何密钥**：密钥只在各项目的 GitHub Secrets / Environments 里，由调用方传入。

| 流水线 | 用途 | 状态 |
|---|---|---|
| [`pr-check.yml`](.github/workflows/pr-check.yml) | PR 检查：密钥扫描、运维规范、项目测试、镜像构建 | ✅ |
| [`server-release.yml`](.github/workflows/server-release.yml) | 服务端发布：门禁（发布窗口、main 的 CI 必须绿）→ 打 tag → 构建 → 经部署入口上传并部署 → GitHub Deployments 记录 | ✅ |
| [`server-rollback.yml`](.github/workflows/server-rollback.yml) | 服务端回滚（不受窗口限制，秒级） | ✅ |
| [`server-status.yml`](.github/workflows/server-status.yml) | 线上版本与最近部署事件 | ✅ |
| [`desktop-release.yml`](.github/workflows/desktop-release.yml) | 桌面端发布：门禁 → macOS 构建 → 对象存储 + 版本清单 + GitHub Release | ✅ |
| [`actions/release-gate`](.github/actions/release-gate/action.yml) | 各端共用的发布门禁：发布窗口、main CI 全绿、打 tag | ✅ |
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

发布 / 回滚需要仓库里有 `production` 环境（只允许 main 分支，需要 GitHub Pro 才能在私有仓库使用）：环境 Secret `DEPLOY_SSH_KEY`（主机部署入口的钥匙，只能操作本服务）、环境变量 `DEPLOY_HOST`（`deploy@<IP>`）与 `DEPLOY_KNOWN_HOSTS`；**镜像仓库（v2 起必需）**：环境变量 `ACR_REGISTRY`、`ACR_USERNAME`，环境 Secret `ACR_PASSWORD`。部署入口 deploy-agent 在私有运维仓库里。

## 版本

调用方固定在主版本（`@v2`）。不兼容的改动发新的主版本；兼容的改动把当前主版本 tag 移到新提交。

| 版本 | 变化 |
|---|---|
| `v2`（2026-10-14） | 服务端发布**必须配镜像仓库**（项目基线 v1）：没配直接失败，去掉「经 SSH 上传镜像」的回退 |
| `v1` | 首版；不再更新 |

## License

MIT
