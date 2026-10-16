import hashlib, json, os, subprocess, tarfile
for arch in ['amd64', 'arm64']:
    archive = f'image-archives/saga-server-{arch}.tar'
    tag = f'saga-server:build-{os.environ["GITHUB_SHA"]}-{arch}'
    # 配置摘要绑定运行参数与全部文件系统层，不依赖 Docker 存储后端的 ID 表示。
    with tarfile.open(archive) as source:
        entries = json.load(source.extractfile('manifest.json'))
        assert len(entries) == 1 and entries[0]['RepoTags'] == [tag], 'Unexpected archive tags'
        raw = source.extractfile(entries[0]['Config']).read()
        assert 'sha256:' + hashlib.sha256(raw).hexdigest() == os.environ[f'{arch.upper()}_CONFIG_DIGEST'], 'Archive differs from validated artifact'
        config = json.loads(raw)
    # 先比对授权的配置摘要，再装载镜像；未匹配的归档不能成为后续上传来源。
    subprocess.run(['docker', 'load', '--input', archive], check=True)
    image = json.loads(subprocess.check_output(['docker', 'image', 'inspect', tag]))[0]
    assert image['RootFS']['Type'] == config['rootfs']['type'] and image['RootFS']['Layers'] == config['rootfs']['diff_ids'], 'Loaded image layers differ'
    for field in ['User', 'Env', 'Entrypoint', 'Cmd', 'WorkingDir', 'Labels', 'StopSignal', 'ExposedPorts']:
        assert image['Config'].get(field) == config['config'].get(field), f'Loaded image {field} differs'
    assert image['Architecture'] == arch and image['Os'] == 'linux', 'Unexpected image platform'
    assert config['architecture'] == arch and config['os'] == 'linux', 'Unexpected archive platform'
    assert image['Config']['User'] == '10001:10001', 'Unexpected runtime identity'
    assert image['Config']['Entrypoint'] == ['/app/saga-server'], 'Unexpected entrypoint'
    labels = image['Config']['Labels']
    assert labels['org.opencontainers.image.revision'] == os.environ['GITHUB_SHA'], 'Unexpected source'
    assert labels['org.opencontainers.image.version'] == os.environ['VERSION'], 'Unexpected version'
