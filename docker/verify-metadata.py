import json, os, re, subprocess, tomllib

# 说明可独立于镜像更新，但当前文档必须来自 release 的成功构建。
assert os.environ.get('GITHUB_ACTIONS') == 'true'
assert os.environ.get('GITHUB_REF') == 'refs/heads/release'
repo, documentation_sha = os.environ['GITHUB_REPOSITORY'], os.environ['GITHUB_SHA']
with open('Cargo.toml', 'rb') as source:
    version = tomllib.load(source)['package']['version']
assert re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version)
for branch in ['master', 'release']:
    ref = json.loads(subprocess.check_output(['gh', 'api', f'repos/{repo}/git/ref/heads/{branch}']))
    assert ref['object']['sha'] == documentation_sha, 'Documentation branches differ'
tag = json.loads(subprocess.check_output(['gh', 'api', f'repos/{repo}/git/ref/tags/{version}']))['object']
if tag['type'] == 'tag':
    tag = json.loads(subprocess.check_output(['gh', 'api', f'repos/{repo}/git/tags/{tag["sha"]}']))['object']
assert tag['type'] == 'commit'
image_sha = tag['sha']
for variable, expected in [('DOCUMENTATION_RUN_ID', documentation_sha), ('BUILD_RUN_ID', image_sha)]:
    run_id = os.environ[variable]
    assert re.fullmatch(r'[0-9]+', run_id)
    run = json.loads(subprocess.check_output(['gh', 'api', f'repos/{repo}/actions/runs/{run_id}']))
    assert run['head_sha'] == expected and run['head_branch'] == 'release', 'Build source differs'
    assert run['path'] == '.github/workflows/ci.yml' and run['event'] in ['push', 'workflow_dispatch']
    assert run['status'] == 'completed' and run['conclusion'] == 'success', 'Successful build required'
for arch in ['AMD64', 'ARM64']:
    assert re.fullmatch(r'sha256:[a-f0-9]{64}', os.environ[arch + '_CONFIG_DIGEST'])
assert os.environ['HUB_NAMESPACE'] == 'nasaruntime'
# 镜像来源固定到既有版本标签，后续步骤只更新说明及指向同一内容的 latest。
with open(os.environ['GITHUB_ENV'], 'a') as output:
    output.write(f'IMAGE=nasaruntime/saga-server\nVERSION={version}\nIMAGE_SOURCE_REVISION={image_sha}\n')
