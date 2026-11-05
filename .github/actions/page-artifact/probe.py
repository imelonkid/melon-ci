#!/usr/bin/env python3
"""使用现有 GitHub production 凭据，只测试项目页面前缀的 OSS 权限。"""
import argparse
from datetime import datetime, timezone
import re
from urllib.error import HTTPError
from uuid import uuid4
import page_artifact as page


class Observe:
    def __init__(self, opener):
        self.opener, self.statuses = opener, []

    def open(self, request, timeout):
        try:
            result = self.opener.open(request, timeout=timeout)
        except HTTPError as e:
            self.statuses.append(e.code)
            raise
        self.statuses.append(result.getcode())
        return result


def probe(project, config=page.oss_config, opener=page.OPENER):
    if not re.fullmatch(r'[a-z0-9][a-z0-9-]{0,40}', project):
        raise ValueError('project 不合法')
    bucket, base, access_id, access_secret = config()
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    key = f'{project}/page/_checks/{stamp}-{uuid4().hex}/probe.txt'
    data = f'Hero OSS permission probe {stamp}\n'.encode()
    observed = Observe(opener)
    args = (base, bucket, key, data, 'text/plain', access_id, access_secret)
    page.put(*args, opener=observed)
    if observed.statuses != [200]:
        raise ValueError('首次上传未返回 HTTP 200')
    print('通过：首次上传 HTTP 200')
    observed.statuses.clear()
    with observed.open(f'{base}/{key}', timeout=30) as response:
        actual = response.read(len(data) + 1)
    if observed.statuses != [200] or actual != data:
        raise ValueError('匿名读取失败或内容不一致')
    print('通过：匿名下载 HTTP 200，内容一致')
    observed.statuses.clear()
    page.put(*args, opener=observed)
    if observed.statuses != [409, 200]:
        raise ValueError('同内容重试未触发 HTTP 409；禁止覆盖保护可能未生效')
    print('通过：同内容重试 HTTP 409，读取核对后安全接受')
    observed.statuses.clear()
    conflict = (base, bucket, key, b'conflicting contents\n', 'text/plain', access_id, access_secret)
    try:
        page.put(*conflict, opener=observed)
    except ValueError as e:
        if observed.statuses != [409, 200] or not str(e).startswith('OSS 对象冲突'):
            raise
    else:
        raise ValueError('不同内容覆盖未被拒绝')
    with observed.open(f'{base}/{key}', timeout=30) as response:
        if response.read(len(data) + 1) != data:
            raise ValueError('冲突测试后原内容发生变化')
    print('通过：不同内容覆盖被拒绝，原内容保持一致')
    print(f'测试对象（保留，不申请删除权限）：{base}/{key}')
    return key


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--project', required=True)
    probe(p.parse_args().project)
