"""
管理画面用の永続化レイヤー（SQLite）

- shipments:     スキャン/手動選択→Shopify注文取得→ヤマト送り状発行 の各処理レコード
                 （発行履歴・エラー一覧はこのテーブルをステータスで絞り込んで表示する）
- orders_cache:  Shopify直近注文のキャッシュ（処理状況一覧の元データ。発送方法で仕分けし、
                 ヤマト分は未発行/発行済みを管理する）
- store_settings: 店舗ごとの送り元情報
- app_settings:  アプリ全体の設定（発行モード・スキャン/出力フォルダ・付与タグ）
"""
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from dotenv import load_dotenv

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
load_dotenv(os.path.join(PROJECT_ROOT, os.getenv("APP_ENV_FILE", ".env")), override=True)

# APP_ENV_FILE=.env.test を指定して起動すると、テスト環境として別DBファイルを使う
# （本番の処理状況・発行履歴とは完全に分離される）
DB_PATH = os.path.join(PROJECT_ROOT, "data", os.getenv("APP_DB_NAME", "app.db"))

STATUS_LABELS = {
    "processing":            "処理中",
    "done":                  "発行完了",
    "error_qr":              "QR読み取り失敗",
    "error_order_not_found": "Shopify注文が見つかりません",
    "error_shopify":         "Shopify APIエラー",
    "error_yamato":          "ヤマトAPIエラー",
}

ERROR_STATUSES = ("error_qr", "error_order_not_found", "error_shopify", "error_yamato")
IN_PROGRESS_STATUSES = ("processing",)

# 発送方法の判定に使うタグのキーワード（Shopify注文タグに含まれるかで判定）
SHIPPING_METHOD_KEYWORDS = {
    "ヤマト": "ヤマト",
    "佐川":   "佐川",
}
SHIPPING_METHOD_OTHER = "その他"

APP_SETTINGS_DEFAULTS = {
    "issue_mode":     "manual",   # manual | auto
    "scan_folder":    "input",
    "output_folder":  "output",
    "archive_folder": "output/archive",
    "issue_tag":      "ヤマト送り状発行済み",
    "scan_pin":       "",   # スマホQRスキャン画面のPIN（設定画面で変更可能）
    "scan_secret":    "",   # PIN認証Cookie署名用の秘密鍵（自動生成）
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@contextmanager
def get_conn():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _ensure_columns(conn, table: str, columns: dict[str, str]) -> None:
    """既存テーブルに不足しているカラムがあれば ALTER TABLE で追加する（簡易マイグレーション）"""
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    for name, col_type in columns.items():
        if name not in existing:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {col_type}")


def init_db():
    with get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS shipments (
                id                   INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at           TEXT NOT NULL,
                updated_at           TEXT NOT NULL,
                source_pdf           TEXT,
                order_name           TEXT,
                store                TEXT,
                shopify_order_number TEXT,
                recipient_name       TEXT,
                recipient_address    TEXT,
                recipient_phone      TEXT,
                status               TEXT NOT NULL,
                error_message        TEXT,
                yamato_issue_no      TEXT,
                yamato_tracking_no   TEXT,
                pdf_path             TEXT,
                detail_json          TEXT
            )
        """)
        _ensure_columns(conn, "shipments", {"tag_status": "TEXT", "print_status": "TEXT"})

        conn.execute("""
            CREATE TABLE IF NOT EXISTS store_settings (
                store          TEXT PRIMARY KEY,
                sender_name    TEXT,
                sender_zip     TEXT,
                sender_address TEXT,
                sender_phone   TEXT,
                watch_folder   TEXT,
                printer_name   TEXT,
                updated_at     TEXT
            )
        """)
        _ensure_columns(conn, "store_settings", {"sender_email": "TEXT", "sender_address2": "TEXT"})

        conn.execute("""
            CREATE TABLE IF NOT EXISTS orders_cache (
                order_id           INTEGER PRIMARY KEY,
                store               TEXT,
                order_number         TEXT,
                order_name           TEXT,
                recipient_name       TEXT,
                recipient_address    TEXT,
                recipient_phone      TEXT,
                tags                 TEXT,
                shipping_method      TEXT,
                order_created_at     TEXT,
                synced_at            TEXT,
                yamato_status        TEXT,
                shipment_id          INTEGER
            )
        """)

        conn.execute("""
            CREATE TABLE IF NOT EXISTS app_settings (
                key   TEXT PRIMARY KEY,
                value TEXT
            )
        """)


def create_shipment_record(**fields) -> int:
    now = _now()
    fields.setdefault("status", "processing")
    columns = ["created_at", "updated_at"] + list(fields.keys())
    values = [now, now] + list(fields.values())
    placeholders = ",".join("?" for _ in values)
    with get_conn() as conn:
        cur = conn.execute(
            f"INSERT INTO shipments ({','.join(columns)}) VALUES ({placeholders})",
            values,
        )
        return cur.lastrowid


def update_shipment_record(record_id: int, **fields) -> None:
    fields["updated_at"] = _now()
    set_clause = ",".join(f"{k}=?" for k in fields)
    with get_conn() as conn:
        conn.execute(
            f"UPDATE shipments SET {set_clause} WHERE id=?",
            list(fields.values()) + [record_id],
        )


def get_shipment(record_id: int) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM shipments WHERE id=?", [record_id]).fetchone()
        return dict(row) if row else None


def find_shipment_by_order_name(order_name: str):
    """指定した注文番号で最新の発行完了レコードを探す（orders_cacheとの突合に使用）"""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM shipments WHERE order_name=? AND status='done' ORDER BY id DESC LIMIT 1",
            [order_name],
        ).fetchone()
        return dict(row) if row else None


def list_shipments(statuses=None, limit: int = 200) -> list[dict]:
    with get_conn() as conn:
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            rows = conn.execute(
                f"SELECT * FROM shipments WHERE status IN ({placeholders}) ORDER BY id DESC LIMIT ?",
                list(statuses) + [limit],
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM shipments ORDER BY id DESC LIMIT ?", [limit]
            ).fetchall()
        return [dict(r) for r in rows]


def count_shipments(statuses=None) -> int:
    with get_conn() as conn:
        if statuses:
            placeholders = ",".join("?" for _ in statuses)
            row = conn.execute(
                f"SELECT COUNT(*) AS c FROM shipments WHERE status IN ({placeholders})",
                list(statuses),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) AS c FROM shipments").fetchone()
        return row["c"]


def list_store_settings() -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM store_settings ORDER BY store").fetchall()
        return [dict(r) for r in rows]


def get_store_settings(store: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM store_settings WHERE store=?", [store]).fetchone()
        return dict(row) if row else None


def upsert_store_settings(store: str, **fields) -> None:
    fields["updated_at"] = _now()
    with get_conn() as conn:
        existing = conn.execute("SELECT store FROM store_settings WHERE store=?", [store]).fetchone()
        if existing:
            set_clause = ",".join(f"{k}=?" for k in fields)
            conn.execute(
                f"UPDATE store_settings SET {set_clause} WHERE store=?",
                list(fields.values()) + [store],
            )
        else:
            columns = ["store"] + list(fields.keys())
            values = [store] + list(fields.values())
            placeholders = ",".join("?" for _ in values)
            conn.execute(
                f"INSERT INTO store_settings ({','.join(columns)}) VALUES ({placeholders})",
                values,
            )


# ── app_settings（グローバル設定） ──────────────────────────────

def get_app_settings() -> dict:
    with get_conn() as conn:
        rows = conn.execute("SELECT key, value FROM app_settings").fetchall()
    values = dict(APP_SETTINGS_DEFAULTS)
    values.update({r["key"]: r["value"] for r in rows})
    return values


def set_app_settings(**fields) -> None:
    with get_conn() as conn:
        for key, value in fields.items():
            conn.execute(
                "INSERT INTO app_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                [key, value],
            )


# ── orders_cache（Shopify直近注文のキャッシュ） ──────────────────

def classify_shipping_method(tags: str) -> str:
    tags = tags or ""
    for keyword, label in SHIPPING_METHOD_KEYWORDS.items():
        if keyword in tags:
            return label
    return SHIPPING_METHOD_OTHER


def upsert_order_cache(**fields) -> None:
    order_id = fields.pop("order_id")
    fields["synced_at"] = _now()
    with get_conn() as conn:
        existing = conn.execute("SELECT order_id FROM orders_cache WHERE order_id=?", [order_id]).fetchone()
        if existing:
            set_clause = ",".join(f"{k}=?" for k in fields)
            conn.execute(
                f"UPDATE orders_cache SET {set_clause} WHERE order_id=?",
                list(fields.values()) + [order_id],
            )
        else:
            columns = ["order_id"] + list(fields.keys())
            values = [order_id] + list(fields.values())
            placeholders = ",".join("?" for _ in values)
            conn.execute(
                f"INSERT INTO orders_cache ({','.join(columns)}) VALUES ({placeholders})",
                values,
            )


def mark_order_issued(order_name: str, shipment_id: int) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE orders_cache SET yamato_status='issued', shipment_id=? WHERE order_name=?",
            [shipment_id, order_name],
        )


def list_orders_cache(limit: int = 500) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM orders_cache ORDER BY order_created_at DESC LIMIT ?", [limit]
        ).fetchall()
        return [dict(r) for r in rows]


def get_orders_cache_by_ids(order_ids: list[int]) -> list[dict]:
    if not order_ids:
        return []
    with get_conn() as conn:
        placeholders = ",".join("?" for _ in order_ids)
        rows = conn.execute(
            f"SELECT * FROM orders_cache WHERE order_id IN ({placeholders})", order_ids
        ).fetchall()
        return [dict(r) for r in rows]
