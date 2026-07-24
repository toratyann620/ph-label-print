"""
Ship&coの実績CSVと、新システムで実際に発行した送り状データを照合する。

処理内容:
  1. CSV（ship-co/xxxx.csv）を読み込み、注文単位（OrderName）に集約する
     - Ship&coのCSVは商品明細ごとに1行なので、配送情報がある最初の行だけを採用する
     - ShippingCarrier=="sagawa" の注文は対象外（現状ヤマトのみサポート）
  2. 各注文について、新システムで実際にヤマトへ送り状発行を行う（印刷は行わない）
  3. 発行に使ったお届け先情報・送り状種類とCSVの値を項目ごとに比較する
  4. 結果を shipments テーブルの該当レコードに記録し、全体の一致率をコンソールに出力する

実行例:
  PYTHONPATH=src/shopify:src/common .venv/bin/python src/yamato/../../scripts/compare_shipco.py ship-co/0722.csv
"""
import asyncio
import csv
import json
import os
import re
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _sub in ("common", "shopify", "yamato"):
    sys.path.insert(0, os.path.join(_PROJECT_ROOT, "src", _sub))

import db  # noqa: E402
from shopify_client import ShopifyClient  # noqa: E402
from issue_slip_from_scan import find_order, issue_for_order_name  # noqa: E402

SERVICE_TYPE_BY_METHOD = {
    "yamato_regular": "0",
    "yamato_collect": "2",
    "yamato_nekopos": "A",
}
SERVICE_TYPE_LABEL = {"0": "発払い", "2": "コレクト(代金引換)", "A": "ネコポス"}

FIELDS = ["name", "phone", "zip", "address", "address2", "service_type"]


def _norm_text(s: str) -> str:
    s = (s or "").strip()
    s = s.replace("　", " ")
    s = re.sub(r"\s+", " ", s)
    return s


def _norm_digits(s: str) -> str:
    digits = re.sub(r"\D", "", s or "")
    if digits.startswith("81") and len(digits) > 10:
        digits = "0" + digits[2:]
    return digits


def load_csv_orders(csv_path: str) -> dict:
    """OrderName -> 配送情報を持つCSV行 の辞書を作る（佐川は除外）"""
    with open(csv_path, newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    orders = {}
    for row in rows:
        if row["OrderName"] in orders:
            continue
        if not row["ShippingCarrier"].strip():
            continue
        if row["ShippingCarrier"].strip() == "sagawa":
            continue
        orders[row["OrderName"]] = row
    return orders


def build_csv_expected(row: dict) -> dict:
    address = _norm_text(row["RecipientProvince"] + row["RecipientCity"] + row["RecipientAddress1"])
    return {
        "name": _norm_text(row["RecipientFullName"]),
        "phone": _norm_digits(row["RecipientPhone"]),
        "zip": _norm_digits(row["RecipientZIP"]),
        "address": address,
        "address2": _norm_text(row["RecipientAddress2"]),
        "service_type": SERVICE_TYPE_BY_METHOD.get(row["ShippingMethod"], "?"),
    }


async def build_actual(order_name: str) -> dict | None:
    """新システムが実際に組み立てたお届け先情報を、Shopify注文から再計算する"""
    store_name, shopify, order, _errors = await find_order(order_name)
    if not order:
        return None
    yamato_req = shopify.map_order_to_yamato_request(order)
    return {
        "name": _norm_text(yamato_req.recipient_name),
        "phone": _norm_digits(yamato_req.recipient_phone),
        "zip": _norm_digits(yamato_req.recipient_zip),
        "address": _norm_text(yamato_req.recipient_address),
        "address2": _norm_text(yamato_req.recipient_address2),
        "service_type": yamato_req.service_type,
    }


async def main():
    csv_path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(_PROJECT_ROOT, "ship-co", "0722.csv")
    db.init_db()

    csv_orders = load_csv_orders(csv_path)
    print("=" * 70)
    print(f"Ship&co照合: {csv_path}")
    print(f"対象注文数（佐川除く）: {len(csv_orders)}")
    print("=" * 70)

    total_fields = 0
    total_matched = 0
    order_results = []

    for i, (order_name, row) in enumerate(sorted(csv_orders.items()), start=1):
        print(f"\n[{i}/{len(csv_orders)}] {order_name} 処理中...")
        expected = build_csv_expected(row)

        record = await issue_for_order_name(order_name, skip_print=True)

        if record["status"] != "done":
            print(f"  ✗ 発行失敗: {record['status']} / {record.get('error_message')}")
            db.update_shipment_record(
                record["id"],
                compare_status="issue_failed",
                compare_match_rate=0.0,
                compare_detail=json.dumps({"expected": expected, "error": record.get("error_message")}, ensure_ascii=False),
            )
            order_results.append({"order_name": order_name, "status": "issue_failed", "match_rate": 0.0})
            continue

        actual = await build_actual(order_name)
        if actual is None:
            print("  ✗ 照合用データの再取得に失敗しました（Shopify注文が見つかりません）")
            continue

        diffs = {}
        matched = 0
        for field in FIELDS:
            is_match = expected[field] == actual[field]
            diffs[field] = {"csv": expected[field], "system": actual[field], "match": is_match}
            if is_match:
                matched += 1

        match_rate = matched / len(FIELDS)
        total_fields += len(FIELDS)
        total_matched += matched

        status_label = "一致" if match_rate == 1.0 else "不一致あり"
        print(f"  {'✓' if match_rate == 1.0 else '△'} {status_label}（一致率 {match_rate * 100:.0f}%） 伝票番号: {record['yamato_tracking_no']}")
        if match_rate < 1.0:
            for field, d in diffs.items():
                if not d["match"]:
                    print(f"      [{field}] CSV: {d['csv']!r} / 新システム: {d['system']!r}")

        db.update_shipment_record(
            record["id"],
            compare_status="match" if match_rate == 1.0 else "mismatch",
            compare_match_rate=match_rate,
            compare_detail=json.dumps({"expected": expected, "actual": actual, "diffs": diffs}, ensure_ascii=False),
        )
        order_results.append({"order_name": order_name, "status": "done", "match_rate": match_rate})

    print("\n" + "=" * 70)
    print("【照合結果まとめ】")
    print(f"  対象注文数: {len(order_results)}")
    issue_failed = sum(1 for r in order_results if r["status"] == "issue_failed")
    fully_matched = sum(1 for r in order_results if r["status"] == "done" and r["match_rate"] == 1.0)
    partial = sum(1 for r in order_results if r["status"] == "done" and r["match_rate"] < 1.0)
    print(f"  発行失敗: {issue_failed}件")
    print(f"  完全一致: {fully_matched}件")
    print(f"  一部不一致: {partial}件")
    if total_fields:
        print(f"  全体の項目一致率: {total_matched}/{total_fields} = {total_matched / total_fields * 100:.1f}%")
    print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
