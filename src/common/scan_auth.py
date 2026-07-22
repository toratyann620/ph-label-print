"""
スマホQRスキャン画面（/scan）・管理画面（/admin）向けの簡易PIN認証。

セッションDBは使わず、app_settingsの{realm}_secretで署名したCookieのみで認証状態を保持する
（有効期限180日）。PIN自体はapp_settings.{realm}_pinで管理し、設定画面から変更可能。
realmは "scan"（スマホ画面用）と "admin"（管理画面用）の2種類があり、それぞれ別のPIN・別のCookieで
独立して認証する（スキャン用PINだけを渡された人が管理画面に入れてしまうことを防ぐため）。
"""
import hashlib
import hmac

from fastapi import Request
from fastapi.responses import Response

import db

MAX_AGE_SECONDS = 60 * 60 * 24 * 180  # 180日


def _expected_token(realm: str) -> str | None:
    secret = db.get_app_settings().get(f"{realm}_secret", "")
    if not secret:
        return None
    return hmac.new(secret.encode(), f"{realm}-authorized".encode(), hashlib.sha256).hexdigest()


def is_authorized(request: Request, realm: str = "scan") -> bool:
    expected = _expected_token(realm)
    if not expected:
        return False
    token = request.cookies.get(f"{realm}_auth")
    if not token:
        return False
    return hmac.compare_digest(token, expected)


def set_auth_cookie(response: Response, realm: str = "scan") -> None:
    expected = _expected_token(realm)
    if not expected:
        return
    response.set_cookie(
        f"{realm}_auth",
        expected,
        max_age=MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
    )
