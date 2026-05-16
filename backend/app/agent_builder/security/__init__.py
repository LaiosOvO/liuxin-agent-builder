"""安全模块包。

包含：
- startup_checks: 应用启动时的安全校验（密钥长度、必需环境变量）
- rate_limit: slowapi 速率限制配置与 limiter 单例

遵守 CLAUDE.md 2.3 Fork discipline：所有代码作为新增模块，不改 flock 原文件。
"""
