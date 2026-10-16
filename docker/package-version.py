import os, re, tomllib
with open('Cargo.toml', 'rb') as source:
    version = tomllib.load(source)['package']['version']
# 镜像归档只能由对应软件版本的发布分支构建，防止分支与标签内容错配。
assert re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', version), 'Stable version required'
assert os.environ.get('GITHUB_REF') == f'refs/heads/release/{version}', 'Release branch must match package version'
with open(os.environ['GITHUB_OUTPUT'], 'a') as output:
    output.write(f'version={version}\n')
