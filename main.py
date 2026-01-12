import os
import re
import logging
import datetime
from typing import Any, Dict, List, Optional, Tuple

import uvicorn
import lark_oapi as lark
from lark_oapi.api.bitable.v1 import (
    GetAppTableRecordRequest,
    ListAppTableRecordRequest,
    BatchGetAppTableRecordRequest,
)
from fastapi import FastAPI, Request, Response, Header, HTTPException
from fastapi.templating import Jinja2Templates
from weasyprint import HTML
from dotenv import load_dotenv

# ============================================================
# CONFIG
# ============================================================

load_dotenv()

APP_ID = os.getenv("LARK_APP_ID", "").strip()
APP_SECRET = os.getenv("LARK_APP_SECRET", "").strip()

# Bitable
BASE_TOKEN = os.getenv("LARK_BASE_TOKEN", "").strip()
TABLE_MASTER_ID = os.getenv("LARK_TABLE_MASTER_ID", "").strip()
TABLE_DETAIL_ID = os.getenv("LARK_TABLE_DETAIL_ID", "").strip()

# Optional security for printing endpoint (recommended if endpoint is public)
# Nếu để trống -> endpoint vẫn public như hiện tại.
PRINT_API_KEY = os.getenv("PRINT_API_KEY", "").strip()

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_DIR = os.getenv("TEMPLATE_DIR", os.path.join(BASE_DIR, "templates"))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("phieu-xuat-kho")

if not (APP_ID and APP_SECRET and BASE_TOKEN and TABLE_MASTER_ID and TABLE_DETAIL_ID):
    logger.warning(
        "Missing env vars. Required: LARK_APP_ID, LARK_APP_SECRET, "
        "LARK_BASE_TOKEN, LARK_TABLE_MASTER_ID, LARK_TABLE_DETAIL_ID"
    )

# ============================================================
# LARK CLIENT
# ============================================================

client = (
    lark.Client.builder()
    .app_id(APP_ID)
    .app_secret(APP_SECRET)
    .log_level(lark.LogLevel.WARN)
    .build()
)

# ============================================================
# FASTAPI
# ============================================================

app = FastAPI()
templates = Jinja2Templates(directory=TEMPLATE_DIR)

# ============================================================
# HELPERS
# ============================================================

def as_text(v: Any) -> str:
    """Normalize Lark field values to a printable string.
    - Single line text: str
    - Lookup / Select / Link: can be list[dict] / dict
    """
    if v is None:
        return ""
    if isinstance(v, str):
        return v.strip()
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, dict):
        return str(v.get("text") or v.get("name") or v.get("value") or "").strip()
    if isinstance(v, list):
        parts = [as_text(x) for x in v]
        parts = [p for p in parts if p]
        return ", ".join(parts)
    return str(v).strip()


def extract_link_record_ids(link_value: Any) -> List[str]:
    """Master field 'Chi tiết nhập xuất' is a real Link Record (list of dict with record_id)."""
    if not link_value or not isinstance(link_value, list):
        return []
    out: List[str] = []
    for x in link_value:
        if isinstance(x, dict) and x.get("record_id"):
            out.append(str(x["record_id"]).strip())
    return [rid for rid in out if rid]


def parse_date_field(v: Any) -> str:
    """Accept timestamp(ms) or string; return dd/mm/YYYY or '...'."""
    if not v:
        return "..."
    if isinstance(v, (int, float)):
        try:
            return datetime.datetime.fromtimestamp(v / 1000).strftime("%d/%m/%Y")
        except Exception:
            return "..."
    s = as_text(v)
    for fmt in ("%Y/%m/%d", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.datetime.strptime(s, fmt).strftime("%d/%m/%Y")
        except Exception:
            pass
    return s or "..."


def format_number_vi(v: Any) -> str:
    """Format quantities safely: supports '5,0', '1 234,50', '1234.5'."""
    s = as_text(v)
    if not s:
        return ""
    s = s.replace(" ", "")
    if "," in s and "." not in s:
        s = s.replace(",", ".")
    if "," in s and "." in s:
        s = s.replace(",", "")
    try:
        num = float(s)
        out = f"{num:,.2f}".replace(".00", "")
        return out
    except Exception:
        return as_text(v)


def safe_filename(name: str) -> str:
    """Prevent weird characters in filename."""
    name = name.strip()
    name = re.sub(r"[^0-9A-Za-z_\-\.]+", "_", name)
    return name or "phieu_xuat_kho"

# ============================================================
# LARK DATA ACCESS
# ============================================================

def get_master_record(record_id: str) -> Optional[Dict[str, Any]]:
    """Fetch Master record fields by record_id."""
    req = (
        GetAppTableRecordRequest.builder()
        .app_token(BASE_TOKEN)
        .table_id(TABLE_MASTER_ID)
        .record_id(record_id)
        .build()
    )
    resp = client.bitable.v1.app_table_record.get(req)
    if not resp.success():
        logger.error("Get master failed: %s", resp.msg)
        return None
    return resp.data.record.fields


def batch_get_detail_records(record_ids: List[str]) -> List[Tuple[str, Dict[str, Any]]]:
    """Batch get detail records (<=100) and return list of (record_id, fields)."""
    if not record_ids:
        return []

    body = (
        lark.api.bitable.v1.BatchGetAppTableRecordRequestBody.builder()
        .records(record_ids)
        .build()
    )
    req = (
        BatchGetAppTableRecordRequest.builder()
        .app_token(BASE_TOKEN)
        .table_id(TABLE_DETAIL_ID)
        .request_body(body)
        .build()
    )
    resp = client.bitable.v1.app_table_record.batch_get(req)

    if not resp.success() or not resp.data or not resp.data.records:
        logger.warning("Batch get details returned empty: %s", getattr(resp, "msg", ""))
        return []

    result: List[Tuple[str, Dict[str, Any]]] = []
    for r in resp.data.records:
        rid = getattr(r, "record_id", "") or ""
        result.append((rid, r.fields))
    return result


def get_details_by_so_phieu_text(so_phieu_text: str) -> List[Dict[str, Any]]:
    """Fallback: list details by text 'Số phiếu' (page_size=100 is OK per your constraint)."""
    clean = (so_phieu_text or "").strip()
    if not clean:
        return []
    filter_cond = f'CurrentValue.[Số phiếu]="{clean}"'
    req = (
        ListAppTableRecordRequest.builder()
        .app_token(BASE_TOKEN)
        .table_id(TABLE_DETAIL_ID)
        .filter(filter_cond)
        .page_size(100)
        .build()
    )
    resp = client.bitable.v1.app_table_record.list(req)
    if not resp.success() or not resp.data or not resp.data.items:
        return []
    return [it.fields for it in resp.data.items]

# ============================================================
# ENDPOINT
# ============================================================

@app.get("/print-phieu-xuat")
def print_phieu_xuat(
    record_id: str,
    request: Request,
    x_api_key: str = Header(default=""),
):
    # Security (optional): enable by setting PRINT_API_KEY env var
    if PRINT_API_KEY and x_api_key != PRINT_API_KEY:
        raise HTTPException(status_code=401, detail="Unauthorized")

    record_id = (record_id or "").strip()
    if not record_id:
        raise HTTPException(status_code=400, detail="Missing record_id")

    master = get_master_record(record_id)
    if not master:
        raise HTTPException(status_code=404, detail="Master record not found")

    so_phieu = as_text(master.get("Số phiếu"))

    # Prefer Link Record ids from master (you confirmed it's real link record)
    detail_ids = extract_link_record_ids(master.get("Chi tiết nhập xuất"))
    details: List[Dict[str, Any]] = []

    if detail_ids:
        got = batch_get_detail_records(detail_ids)
        # preserve order from master
        got_map = {rid: fields for rid, fields in got if rid}
        details = [got_map[rid] for rid in detail_ids if rid in got_map]

    # Fallback by text
    if not details:
        details = get_details_by_so_phieu_text(so_phieu)

    ngay_str = parse_date_field(master.get("Ngày xuất nhập"))

    context = {
        "request": request,
        "current_date": datetime.datetime.now().strftime("%H:%M:%S %d/%m/%Y"),
        "so_phieu": so_phieu,
        "du_an": as_text(master.get("Hạng mục")),
        "xuong": as_text(master.get("Xưởng")),
        "ngay_xuat": ngay_str,
        "noi_dung": as_text(master.get("Nội dung xuất")),
        "items": [],
    }

    for item in details:
        context["items"].append(
            {
                "ma_vt": as_text(item.get("Mã vật tư")),
                "ten_sp": as_text(item.get("Tên vật tư, thiết bị")),
                "dvt": as_text(item.get("Đơn vị tính")),     # lookup
                "quy_cach": as_text(item.get("Quy cách, Mã hiệu")),
                "nhan_hieu": as_text(item.get("Nhãn hiệu")), # lookup
                "so_luong": format_number_vi(item.get("SL đề nghị đợt này")),
                "ghi_chu": as_text(item.get("Ghi chú")),
            }
        )

    try:
        template = templates.get_template("phieu_xuat_kho.html")
        html_content = template.render(context)

        pdf_bytes = HTML(string=html_content, base_url=BASE_DIR).write_pdf()

        filename = safe_filename(f"PX-{so_phieu}") + ".pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'inline; filename="{filename}"'},
        )
    except Exception as e:
        logger.exception("PDF render failed")
        return Response(content=f"Lỗi tạo PDF: {str(e)}", media_type="text/plain")


if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=True)
