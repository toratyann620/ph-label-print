"""
スマホQRスキャン画面（/scan）向けの簡易PIN認証。

セッションDBは使わず、app_settingsのscan_secretで署名したCookieのみで認証状態を保持する
（有効期限180日）。PIN自体はapp_settings.scan_pinで管理し、設定画面から変更可能。
"""
import hashlib
import hmac

from fastapi import Request
from fastapi.responses import Response

import db

COOKIE_NAME = "scan_auth"
MAX_AGE_SECONDS = 60 * 60 * 24 * 180  # 180日


def _expected_token() -> str:
    secret = db.get_app_settings()["scan_secret"]
    return hmac.new(secret.encode(), b"scan-authorized", hashlib.sha256).hexdigest()


def is_authorized(request: Request) -> bool:
    secret = db.get_app_settings()["scan_secret"]
    if not secret:
        return False
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return False
    return hmac.compare_digest(token, _expected_token())


def set_auth_cookie(response: Response) -> None:
    response.set_cookie(
        COOKIE_NAME,
        _expected_token(),
        max_age=MAX_AGE_SECONDS,
        httponly=True,
        samesite="lax",
    )
