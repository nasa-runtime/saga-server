import os, re, tomllib
with open('Cargo.toml', 'rb') as source:
    version = tomllib.load(source)['package']['version']
# 镜像归档只能由受控发布分支构建，软件版本从 manifest 读取并写入镜像标签。
assert re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version), 'Stable version required'
assert os.environ.get('GITHUB_REF') == 'refs/heads/release', 'Release branch required'
with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
    output.write(f'version={version}\n')
