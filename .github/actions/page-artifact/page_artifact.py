#!/usr/bin/env python3
"""仅打包公开页面；OSS 版本对象不可覆盖。部署交给内网执行器。"""
import argparse
import base64
import gzip
import hashlib
import hmac
import io
import json
import os
from pathlib import Path, PurePosixPath
import re
import subprocess
import tarfile
import time
from email.utils import formatdate
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPRedirectHandler

LIMIT = 64 * 1024 * 1024
FORMAT = 'melon-page/v1'


def git(*args):
    return subprocess.check_output(['git', *args])


def package(repo, project, tag, page_dir, out):
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('repo 不合法')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,40}', project):
        raise ValueError('project 不合法')
    if not re.fullmatch(r'page-v[0-9]+\.[0-9]+\.[0-9]+', tag):
        raise ValueError('页面 tag 必须是 page-vX.Y.Z')
    if not re.fullmatch(r'[A-Za-z0-9_-][A-Za-z0-9._/-]*', page_dir) or '..' in page_dir:
        raise ValueError('page-dir 必须是仓库相对目录')
    ref = f'refs/tags/{tag}'
    commit = git('rev-parse', f'{ref}^{{commit}}').decode().strip()
    # 已有 tag 也必须来自经审核的 main，禁止发布旁支内容。
    subprocess.run(['git', 'merge-base', '--is-ancestor', commit, 'origin/main'], check=True)
    raw = git('archive', '--format=tar', f'{ref}:{page_dir}')
    if len(raw) > LIMIT:
        raise ValueError('页面归档超过 64 MiB')
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        files = archive.getmembers()
        total = 0
        for f in files:
            parts = PurePosixPath(f.name).parts
            if f.name.startswith('/') or '..' in parts or not (f.isfile() or f.isdir()):
                raise ValueError(f'页面包含不安全文件：{f.name}')
            total += f.size
        if total > LIMIT or not any(f.name == 'index.html' and f.isfile() for f in files):
            raise ValueError('页面超过 64 MiB 或根目录缺 index.html')
    # 子树 archive 不带 commit 的 mtime，重建归档以保证跨时间重试仍是同一字节。
    normalized = io.BytesIO()
    stamp = int(git('show', '-s', '--format=%ct', commit).decode().strip())
    with tarfile.open(fileobj=io.BytesIO(raw)) as source, tarfile.open(fileobj=normalized, mode='w', format=tarfile.USTAR_FORMAT) as target:
        for member in sorted(source.getmembers(), key=lambda m: m.name):
            member.mtime = stamp
            member.uid = member.gid = 0
            member.uname = member.gname = ''
            member.mode = 0o755 if member.isdir() else 0o644
            target.addfile(member, source.extractfile(member) if member.isfile() else None)
    data = gzip.compress(normalized.getvalue(), mtime=0)
    manifest = dict(format=FORMAT, repo=repo, project=project, tag=tag,
                    commit=commit, path=page_dir, archive='site.tar.gz',
                    sha256=hashlib.sha256(data).hexdigest(), size=len(data))
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    (out / 'site.tar.gz').write_bytes(data)
    (out / 'manifest.json').write_text(json.dumps(manifest, sort_keys=True, separators=(',', ':')) + '\n')
    return manifest


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None  # 凭据和读取目标不跟随重定向


OPENER = build_opener(NoRedirect())


def put(base, bucket, key, data, content_type, access_id, access_secret, opener=OPENER):
    date = formatdate(usegmt=True)
    md5 = base64.b64encode(hashlib.md5(data).digest()).decode()
    canonical = f'PUT\n{md5}\n{content_type}\n{date}\nx-oss-forbid-overwrite:true\n/{bucket}/{key}'
    sig = base64.b64encode(hmac.new(access_secret.encode(), canonical.encode(), hashlib.sha1).digest()).decode()
    req = Request(f'{base}/{key}', data=data, method='PUT', headers={
        'Date': date, 'Content-MD5': md5, 'Content-Type': content_type,
        'x-oss-forbid-overwrite': 'true', 'Authorization': f'OSS {access_id}:{sig}'})
    try:
        with opener.open(req, timeout=60) as response:
            response.read(4096)
    except HTTPError as e:
        if e.code != 409:
            raise RuntimeError(f'OSS 上传失败：HTTP {e.code}，对象 {key}') from None
        e.close()
        # 网络返回丢失、包已上传而清单失败均可安全重试；必须读取并比较完整内容。
        with opener.open(f'{base}/{key}', timeout=60) as response:
            existing = response.read(len(data) + 1)
        if existing != data:
            raise ValueError(f'OSS 对象冲突，禁止覆盖：{key}')


def oss_config(env=os.environ):
    bucket, endpoint, access_id, access_secret = (env[k] for k in (
        'OSS_BUCKET', 'OSS_ENDPOINT', 'OSS_ACCESS_KEY_ID', 'OSS_ACCESS_KEY_SECRET'))
    if not all((bucket, endpoint, access_id, access_secret)):
        raise ValueError('缺 OSS 配置')
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{1,61}[a-z0-9]', bucket) or not re.fullmatch(r'oss-[a-z0-9-]+\.aliyuncs\.com', endpoint):
        raise ValueError('OSS 桶或 endpoint 不合法')
    return bucket, f'https://{bucket}.{endpoint}', access_id, access_secret


def upload(out, env=os.environ):
    bucket, base, access_id, access_secret = oss_config(env)
    out = Path(out)
    manifest = json.loads((out / 'manifest.json').read_text())
    prefix = f"{manifest['project']}/page/{manifest['tag']}"
    for name, content_type in [('site.tar.gz', 'application/gzip'), ('manifest.json', 'application/json')]:
        data = (out / name).read_bytes()
        started = time.monotonic()
        put(base, bucket, f'{prefix}/{name}', data, content_type, access_id, access_secret)
        # 不把上传成功等同于匿名可读：腾讯会以匿名方式取包。
        with OPENER.open(f'{base}/{prefix}/{name}', timeout=60) as response:
            downloaded = response.read(len(data) + 1)
        if downloaded != data:
            raise ValueError(f'匿名下载内容不一致：{name}')
        print(f'{name}：上传与匿名下载校验通过，{time.monotonic()-started:.1f}s')
    digest = hashlib.sha256((out / 'manifest.json').read_bytes()).hexdigest()
    receipt = dict(manifest, manifest_sha256=digest, manifest_url=f'{base}/{prefix}/manifest.json')
    (out / 'receipt.json').write_text(json.dumps(receipt, sort_keys=True) + '\n')
    output = env.get('GITHUB_OUTPUT')
    if output:
        with open(output, 'a') as f:
            f.write(f'manifest-sha256={digest}\ncommit={manifest["commit"]}\n')
    print(f'制品就绪：{manifest["tag"]}，commit={manifest["commit"]}；尚未部署')


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('command', choices=('package', 'upload'))
    ap.add_argument('--out', required=True)
    ap.add_argument('--repo')
    ap.add_argument('--project')
    ap.add_argument('--tag')
    ap.add_argument('--page-dir', default='site')
    a = ap.parse_args()
    if a.command == 'package':
        package(a.repo, a.project, a.tag, a.page_dir, a.out)
    else:
        upload(a.out)
