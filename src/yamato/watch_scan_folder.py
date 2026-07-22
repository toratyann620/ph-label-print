"""
inputフォルダ（設定のscan_folder）を継続的に監視し、PDFが追加された瞬間に
QR読取→Shopify注文取得→ヤマト送り状発行→印刷まで自動実行する簡易ウォッチャー。

実装はポーリング方式（既定1秒間隔）。ファイルサイズが2回連続で同じになったこと
をもってスキャナーの書き込み完了とみなしてから処理を開始する。
各ステップの所要時間をコンソールに出力する（一連処理のタイミング計測用）。

実行例:
  PYTHONPATH=src/shopify:src/common .venv/bin/python src/yamato/watch_scan_folder.py
  （Ctrl+Cで停止）
"""
import asyncio
import glob
import os
import shutil
import time
from datetime import datetime

import db
from issue_slip_from_scan import process_scanned_pdf, _resolve_path


async def _wait_for_stable_file(path: str, checks: int = 2, interval: float = 0.5) -> None:
    last_size = -1
    stable_count = 0
    while stable_count < checks:
        try:
            size = os.path.getsize(path)
        except FileNotFoundError:
            return
        if size == last_size and size > 0:
            stable_count += 1
        else:
            stable_count = 0
        last_size = size
        await asyncio.sleep(interval)


async def watch_loop(poll_interval: float = 1.0):
    db.init_db()
    settings = db.get_app_settings()
    scan_dir = _resolve_path(settings["scan_folder"])
    archive_dir = _resolve_path(settings["archive_folder"])
    os.makedirs(scan_dir, exist_ok=True)
    os.makedirs(archive_dir, exist_ok=True)

    print("=" * 60)
    print(f"[watch] 監視フォルダ: {scan_dir}")
    print(f"[watch] アーカイブ先: {archive_dir}")
    print("[watch] PDFファイルの格納を待っています... (Ctrl+Cで停止)")
    print("=" * 60)

    seen = set()

    while True:
        for pdf_path in sorted(glob.glob(os.path.join(scan_dir, "*.pdf"))):
            if pdf_path in seen:
                continue
            seen.add(pdf_path)

            t0 = time.monotonic()
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] ● 検知: {os.path.basename(pdf_path)}")

            try:
                await _wait_for_stable_file(pdf_path)
                t1 = time.monotonic()
                print(f"  [+{t1 - t0:5.1f}s] 書き込み完了を確認")

                record = await process_scanned_pdf(pdf_path)
                t2 = time.monotonic()
                print(f"  [+{t2 - t1:5.1f}s] QR読取〜発行〜タグ付与〜印刷まで完了 / ステータス: {db.STATUS_LABELS.get(record['status'], record['status'])}")

                archive_path = os.path.join(archive_dir, os.path.basename(pdf_path))
                if os.path.exists(archive_path):
                    base, ext = os.path.splitext(archive_path)
                    archive_path = f"{base}_{datetime.now().strftime('%H%M%S')}{ext}"
                shutil.move(pdf_path, archive_path)
                t3 = time.monotonic()
                print(f"  [+{t3 - t2:5.1f}s] 指示書をアーカイブへ移動")

                print(f"  ── 合計所要時間: {t3 - t0:.1f}秒 ──")
                if record["status"] == "done":
                    print(f"     注文番号: {record['order_name']} / 伝票番号: {record['yamato_tracking_no']}")
                    print(f"     タグ付与: {record.get('tag_status')}")
                    print(f"     印刷:     {record.get('print_status')}")
                else:
                    print(f"     エラー: {record.get('error_message')}")
            except Exception as e:
                # 1件の想定外エラーで監視プロセス全体を落とさない。詳細はエラー・要対応一覧で確認する。
                print(f"  ✗ 想定外のエラーで処理を中断しました（監視は継続します）: {e}")

        await asyncio.sleep(poll_interval)


if __name__ == "__main__":
    try:
        asyncio.run(watch_loop())
    except KeyboardInterrupt:
        print("\n[watch] 停止しました。")
