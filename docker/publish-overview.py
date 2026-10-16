import json, os, urllib.request
from pathlib import Path
# 镜像版本内容确认后才更新公开说明，避免说明指向尚未确认的镜像。
assert os.environ.get('GITHUB_ACTIONS') == 'true' and os.environ.get('GITHUB_REF') == f'refs/heads/release/{os.environ["VERSION"]}', 'Matching release workflow required'
credentials = {'identifier': os.environ['HUB_USERNAME'], 'secret': os.environ['HUB_TOKEN']}
request = urllib.request.Request('https://hub.docker.com/v2/auth/token', data=json.dumps(credentials).encode(), headers={'Content-Type': 'application/json'})
with urllib.request.urlopen(request, timeout=30) as response:
    token = json.load(response)['access_token']
print(f'::add-mask::{token}')
overview = Path('docker/README.md').read_text()
description = 'Saga orchestrator: workflows without server restarts; multi-registry discovery and durable recovery.'
url = f'https://hub.docker.com/v2/repositories/{os.environ["IMAGE"]}/'
request = urllib.request.Request(url, data=json.dumps({'description': description, 'full_description': overview}).encode(), headers={'Content-Type': 'application/json', 'Authorization': f'Bearer {token}'}, method='PATCH')
with urllib.request.urlopen(request, timeout=30):
    pass
request = urllib.request.Request(url, headers={'Authorization': f'Bearer {token}'})
with urllib.request.urlopen(request, timeout=30) as response:
    result = json.load(response)
assert result['full_description'] == overview, 'Docker Hub overview differs'
assert result['description'] == description, 'Docker Hub summary differs'
