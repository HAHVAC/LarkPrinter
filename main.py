import os
import uvicorn
import lark_oapi as lark
from lark_oapi.api.bitable.v1 import *
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.templating import Jinja2Templates
from weasyprint import HTML
import datetime
from dotenv import load_dotenv

# --- CẤU HÌNH FIX LỖI WINDOWS (CHO LOCAL) ---
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

def get_detail_items_by_so_phieu(so_phieu_text):
    """Lấy chi tiết vật tư theo Số phiếu"""
    if not so_phieu_text:
        return []

    # Filter: Tìm các dòng ở bảng con có cột 'Số phiếu' chứa giá trị này
    # Lưu ý: Với trường Link Record, filter hơi khác biệt, ta dùng CONTAINS hoặc bằng chính xác chuỗi
    # Ở đây dùng cú pháp an toàn nhất cho Link Record text
    filter_cond = f'CurrentValue.[Số phiếu] = "{so_phieu_text}"'
    
    print(f"🔍 Đang tìm Detail với filter: {filter_cond}") # Log debug

    req = ListAppTableRecordRequest.builder() \
        .app_token(BASE_TOKEN) \
        .table_id(TABLE_DETAIL_ID) \
        .filter(filter_cond) \
        .page_size(100) \
        .build()
        
    resp = client.bitable.v1.app_table_record.list(req)
    
    if not resp.success():
        print(f"❌ Lỗi lấy Detail: {resp.msg}")
        return []
    
    if not resp.data.items:
        print("⚠️ Không tìm thấy vật tư nào khớp mã phiếu này.")
        return []
        
    return [item.fields for item in resp.data.items]

# --- API CHÍNH ---

@app.get("/print-phieu-xuat")
async def print_phieu(request: Request, record_id: str):
    print(f"\n--- YÊU CẦU IN MỚI: {record_id} ---")
    
    # B1: Lấy Master
    master = get_master_record(record_id)
    if not master:
        # Thay vì lỗi 500, trả về thông báo rõ ràng
        return Response(content="Lỗi: Không tìm thấy dữ liệu Phiếu (Master). Kiểm tra lại Record ID.", media_type="text/plain")

    # Debug dữ liệu master lấy được
    print(f"✅ Dữ liệu Master: {master}")

    # Lấy số phiếu (Dùng get để tránh lỗi nếu không có cột này)
    # Lưu ý: Kiểm tra xem cột trong Base là "Số phiếu" hay "Số phiếu " (dư space)
    # Dựa vào CSV bạn gửi, tên cột là "Số phiếu"
    so_phieu = master.get("Số phiếu", "")
    
    # Xử lý trường hợp số phiếu là list (do Link record hoặc Lookup trả về mảng)
    if isinstance(so_phieu, list):
        so_phieu = so_phieu[0].get("text", "") if so_phieu else ""
    elif isinstance(so_phieu, dict):
        so_phieu = so_phieu.get("text", "")
    
    so_phieu = str(so_phieu).strip() # Xóa khoảng trắng thừa

    if not so_phieu:
        return Response(content="Lỗi: Phiếu này chưa có 'Số phiếu'. Vui lòng điền Số phiếu trên Lark trước.", media_type="text/plain")

    print(f"🎫 Số phiếu cần tìm: '{so_phieu}'")

    # B2: Lấy Detail
    details = get_detail_items_by_so_phieu(so_phieu)
    print(f"📦 Tìm thấy {len(details)} dòng chi tiết.")

    # B3: Xử lý hiển thị (Safe Mode - Chống lỗi None)
    
    # Xử lý ngày
    ts_ngay = master.get("Ngày xuất nhập", 0)
    ngay_str = "..."
    if isinstance(ts_ngay, int) and ts_ngay > 0:
        ngay_str = datetime.datetime.fromtimestamp(ts_ngay / 1000).strftime("%d/%m/%Y")

    # Xử lý Hạng mục/Dự án (Tránh lỗi nếu cột này trống)
    du_an_raw = master.get("Hạng mục", "")
    du_an = str(du_an_raw) if du_an_raw else ""

    context = {
        "request": request,
        "current_date": datetime.datetime.now().strftime("%H:%M:%S %d/%m/%Y"),
        "so_phieu": so_phieu,
        "du_an": du_an, 
        "xuong": str(master.get("Xưởng", "") or ""),
        "ngay_xuat": ngay_str,
        "noi_dung": str(master.get("Nội dung xuất", "") or ""),
        "items": []
    }

    # Map dữ liệu Detail (Dựa chính xác vào tên cột CSV bảng con)
    for item in details:
        # Safe get số lượng
        sl = item.get("SL đề nghị đợt này", 0)
        try:
            sl_float = float(sl)
            sl_fmt = "{:,.2f}".format(sl_float).replace(".00", "")
        except:
            sl_fmt = str(sl)

        context["items"].append({
            "ma_vt": str(item.get("Mã vật tư", "") or ""),
            "ten_sp": str(item.get("Tên vật tư, thiết bị", "") or ""), # Check kỹ tên cột này trong Base
            "dvt": str(item.get("Đơn vị tính", "") or ""),
            "quy_cach": str(item.get("Quy cách, Mã hiệu", "") or ""),
            "nhan_hieu": str(item.get("Nhãn hiệu", "") or ""),
            "so_luong": sl_fmt,
            "ghi_chu": str(item.get("Ghi chú", "") or "")
        })

    # B4: Render PDF
    try:
        template = templates.get_template("phieu_xuat_kho.html")
        html_content = template.render(context)
        pdf_bytes = HTML(string=html_content).write_pdf()
        
        filename = f"PX-{so_phieu}.pdf"
        # Dùng inline để mở preview, attachment để tải luôn
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"inline; filename={filename}"}
        )
    except Exception as e:
        error_msg = f"Lỗi tạo PDF (WeasyPrint): {str(e)}"
        print(f"❌ {error_msg}")
        return Response(content=error_msg, media_type="text/plain")

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)