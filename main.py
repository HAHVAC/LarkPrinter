import os
import uvicorn
import lark_oapi as lark
from lark_oapi.api.bitable.v1 import *
from fastapi import FastAPI, Request, Response
from fastapi.templating import Jinja2Templates
from weasyprint import HTML
import datetime
from dotenv import load_dotenv

# --- FIX LỖI WINDOWS ---
if os.name == 'nt':
    gtk_path = r"C:\Program Files\GTK3-Runtime Win64\bin"
    if os.path.exists(gtk_path):
        os.add_dll_directory(gtk_path)

# 1. Load cấu hình
load_dotenv()
APP_ID = os.getenv("LARK_APP_ID")
APP_SECRET = os.getenv("LARK_APP_SECRET")
BASE_TOKEN = os.getenv("BASE_TOKEN")
TABLE_MASTER_ID = os.getenv("TABLE_MASTER_ID")
TABLE_DETAIL_ID = os.getenv("TABLE_DETAIL_ID")

# 2. Khởi tạo Client
client = lark.Client.builder().app_id(APP_ID).app_secret(APP_SECRET).build()

app = FastAPI()
templates = Jinja2Templates(directory="templates")

# --- HÀM HỖ TRỢ ---

def get_master_record(record_id):
    """Lấy thông tin bảng Master"""
    req = GetAppTableRecordRequest.builder() \
        .app_token(BASE_TOKEN) \
        .table_id(TABLE_MASTER_ID) \
        .record_id(record_id) \
        .build()
    resp = client.bitable.v1.app_table_record.get(req)
    if not resp.success():
        print(f"❌ Lỗi lấy Master: {resp.msg}")
        return None
    return resp.data.record.fields

def get_details_by_ids(list_record_ids):
    """
    CÁCH 1 (Ưu tiên): Lấy vật tư theo danh sách ID (Chính xác 100%)
    Dùng khi bảng Master đã có cột Link trỏ sang bảng con.
    """
    if not list_record_ids:
        return []
    
    # Tạo filter: OR từng ID (CurrentValue.[record_id] = "id1" OR ...)
    # Lưu ý: Lark giới hạn độ dài filter, nhưng với phiếu xuất kho thường < 50 item nên OK.
    conditions = []
    for rid in list_record_ids:
        conditions.append(f'CurrentValue.[record_id]="{rid}"')
    
    filter_cond = " OR ".join(conditions)
    print(f"🔹 Cách 1: Tìm theo ID trực tiếp. Filter: {filter_cond[:50]}...")

    req = ListAppTableRecordRequest.builder() \
        .app_token(BASE_TOKEN) \
        .table_id(TABLE_DETAIL_ID) \
        .filter(filter_cond) \
        .page_size(100) \
        .build()
        
    resp = client.bitable.v1.app_table_record.list(req)
    if not resp.success() or not resp.data.items:
        return []
    return [item.fields for item in resp.data.items]

def get_details_by_so_phieu_text(so_phieu_text):
    """
    CÁCH 2 (Dự phòng): Lấy vật tư bằng cách tìm Text "Số phiếu"
    Dùng khi người dùng nhập tay mã phiếu mà không dùng Link Record.
    """
    if not so_phieu_text: return []
    
    # Trim space để tránh lỗi "PX-001 " khác "PX-001"
    clean_text = so_phieu_text.strip()
    filter_cond = f'CurrentValue.[Số phiếu]="{clean_text}"'
    print(f"🔸 Cách 2: Tìm theo Text 'Số phiếu'. Filter: {filter_cond}")

    req = ListAppTableRecordRequest.builder() \
        .app_token(BASE_TOKEN) \
        .table_id(TABLE_DETAIL_ID) \
        .filter(filter_cond) \
        .page_size(100) \
        .build()

    resp = client.bitable.v1.app_table_record.list(req)
    if not resp.success() or not resp.data.items:
        return []
    return [item.fields for item in resp.data.items]

# --- API CHÍNH ---

@app.get("/print-phieu-xuat")
async def print_phieu(request: Request, record_id: str):
    print(f"\n--- IN PHIẾU: {record_id} ---")
    
    # 1. Lấy Master
    master = get_master_record(record_id)
    if not master:
        return Response(content="Lỗi: Không tìm thấy phiếu này (Sai Record ID).", media_type="text/plain")

    so_phieu = str(master.get("Số phiếu", "") or "").strip()
    if isinstance(master.get("Số phiếu"), list): # Nếu là cột Link/Lookup
         so_phieu = master.get("Số phiếu")[0].get("text", "")

    # 2. CHIẾN THUẬT LẤY VẬT TƯ (QUAN TRỌNG)
    details = []
    
    # >> Ưu tiên 1: Lấy từ cột Link "Chi tiết nhập xuất" (Nếu có)
    # Cột này chứa danh sách Record ID của các dòng bảng con
    link_data = master.get("Chi tiết nhập xuất") # Tên cột từ file CSV Master
    
    if link_data and isinstance(link_data, list):
        # Lấy danh sách ID
        detail_ids = [item['record_id'] for item in link_data if 'record_id' in item]
        if detail_ids:
            print(f"✅ Tìm thấy {len(detail_ids)} liên kết ID từ Master.")
            details = get_details_by_ids(detail_ids)
    
    # >> Ưu tiên 2: Nếu cách 1 thất bại (hoặc chưa link), dùng cách tìm theo Text "Số phiếu"
    if not details:
        print("⚠️ Không thấy link ID, chuyển sang tìm theo mã Số phiếu (Text)...")
        details = get_details_by_so_phieu_text(so_phieu)

    print(f"📦 Tổng cộng tìm thấy: {len(details)} dòng vật tư.")

    # 3. Render PDF (Giống cũ nhưng thêm safe check)
    ts_ngay = master.get("Ngày xuất nhập", 0)
    ngay_str = datetime.datetime.fromtimestamp(ts_ngay/1000).strftime("%d/%m/%Y") if ts_ngay else "..."

    context = {
        "request": request,
        "current_date": datetime.datetime.now().strftime("%H:%M:%S %d/%m/%Y"),
        "so_phieu": so_phieu,
        "du_an": str(master.get("Hạng mục", "") or ""),
        "xuong": str(master.get("Xưởng", "") or ""),
        "ngay_xuat": ngay_str,
        "noi_dung": str(master.get("Nội dung xuất", "") or ""),
        "items": []
    }

    for item in details:
        # Format số lượng
        sl = item.get("SL đề nghị đợt này", 0)
        try:
            sl = "{:,.2f}".format(float(sl)).replace(".00", "")
        except: pass
            
        context["items"].append({
            "ma_vt": str(item.get("Mã vật tư", "") or ""),
            "ten_sp": str(item.get("Tên vật tư, thiết bị", "") or ""),
            "dvt": str(item.get("Đơn vị tính", "") or ""),
            "quy_cach": str(item.get("Quy cách, Mã hiệu", "") or ""),
            "nhan_hieu": str(item.get("Nhãn hiệu", "") or ""),
            "so_luong": str(sl),
            "ghi_chu": str(item.get("Ghi chú", "") or "")
        })

    try:
        template = templates.get_template("phieu_xuat_kho.html")
        html_content = template.render(context)
        pdf_bytes = HTML(string=html_content).write_pdf()
        filename = f"PX-{so_phieu}.pdf"
        return Response(content=pdf_bytes, media_type="application/pdf", headers={"Content-Disposition": f"inline; filename={filename}"})
    except Exception as e:
        return Response(content=f"Lỗi tạo PDF: {str(e)}", media_type="text/plain")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)