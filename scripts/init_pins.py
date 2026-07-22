"""
初回セットアップ用: 管理画面PIN（/admin）・スマホスキャンPIN（/scan）を発行する。

/admin 自体がPINでガードされているため、初回だけはこのスクリプトで直接DBに
PINを発行する必要がある（発行後はブラウザの設定画面から変更できる）。
既にPINが設定済みの項目は上書きしない。

実行例（プロジェクトルートで実行）:
  .venv\\Scripts\\python.exe scripts\\init_pins.py     (Windows)
  .venv/bin/python scripts/init_pins.py                 (macOS/Linux)

テスト環境（.env.test）に対して発行する場合:
  set APP_ENV_FILE=.env.test  (Windows) / export APP_ENV_FILE=.env.test (macOS/Linux)
"""
import os
import secrets
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src", "common"))

import db  # noqa: E402

db.init_db()
settings = db.get_app_settings()

updates = {}
for pin_key, secret_key, label in [
    ("admin_pin", "admin_secret", "管理画面 (/admin)"),
    ("scan_pin", "scan_secret", "スマホスキャン画面 (/scan)"),
]:
    if settings.get(pin_key):
        print(f"{label} のPINは既に設定済みのためスキップします。")
        continue
    pin = str(secrets.randbelow(9000) + 1000)
    updates[pin_key] = pin
    updates[secret_key] = secrets.token_hex(16)
    print(f"{label} のPIN: {pin}")

if updates:
    db.set_app_settings(**updates)
    print("\n発行したPINは大切に保管し、必要な方にのみ共有してください。")
    print("設定画面（/admin/settings）からいつでも変更できます。")
else:
    print("\n変更はありませんでした。")
