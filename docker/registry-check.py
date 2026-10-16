import json, os, urllib.error, urllib.parse, urllib.request
image = os.environ['IMAGE']
query = urllib.parse.urlencode({'service': 'registry.docker.io', 'scope': f'repository:{image}:pull'})
with urllib.request.urlopen(f'https://auth.docker.io/token?{query}', timeout=30) as response:
    token = json.load(response)['token']
def manifest(reference):
    """业务作用：读取远端镜像身份，区分不存在与无法确认。
    参数说明：reference 是待核对的标签或内容摘要。
    返回：存在时返回清单，仅 HTTP 404 返回 None，其余失败停止发布。
    """
    request = urllib.request.Request(
        f'https://registry-1.docker.io/v2/{image}/manifests/{reference}',
        headers={'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json'})
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        if error.code == 404:
            return None
        raise SystemExit(f'Registry preflight failed: HTTP {error.code}')
expected = {arch: os.environ[f'{arch.upper()}_CONFIG_DIGEST'] for arch in ['amd64', 'arm64']}
source_revision = os.environ.get('IMAGE_SOURCE_REVISION', os.environ['GITHUB_SHA'])
version = manifest(os.environ['VERSION'])
if os.environ.get('REQUIRE_VERSION_PRESENT') == 'true':
    assert version is not None, 'Published version is missing'
if version is not None:
    # 已存在的内容只能用于继续完成同一发布，不能替换已公开版本。
    entries = version.get('manifests', [])
    assert sorted((entry['platform']['os'], entry['platform']['architecture']) for entry in entries) == [('linux', 'amd64'), ('linux', 'arm64')], 'Existing version platforms differ'
    for entry in entries:
        arch = entry['platform']['architecture']
        assert manifest(entry['digest'])['config']['digest'] == expected[arch], 'Existing version content differs; choose a new version'
for arch in expected:
    existing = manifest(f'sha-{source_revision}-{arch}')
    assert existing is None or existing['config']['digest'] == expected[arch], 'Existing architecture image differs'
if os.environ.get('VERIFY_LATEST') == 'true':
    # latest 只能引用已确认的版本平台清单，不能把其它构建混入默认入口。
    latest = manifest('latest')
    assert latest is not None and version is not None, 'Version and latest must exist'
    assert latest.get('manifests') == version.get('manifests'), 'Latest content differs from version'
with open(os.environ['GITHUB_ENV'], 'a') as output:
    output.write(f'PUBLISH_VERSION={"true" if version is None else "false"}\n')
