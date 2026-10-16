"""使用 Python 标准库发起、查询 Saga 或读取流程定义；凭据仅从环境读取。"""

import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


class DirectRequest(urllib.request.HTTPRedirectHandler):
    """已签名请求不能自动改发到其它路径或主机。"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        """业务作用: 拒绝重定向，避免泄露签名凭据或改变业务请求目标。

        参数说明: req 为原请求，其余参数为服务端重定向响应和目标。
        返回: 不创建重定向请求，由调用方接收原始 HTTP 失败状态。
        """
        return None


def arguments():
    """业务作用: 明确一次请求的业务身份，避免示例自动生成重复事务。

    参数说明: 无。
    返回: 已校验必填项的命令行参数；缺少参数时退出并打印使用说明。
    """
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="operation", required=True)
    for name in ("start", "get", "definition"):
        command = commands.add_parser(name)
        command.add_argument("--tenant", required=True)
        if name in ("start", "get"):
            command.add_argument("--saga-id", required=True)
        if name in ("start", "definition"):
            command.add_argument("--workflow", required=True)
            command.add_argument("--definition-version", type=int, required=True)
        if name == "start":
            command.add_argument("--business-key", required=True)
            command.add_argument("--trigger-id", required=True)
            command.add_argument("--input-file", type=Path, required=True)
    return parser.parse_args()


def signed_request(args):
    """业务作用: 用稳定的业务内容和本次尝试的新 nonce 构造 Saga HTTP 请求。

    参数说明: args 提供租户、流程版本、实例身份与输入文件等业务字段。
    返回: 签名覆盖实际 path 和原始 body 的 Request；无效地址、密钥或输入被拒绝。
    """
    base = os.environ["SAGA_BASE_URL"].rstrip("/")
    parts = urllib.parse.urlsplit(base)
    if (parts.scheme not in ("http", "https") or not parts.hostname or parts.query
            or parts.fragment or parts.username or parts.password):
        raise ValueError("SAGA_BASE_URL 必须为不含认证、query 或 fragment 的 HTTP(S) 基础地址")
    key = os.environ["SAGA_HTTP_KEY"]
    if not re.fullmatch(r"[0-9a-f]{64}", key):
        raise ValueError("SAGA_HTTP_KEY 必须是 64 个小写十六进制字符")
    producer = os.environ["SAGA_HTTP_PRODUCER"]
    if not producer or any(ord(c) < 33 or ord(c) > 126 for c in producer):
        raise ValueError("SAGA_HTTP_PRODUCER 必须是有效的 HTTP 身份头")
    if args.operation in ("start", "definition") and args.definition_version <= 0:
        raise ValueError("definition-version 必须为正整数")
    tenant = urllib.parse.quote(args.tenant, safe="")
    body = b""
    if args.operation == "start":
        payload = json.loads(args.input_file.read_text(encoding="utf-8"))
        body = json.dumps({
            "tenant_id": args.tenant, "saga_id": args.saga_id,
            "workflow": args.workflow, "definition_version": args.definition_version,
            "business_key": args.business_key, "trigger_id": args.trigger_id,
            "input": payload,
        }, ensure_ascii=False, allow_nan=False, separators=(",", ":")).encode("utf-8")
        path = "/instances"
    elif args.operation == "get":
        path = "/instances/" + tenant + "/" + urllib.parse.quote(args.saga_id, safe="")
    else:
        path = ("/registry/definitions/" + tenant + "/"
                + urllib.parse.quote(args.workflow, safe="") + "/" + str(args.definition_version))
    url = base + path
    timestamp = str(time.time_ns() // 1_000_000)
    nonce = secrets.token_hex(16)
    material = ("nasaga-http-v2\n" + producer + "\n" + urllib.parse.urlsplit(url).path
                + "\n" + timestamp + "\n" + nonce + "\n").encode("utf-8") + body
    signature = hmac.new(bytes.fromhex(key), material, hashlib.sha256).hexdigest()
    return urllib.request.Request(url, data=body if args.operation == "start" else None,
                                  headers={"Content-Type": "application/json",
                                           "x-saga-producer": producer, "x-saga-timestamp": timestamp,
                                           "x-saga-nonce": nonce, "x-saga-signature": signature})


def main():
    """业务作用: 执行一次签名调用并保留 HTTP 状态，供业务方判断是否查询或重试。

    参数说明: 无。
    返回: HTTP 成功退出 0；HTTP 拒绝退出 1；配置、网络或超时失败退出 2。
    """
    try:
        request = signed_request(arguments())
        # 重试必须由业务方保留原事务身份和内容，再生成新的签名，不能原样重放。
        with urllib.request.build_opener(DirectRequest()).open(request, timeout=10) as response:
            print("HTTP", response.status)
            print(response.read().decode("utf-8", errors="replace"))
        return 0
    except urllib.error.HTTPError as error:
        print("HTTP", error.code, file=sys.stderr)
        print(error.read().decode("utf-8", errors="replace"), file=sys.stderr)
        return 1
    except (KeyError, ValueError, OSError, urllib.error.URLError) as error:
        print("请求未获得可确认结果:", error, file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
