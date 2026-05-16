"""应用启动安全校验模块。

在 FastAPI app 构造之前调用 run_startup_checks()，对以下内容进行严格校验：
1. HMAC_SECRET / JWT_SECRET 长度 ≥ 32 字节（防止弱密钥被用于 Token 伪造）
2. 必需环境变量存在（POSTGRES_DSN / REDIS_URL / PUBLIC_BASE_URL / WEB_ORIGIN）

校验失败时：打印中文错误说明 + sys.exit(1)（拒绝启动）。

Pitfall 4 防护：HMAC_SECRET 太短 → 任意 token 可被伪造 → 所有审批节点被绕过。
NET-04 需求实现。
"""

import logging
import os
import sys

# 确保 basicConfig 已配置，避免错误被吞
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s — %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%SZ",
)

log = logging.getLogger(__name__)

# 需要校验长度的密钥名（任一不足 32 字节则拒绝启动）
REQUIRED_SECRETS: list[str] = ["HMAC_SECRET", "JWT_SECRET"]

# 必须存在的环境变量（空字符串视为未配置）
REQUIRED_ENV: list[str] = [
    "POSTGRES_DSN",
    "REDIS_URL",
    "PUBLIC_BASE_URL",
    "WEB_ORIGIN",
]

# 最小密钥长度（字节）
MIN_SECRET_BYTES: int = 32


def run_startup_checks() -> None:
    """执行所有启动安全校验。

    失败时：记录所有错误并 sys.exit(1)。
    成功时：记录 INFO 日志，正常返回。
    """
    errors: list[str] = []

    # 1. 校验密钥长度
    for name in REQUIRED_SECRETS:
        val: str = os.environ.get(name, "")
        byte_len: int = len(val.encode("utf-8"))
        if byte_len < MIN_SECRET_BYTES:
            errors.append(
                f"{name} 长度不足"
                f"（实际 {byte_len} 字节，要求 ≥ {MIN_SECRET_BYTES} 字节）"
            )

    # 2. 校验必需环境变量存在
    for name in REQUIRED_ENV:
        if not os.environ.get(name):
            errors.append(f"必需环境变量 {name} 未配置")

    # 3. 任有错误 → 记录 + 退出
    if errors:
        log.error(
            "启动安全校验失败，服务拒绝启动：\n  - %s",
            "\n  - ".join(errors),
        )
        sys.exit(1)

    log.info(
        "启动安全校验通过：%d 个密钥 / %d 个环境变量均符合要求",
        len(REQUIRED_SECRETS),
        len(REQUIRED_ENV),
    )
