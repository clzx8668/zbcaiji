"""
HTTP Basic Auth 保护 Flask-Admin 管理界面。
凭据从环境变量 WEB_ADMIN_USER / WEB_ADMIN_PASS 读取。
"""
import os
from flask import request, Response
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps

# 默认凭据，可通过 .env 覆盖
ADMIN_USER = os.getenv("WEB_ADMIN_USER", "admin")
ADMIN_PASS = os.getenv("WEB_ADMIN_PASS", "admin123")

# 预计算 hash（首次导入时）
_users = {ADMIN_USER: generate_password_hash(ADMIN_PASS)}


def check_auth(username, password):
    """验证用户名密码"""
    return (
        username in _users
        and check_password_hash(_users[username], password)
    )


def authenticate():
    """返回 401 响应，要求认证"""
    return Response(
        "需要登录以访问管理后台。",
        401,
        {"WWW-Authenticate": 'Basic realm="Bid Scraper Admin"'},
    )


def requires_auth(f):
    """装饰器：保护单个视图函数"""
    @wraps(f)
    def decorated(*args, **kwargs):
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Basic "):
            return authenticate()
        import base64
        try:
            credentials = base64.b64decode(auth_header[6:]).decode("utf-8")
            username, password = credentials.split(":", 1)
        except Exception:
            return authenticate()
        if not check_auth(username, password):
            return authenticate()
        return f(*args, **kwargs)
    return decorated


def protect_admin(app):
    """注册 before_request 钩子，保护 /admin/* 路径"""
    @app.before_request
    def _check_admin_auth():
        if request.path.startswith("/admin") and request.endpoint != "static":
            auth_header = request.headers.get("Authorization")
            if not auth_header or not auth_header.startswith("Basic "):
                return authenticate()
            import base64
            try:
                credentials = base64.b64decode(auth_header[6:]).decode("utf-8")
                username, password = credentials.split(":", 1)
            except Exception:
                return authenticate()
            if not check_auth(username, password):
                return authenticate()
