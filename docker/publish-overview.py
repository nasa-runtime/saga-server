import json, os, urllib.error, urllib.request
from pathlib import Path
# 镜像版本内容确认后才更新公开说明，避免说明指向尚未确认的镜像。
assert os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('GITHUB_REF') == 'refs/heads/release', 'Release workflow required'
credentials = {'identifier': os.environ['HUB_USERNAME'], 'secret': os.environ['HUB_TOKEN']}
request = urllib.request.Request('https://hub.docker.com/v2/auth/token', data=json.dumps(credentials).encode(), headers={'Content-Type': 'application/json'})
with urllib.request.urlopen(request, timeout=30) as response:
    token = json.load(response)['access_token']
print(f'::add-mask::{token}')
overview = Path('docker/README.md').read_text()
assert len(overview.encode('utf-8')) <= 25000, 'Repository overview exceeds its UTF-8 budget'
description = 'Saga 协调服务：新增流程无需重启，多注册中心、持久恢复、幂等与补偿。'
assert len(description.encode('utf-8')) <= 100, 'Repository summary exceeds its UTF-8 budget'
url = f'https://hub.docker.com/v2/repositories/{os.environ["IMAGE"]}/'
request = urllib.request.Request(url, data=json.dumps({'description': description, 'full_description': overview}).encode(), headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {token}'}, method='PATCH')
try:
    with urllib.request.urlopen(request, timeout=30):
        pass
except urllib.error.HTTPError as error:
    # 仓库说明属于公开内容；保留字段校验原因，并移除可能回显的认证材料。
    detail = error.read(4096).decode('utf-8', errors='replace')
    detail = detail.replace(token, '[redacted]').replace(os.environ['HUB_TOKEN'], '[redacted]')
    raise SystemExit(f'Repository overview rejected: HTTP {error.code}: {detail}')
request = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
with urllib.request.urlopen(request, timeout=30) as response:
    result = json.load(response)
assert result['full_description'] == overview, 'Docker Hub overview differs'
assert result['description'] == description, 'Docker Hub summary differs'
