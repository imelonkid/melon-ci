# melon-ci

melonkid 各项目共用的 GitHub Actions 可复用流水线（开发发布平台 P4，方案见私有仓库 melon-ops 的 `docs/release-platform.html`）。

**公开仓库，不含任何密钥**：密钥只在各项目的 GitHub Secrets / Environments 里，由调用方传入。

| 流水线 | 用途 | 状态 |
|---|---|---|
| [`pr-check.yml`](.github/workflows/pr-check.yml) | PR 检查：密钥扫描、运维规范、项目测试、镜像构建 | ✅ |
| [`server-release.yml`](.github/workflows/server-release.yml) | 服务端发布：门禁（发布窗口、main 的 CI 必须绿）→ 打 tag → 构建 → 经部署入口上传并部署 → GitHub Deployments 记录 | ✅ |
| [`server-rollback.yml`](.github/workflows/server-rollback.yml) | 服务端回滚（不受窗口限制，秒级） | ✅ |
| [`server-status.yml`](.github/workflows/server-status.yml) | 线上版本与最近部署事件 | ✅ |
| `desktop-release.yml` / `harmony-release.yml` | 客户端发布 | P4.4 |

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
    uses: imelonkid/melon-ci/.github/workflows/pr-check.yml@v1
```

约定：`scripts/ci-test.sh` 存在就跑；`deploy/Dockerfile` 存在就构建镜像（`deploy/prepare-context.sh` 用来准备构建上下文）。

发布 / 回滚需要仓库里有：Secret `DEPLOY_SSH_KEY`（主机部署入口的钥匙，只能操作本服务）、变量 `DEPLOY_HOST`（`deploy@<IP>`）与 `DEPLOY_KNOWN_HOSTS`。部署入口 deploy-agent 在私有运维仓库里。

## 版本

调用方固定在 `@v1`。不兼容的改动发 `v2`；兼容的改动把 `v1` 移到新提交。

## License

MIT
