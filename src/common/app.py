"""
ヤマト運輸 B2クラウド 送り状自動作成アプリ
"""

import os
import sys

# src/common, src/shopify, src/yamato を直接 import できるようにする
# （PYTHONPATH未設定で `uvicorn src.common.app:app` を実行した場合でも動くように）
_SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _sub in ("common", "shopify", "yamato"):
    _path = os.path.join(_SRC_DIR, _sub)
    if _path not in sys.path:
        sys.path.insert(0, _path)

from datetime import date
from fastapi import FastAPI, Request, HTTPException, Form
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
import httpx

from models import ShipmentRequest, ShipmentResponse, ShopifyOrder, ScanOrderRequest
from yamato_client import create_shipment
import db
from config import STORE_CANDIDATES
import order_sync
import scan_auth
from issue_slip_from_scan import issue_for_order_name, scan_folder_and_issue, find_order

PROJECT_ROOT = os.path.dirname(_SRC_DIR)

app = FastAPI(title="ヤマト送り状自動作成", version="1.0.0")
templates = Jinja2Templates(directory=os.path.join(PROJECT_ROOT, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(PROJECT_ROOT, "static")), name="static")


@app.on_event("startup")
async def on_startup():
    db.init_db()


def _nav_counts() -> dict:
    orders = db.list_orders_cache()
    not_issued = sum(1 for o in orders if o["shipping_method"] == "ヤマト" and o["yamato_status"] != "issued")
    return {
        "processing": not_issued,
        "errors": db.count_shipments(db.ERROR_STATUSES),
    }


# ── フロントエンド ────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    today = date.today().isoformat()
    return templates.TemplateResponse("index.html", {"request": request, "today": today})


# ── 送り状発行API ────────────────────────────────────────────

@app.post("/api/shipment", response_model=ShipmentResponse)
async def create_shipment_api(req: ShipmentRequest):
    """
    送り状を発行する

    フォーム入力 or Shopify連携から呼ばれる
    """
    try:
        result = await create_shipment(req)
        return result
    except httpx.HTTPStatusError as e:
        raise HTTPException(
            status_code=e.response.status_code,
            detail=f"ヤマトAPI エラー: {e.response.text}",
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Shopify Webhook（将来対応） ────────────────────────────────

@app.post("/webhook/shopify/order")
async def shopify_order_webhook(order: ShopifyOrder):
    """
    Shopify 注文作成 Webhook → 自動で送り状発行

    Shopify管理画面 > 設定 > 通知 > Webhook で
    このエンドポイントを登録する
    """
    addr = order.shipping_address
    req = ShipmentRequest(
        recipient_name=addr.get("name", ""),
        recipient_zip=addr.get("zip", "").replace("-", ""),
        recipient_address=(
            addr.get("province", "")
            + addr.get("city", "")
            + addr.get("address1", "")
            + (addr.get("address2") or "")
        ),
        recipient_phone=addr.get("phone", ""),
        sender_name="株式会社MuOG",          # 送り元は固定
        sender_zip="000-0000",               # TODO: .envで設定
        sender_address="送り元住所を設定してください",
        sender_phone="000-0000-0000",
        item_name=order.line_items[0].get("name", "商品") if order.line_items else "商品",
        total_count=len(order.line_items),
        ship_date=date.today().isoformat(),
    )

    try:
        result = await create_shipment(req)
        return {"order_id": order.id, "slip_no": result.slip_no, "success": result.success}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── 管理画面 ──────────────────────────────────────────────────

SETTINGS_FIELDS = ["sender_name", "sender_zip", "sender_address", "sender_address2", "sender_phone", "sender_email", "printer_name"]


@app.get("/admin", include_in_schema=False)
async def admin_root():
    return RedirectResponse(url="/admin/processing")


@app.get("/admin/processing", response_class=HTMLResponse)
async def admin_processing(request: Request, synced: str = "", issued: str = "", scanned: str = ""):
    sync_result = None
    try:
        sync_result = await order_sync.sync_recent_orders()
    except Exception as e:
        sync_result = {"error": str(e)}

    rows = db.list_orders_cache()
    settings = db.get_app_settings()
    return templates.TemplateResponse("admin/processing.html", {
        "request": request, "active": "processing", "counts": _nav_counts(),
        "rows": rows, "sync_result": sync_result, "issue_mode": settings["issue_mode"],
        "synced": synced, "issued": issued, "scanned": scanned,
    })


@app.post("/admin/issue", include_in_schema=False)
async def admin_issue(order_ids: list[int] = Form(...)):
    """手動発行モード：処理状況一覧でチェックした注文の送り状をまとめて発行する"""
    orders = db.get_orders_cache_by_ids(order_ids)
    count = 0
    for order in orders:
        await issue_for_order_name(order["order_name"])
        count += 1
    return RedirectResponse(url=f"/admin/processing?issued={count}", status_code=303)


@app.post("/admin/scan", include_in_schema=False)
async def admin_scan():
    """自動発行モードの代替：スキャンフォルダを今すぐ読み取り、送り状発行までまとめて実行する"""
    results = await scan_folder_and_issue()
    return RedirectResponse(url=f"/admin/processing?scanned={len(results)}", status_code=303)


@app.get("/admin/pdf/{record_id}")
async def admin_pdf(record_id: int):
    record = db.get_shipment(record_id)
    if not record or not record.get("pdf_path") or not os.path.exists(record["pdf_path"]):
        raise HTTPException(status_code=404, detail="PDFが見つかりません")
    return FileResponse(record["pdf_path"], media_type="application/pdf")


@app.get("/admin/history", response_class=HTMLResponse)
async def admin_history(request: Request):
    rows = db.list_shipments(statuses=["done"])
    return templates.TemplateResponse("admin/history.html", {
        "request": request, "active": "history", "counts": _nav_counts(),
        "rows": rows,
    })


@app.get("/admin/errors", response_class=HTMLResponse)
async def admin_errors(request: Request):
    rows = db.list_shipments(statuses=list(db.ERROR_STATUSES))
    return templates.TemplateResponse("admin/errors.html", {
        "request": request, "active": "errors", "counts": _nav_counts(),
        "rows": rows, "status_labels": db.STATUS_LABELS,
    })


@app.get("/admin/settings", response_class=HTMLResponse)
async def admin_settings(request: Request, saved: str = ""):
    settings_by_store = {s["store"]: s for s in db.list_store_settings()}
    stores = [
        {"store": store, **{f: (settings_by_store.get(store, {}) or {}).get(f, "") for f in SETTINGS_FIELDS}}
        for store in STORE_CANDIDATES
    ]
    return templates.TemplateResponse("admin/settings.html", {
        "request": request, "active": "settings", "counts": _nav_counts(),
        "stores": stores, "saved": saved, "app_settings": db.get_app_settings(),
    })


@app.post("/admin/settings", include_in_schema=False)
async def admin_settings_save(
    store: str = Form(...),
    sender_name: str = Form(""),
    sender_zip: str = Form(""),
    sender_address: str = Form(""),
    sender_address2: str = Form(""),
    sender_phone: str = Form(""),
    sender_email: str = Form(""),
    printer_name: str = Form(""),
):
    if store not in STORE_CANDIDATES:
        raise HTTPException(status_code=400, detail=f"不明なストアです: {store}")
    db.upsert_store_settings(
        store,
        sender_name=sender_name,
        sender_zip=sender_zip,
        sender_address=sender_address,
        sender_address2=sender_address2,
        sender_phone=sender_phone,
        sender_email=sender_email,
        printer_name=printer_name,
    )
    return RedirectResponse(url="/admin/settings?saved=1", status_code=303)


@app.post("/admin/settings/global", include_in_schema=False)
async def admin_settings_global_save(
    issue_mode: str = Form("manual"),
    scan_folder: str = Form("input"),
    output_folder: str = Form("output"),
    archive_folder: str = Form("output/archive"),
    issue_tag: str = Form(""),
    scan_pin: str = Form(""),
):
    if issue_mode not in ("manual", "auto"):
        raise HTTPException(status_code=400, detail=f"不明な発行モードです: {issue_mode}")
    db.set_app_settings(
        issue_mode=issue_mode,
        scan_folder=scan_folder,
        output_folder=output_folder,
        archive_folder=archive_folder,
        issue_tag=issue_tag,
        scan_pin=scan_pin,
    )
    return RedirectResponse(url="/admin/settings?saved=1", status_code=303)


# ── スマホQRスキャン画面 ──────────────────────────────────────

@app.get("/scan/login", response_class=HTMLResponse, include_in_schema=False)
async def scan_login_page(request: Request, error: str = ""):
    return templates.TemplateResponse("scan_login.html", {"request": request, "error": error})


@app.post("/scan/login", include_in_schema=False)
async def scan_login_submit(pin: str = Form(...)):
    expected_pin = db.get_app_settings()["scan_pin"]
    if not expected_pin or pin != expected_pin:
        return RedirectResponse(url="/scan/login?error=1", status_code=303)
    response = RedirectResponse(url="/scan", status_code=303)
    scan_auth.set_auth_cookie(response)
    return response


@app.get("/scan", response_class=HTMLResponse, include_in_schema=False)
async def scan_page(request: Request):
    if not scan_auth.is_authorized(request):
        return RedirectResponse(url="/scan/login")
    return templates.TemplateResponse("scan.html", {"request": request})


@app.post("/api/scan/lookup")
async def api_scan_lookup(request: Request, body: ScanOrderRequest):
    """QRから読み取った注文番号をShopifyで検索し、発行前の確認情報を返す（副作用なし）"""
    if not scan_auth.is_authorized(request):
        raise HTTPException(status_code=401, detail="認証が必要です")

    order_name = body.order_name.strip()
    store_name, shopify, order, store_errors = await find_order(order_name)

    if not order:
        if store_errors:
            return {"found": False, "error": f"Shopify APIエラー: {store_errors}"}
        return {"found": False, "error": f"注文 '{order_name}' が見つかりませんでした"}

    recipient = shopify.extract_recipient(order)
    existing = db.find_shipment_by_order_name(order_name)

    return {
        "found": True,
        "order_name": order_name,
        "store": store_name,
        "customer_name": recipient["name"],
        "already_issued": bool(existing),
        "tracking_number": existing["yamato_tracking_no"] if existing else None,
    }


@app.post("/api/scan/issue")
async def api_scan_issue(request: Request, body: ScanOrderRequest):
    """スマホからの依頼で送り状を発行し、印刷まで実行する"""
    if not scan_auth.is_authorized(request):
        raise HTTPException(status_code=401, detail="認証が必要です")

    record = await issue_for_order_name(body.order_name.strip())
    return {
        "status": record["status"],
        "status_label": db.STATUS_LABELS.get(record["status"], record["status"]),
        "tracking_number": record.get("yamato_tracking_no"),
        "print_status": record.get("print_status"),
        "error_message": record.get("error_message"),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=3131, reload=True)
