import json, os, re, subprocess, tomllib
from pathlib import Path
run_id = os.environ['BUILD_RUN_ID']
with open('Cargo.toml', 'rb') as manifest:
    version = tomllib.load(manifest)['package']['version']
assert re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version), 'Stable version required'
release_branch = f'release/{version}'
# 发布只能消费对应软件版本分支的成功构建，不能借用其它分支或旧提交的产物。
assert os.environ.get('GITHUB_REF') == f'refs/heads/{release_branch}', 'Release branch must match package version'
assert os.environ.get('GITHUB_ACTIONS') == 'true', 'GitHub Actions context required'
assert re.fullmatch(r'[0-9]+', run_id), 'Invalid build run ID'
for name in ['AMD64_CONFIG_DIGEST', 'ARM64_CONFIG_DIGEST']:
    assert re.fullmatch(r'sha256:[a-f0-9]{64}', os.environ[name]), 'Invalid config digest'
repo, sha = os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_SHA']
run = json.loads(subprocess.check_output(['gh', 'api', f'repos/{repo}/actions/runs/{run_id}']))
assert run['head_sha'] == sha and run['head_branch'] == release_branch, 'Source revision differs'
assert run['event'] in ['push', 'workflow_dispatch'], 'Untrusted build event'
assert run['path'] == '.github/workflows/ci.yml', 'Unexpected build workflow'
assert run['status'] == 'completed' and run['conclusion'] == 'success', 'Build is not successful'
for branch in ['master', release_branch]:
    ref = json.loads(subprocess.check_output(['gh', 'api', f'repos/{repo}/git/ref/heads/{branch}']))
    assert ref['object']['sha'] == sha, f'{branch} has a different revision'
namespace = os.environ['HUB_NAMESPACE']
assert re.fullmatch(r'[a-z0-9][a-z0-9_-]*', namespace), 'Invalid Docker Hub namespace'
assert namespace == 'nasaruntime', 'Docker Hub documentation and namespace must agree'
assert Path('docker/README.md').is_file(), 'Docker Hub overview is required'
with open(os.environ['GITHUB_ENV'], 'a') as output:
    output.write(f'IMAGE={namespace}/saga-server\nVERSION={version}\n')
