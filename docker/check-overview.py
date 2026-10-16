import ast
from pathlib import Path

# Docker Hub 按 UTF-8 预算接收公开说明；超限时在镜像上传前拒绝，避免文本被截断。
overview = Path('docker/README.md').read_bytes()
assert 0 < len(overview) <= 25000, 'Repository overview must fit 25000 UTF-8 bytes'
module = ast.parse(Path('docker/publish-overview.py').read_text())
summary = next(ast.literal_eval(node.value) for node in module.body
               if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == 'description' for target in node.targets))
assert isinstance(summary, str) and 0 < len(summary.encode('utf-8')) <= 100, 'Repository summary must fit 100 UTF-8 bytes'
print('Repository overview and summary fit their UTF-8 budgets')
