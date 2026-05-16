"""服务层（Service Layer）。

各子模块：
- password.py    : 密码哈希与强度校验（pwdlib[argon2]）
- jwt_service.py : 3 类 JWT 签发/校验/消费（PyJWT 2.12.1 HS256）
- email_service.py: 异步邮件发送（aiosmtplib + Jinja2）
- setup_service.py: 首启 Setup 流程（super_admin + workspace 创建）
- registration_service.py: 用户注册与邮箱验证消费
- invite_service.py: 邀请签发、预览、落地注册
- rbac.py        : RBAC 权限矩阵 + FastAPI Depends 工厂
- audit.py       : 审计日志写入工具
"""
