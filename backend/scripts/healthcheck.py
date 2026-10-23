"""容器健康检查。

未登录时 `/api/v1/auth/me` 返回 401，对健康检查来说说明服务已经就绪；
只有连接失败或返回 5xx 才算不健康。

单独放成脚本而不是写在 Dockerfile 的 `CMD` 里，是因为 `python -c` 无法
在一行里写 `try/except`，多行续行又容易被 shell 解析出问题。
"""

from __future__ import annotations

import os
import sys
import urllib.error
import urllib.request

URL = os.environ.get(
    "HEALTHCHECK_URL", "http://127.0.0.1:8000/api/v1/auth/me"
)
READY_STATUSES = {200, 401, 403}


def main() -> int:
    try:
        with urllib.request.urlopen(URL, timeout=4) as response:
            return 0 if response.status in READY_STATUSES else 1
    except urllib.error.HTTPError as exc:
        return 0 if exc.code in READY_STATUSES else 1
    except Exception as exc:  # pragma: no cover - 连接失败路径
        print(f"healthcheck failed: {type(exc).__name__}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())