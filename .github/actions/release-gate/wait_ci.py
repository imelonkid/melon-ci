#!/usr/bin/env python3
"""等待并核验 main 最新提交的 CI 检查全部通过（供 release-gate 调用，只用标准库）。"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from typing import Callable


def gh_json(path: str, optional: bool = False):
    proc = subprocess.run(["gh", "api", path], capture_output=True, text=True)
    if proc.returncode != 0:
        if optional:
            return None
        msg = (proc.stderr or proc.stdout).strip() or f"gh api {path} 退出码 {proc.returncode}"
        raise RuntimeError(msg)
    return json.loads(proc.stdout)


def latest_by_name(check_runs: list[dict], prefix: str = "check /") -> dict[str, dict]:
    """按检查名去重，保留最新一条（重跑 CI 时避免旧失败记录误拦）。"""
    latest: dict[str, dict] = {}
    for run in check_runs or []:
        name = run.get("name") or ""
        if not name.startswith(prefix):
            continue
        prev = latest.get(name)
        if prev is None or (run.get("id") or 0) >= (prev.get("id") or 0):
            latest[name] = run
    return latest


def evaluate(
    check_runs: list[dict],
    required_contexts: list[str] | None = None,
    prefix: str = "check /",
) -> dict:
    """判定当前 CI 状态：success / failed / waiting / missing。"""
    latest = latest_by_name(check_runs, prefix=prefix)
    req_list: list[str] = []
    for ctx in required_contexts or []:
        if isinstance(ctx, str) and ctx.startswith(prefix) and ctx not in req_list:
            req_list.append(ctx)

    if req_list:
        missing = [name for name in req_list if name not in latest]
        target = [latest[name] for name in req_list if name in latest]
        req_set = set(req_list)
        optional_failed = [
            run for name, run in latest.items()
            if name not in req_set and run.get("status") == "completed" and run.get("conclusion") != "success"
        ]
    else:
        missing = []
        target = list(latest.values())
        optional_failed = []

    failed = [r for r in target if r.get("status") == "completed" and r.get("conclusion") != "success"]
    pending = [r for r in target if r.get("status") != "completed"]
    passed = [r for r in target if r.get("status") == "completed" and r.get("conclusion") == "success"]

    if failed:
        state = "failed"
    elif target and not missing and not pending:
        state = "success"
    elif pending:
        state = "waiting"
    else:
        state = "missing"

    return {
        "state": state,
        "required": req_list,
        "target": target,
        "passed": passed,
        "pending": pending,
        "failed": failed,
        "missing": missing,
        "optional_failed": optional_failed,
    }


def wait_for_ci(
    sha: str,
    fetch_runs: Callable[[], list[dict]],
    fetch_required: Callable[[], list[str]],
    *,
    wait_seconds: int = 300,
    poll_seconds: int = 10,
    appear_seconds: int = 60,
    prefix: str = "check /",
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    out=None,
) -> int:
    stream = out or sys.stdout
    short_sha = sha[:8]
    required = fetch_required() or []
    started = clock()
    announced_req = False

    while True:
        res = evaluate(fetch_runs(), required, prefix=prefix)
        elapsed = max(0.0, clock() - started)

        if res["required"] and not announced_req:
            print(f"按分支保护的必过检查（{len(res['required'])} 项）", file=stream, flush=True)
            announced_req = True

        state = res["state"]
        if state == "success":
            for r in res["optional_failed"]:
                print(f"::notice::非必过检查未通过：{r['name']}（不拦发布）", file=stream, flush=True)
            print(f"main@{short_sha}：CI 检查 {len(res['target'])} 项，全部通过", file=stream, flush=True)
            return 0

        if state == "failed":
            print(
                f"main@{short_sha}：CI 检查 {len(res['target'])} 项，失败 {len(res['failed'])} 项",
                file=stream,
                flush=True,
            )
            for r in res["target"]:
                print(f"  {r['name']}：{r.get('status')} {r.get('conclusion')}", file=stream, flush=True)
            print("::error::main 的 CI 没通过，不能发布", file=stream, flush=True)
            return 1

        if state == "missing":
            limit = min(appear_seconds, wait_seconds)
            if elapsed >= limit:
                if res["missing"]:
                    miss = "、".join(res["missing"])
                    print(f"::error::main 最新提交缺少必过检查：{miss}（等 CI 跑完再发）", file=stream, flush=True)
                else:
                    print("::error::main 最新提交没有 CI 结果（等 CI 跑完再发）", file=stream, flush=True)
                return 1
            wait_step = min(poll_seconds, max(0.0, limit - elapsed))
            detail = f"待出现：{'、'.join(res['missing'])}" if res["missing"] else "尚无检查记录"
            print(
                f"main@{short_sha}：等待 CI 启动（{detail}，已等 {int(elapsed)}s / {limit}s）",
                file=stream,
                flush=True,
            )
            if wait_step > 0:
                sleep(wait_step)
            continue

        # state == "waiting"
        if elapsed >= wait_seconds:
            for r in res["target"]:
                print(f"  {r['name']}：{r.get('status')} {r.get('conclusion')}", file=stream, flush=True)
            if res["missing"]:
                print(f"  待出现：{'、'.join(res['missing'])}", file=stream, flush=True)
            print(f"::error::等待 main 的 CI 超时（已等 {wait_seconds} 秒），仍有检查未完成", file=stream, flush=True)
            return 1

        parts = [f"{r['name']}={r.get('status')}" for r in res["pending"]]
        if res["missing"]:
            parts.extend(f"{name}=pending" for name in res["missing"])
        print(
            f"main@{short_sha}：CI 进行中（已通过 {len(res['passed'])} 项，等待 {len(parts)} 项：{'、'.join(parts)}），"
            f"已等 {int(elapsed)}s / {wait_seconds}s",
            file=stream,
            flush=True,
        )
        wait_step = min(poll_seconds, max(0.0, wait_seconds - elapsed))
        if wait_step > 0:
            sleep(wait_step)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="等待并校验 main 最新提交的 CI 检查全部通过")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--sha", required=True)
    ap.add_argument("--wait-seconds", type=int, default=300)
    ap.add_argument("--poll-seconds", type=int, default=10)
    ap.add_argument("--appear-seconds", type=int, default=60)
    ap.add_argument("--prefix", default="check /")
    args = ap.parse_args(argv)

    def fetch_required() -> list[str]:
        branch = gh_json(f"repos/{args.repo}/branches/main", optional=True)
        if not isinstance(branch, dict):
            return []
        return list((((branch.get("protection") or {}).get("required_status_checks") or {}).get("contexts")) or [])

    def fetch_runs() -> list[dict]:
        data = gh_json(f"repos/{args.repo}/commits/{args.sha}/check-runs?per_page=100")
        return list((data or {}).get("check_runs") or [])

    return wait_for_ci(
        args.sha,
        fetch_runs,
        fetch_required,
        wait_seconds=max(0, args.wait_seconds),
        poll_seconds=max(1, args.poll_seconds),
        appear_seconds=max(0, args.appear_seconds),
        prefix=args.prefix,
    )


if __name__ == "__main__":
    raise SystemExit(main())
