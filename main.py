import os
import uvicorn
import lark_oapi as lark
from lark_oapi.api.bitable.v1 import *
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.templating import Jinja2Templates
from weasyprint import HTML
import datetime
from dotenv import load_dotenv

# 1. Load cấu hình từ file .env
load_dotenv()

APP_ID = os.getenv("LARK_APP_ID")
APP_SECRET = os.getenv("LARK_APP_SECRET")
BASE_TOKEN = os.getenv("BASE_TOKEN")
TABLE_MASTER_ID = os.getenv("TABLE_MASTER_ID")
TABLE_DETAIL_ID = os.getenv("TABLE_DETAIL_ID")

# 2. Khởi tạo Lark Client
client = lark.Client.builder().app_id(APP_ID).app_secret(APP_SECRET).build()

# 3. Khởi tạo FastAPI
app = FastAPI()
templates = Jinja2Templates(directory="templates")

# --- HÀM HỖ TRỢ LẤY DỮ LIỆU ---

def get_master_record(record_id):
    """Lấy thông tin 1 dòng từ bảng Master theo Record ID"""
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
    """
    Lấy danh sách vật tư từ bảng Detail.
    Logic: Tìm các dòng mà cột 'Số phiếu' bên bảng con == Số phiếu bên bảng cha
    """
    # Cú pháp Filter của Lark: CurrentValue.[Tên Cột] = "Giá trị"
    # Lưu ý: Tên cột phải chính xác 100% như trong Base
    filter_cond = f'CurrentValue.[Số phiếu] = "{so_phieu_text}"'
    
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
        return []
        
    return [item.fields for item in resp.data.items]

# --- API ENDPOINT ---

@app.get("/print-phieu-xuat")
async def print_phieu(request: Request, record_id: str):
    print(f"🖨️ Đang xử lý yêu cầu in cho Record ID: {record_id}")
    
    # B1: Lấy dữ liệu Master
    master = get_master_record(record_id)
    if not master:
        raise HTTPException(status_code=404, detail="Không tìm thấy phiếu xuất kho. Kiểm tra lại Record ID.")

    # Lấy Số phiếu để đi tìm các mặt hàng liên quan
    so_phieu = master.get("Số phiếu", "")
    if not so_phieu:
        raise HTTPException(status_code=400, detail="Phiếu này chưa có Số phiếu, không thể tìm chi tiết.")

    # B2: Lấy dữ liệu Detail dựa trên Số phiếu
    details = get_detail_items_by_so_phieu(so_phieu)
    print(f"✅ Tìm thấy {len(details)} vật tư cho phiếu {so_phieu}")

    # B3: Xử lý dữ liệu hiển thị (Format ngày, số...)
    # Xử lý ngày: Lark trả về timestamp (milliseconds)
    ts_ngay = master.get("Ngày xuất nhập", 0)
    if isinstance(ts_ngay, int) and ts_ngay > 0:
        ngay_str = datetime.datetime.fromtimestamp(ts_ngay / 1000).strftime("%d/%m/%Y")
    else:
        ngay_str = "..."

    # Mapping dữ liệu vào context để Jinja2 điền vào HTML
    context = {
        "request": request,
        "current_date": datetime.datetime.now().strftime("%H:%M:%S %d/%m/%Y"),
        
        "so_phieu": so_phieu,
        # Nếu cột 'Hạng mục' là Link hoặc Text, cần xử lý safe
        "du_an": master.get("Hạng mục", "NHÀ MÁY GOERTEK (GIAI ĐOẠN 3)"), 
        "xuong": master.get("Xưởng", ""),
        "ngay_xuat": ngay_str,
        "noi_dung": master.get("Nội dung xuất", ""),
        
        "items": []
    }

    # Loop qua danh sách detail để map đúng tên cột trong Base vào tên biến HTML
    for item in details:
        # Nếu cột là kiểu số, format đẹp (ví dụ: 60.0)
        sl = item.get("SL đề nghị đợt này", 0)
        sl_formatted = "{:,.2f}".format(float(sl)) if sl else "0"

        context["items"].append({
            "ma_vt": item.get("Mã vật tư", ""),
            "ten_sp": item.get("Tên vật tư, thiết bị", ""),
            "dvt": item.get("Đơn vị tính", ""),
            "quy_cach": item.get("Quy cách, Mã hiệu", ""),
            "nhan_hieu": item.get("Nhãn hiệu", ""),
            "so_luong": sl_formatted.replace(".00", ""), # Bỏ số thập phân nếu chẵn
            "ghi_chu": item.get("Ghi chú", "")
        })

    # B4: Tạo PDF
    try:
        template = templates.get_template("phieu_xuat_kho.html")
        html_content = template.render(context)
        
        # Render PDF
        pdf_bytes = HTML(string=html_content).write_pdf()
        
    except Exception as e:
        print(f"❌ Lỗi WeasyPrint: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Lỗi tạo PDF: {str(e)}")

    # B5: Trả file về trình duyệt
    # Content-Disposition: inline giúp trình duyệt mở preview luôn thay vì tải ngầm
    filename = f"PX-{so_phieu}.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"inline; filename={filename}"}
    )

if __name__ == "__main__":
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)