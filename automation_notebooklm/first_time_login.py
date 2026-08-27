from playwright.sync_api import sync_playwright

# Đặt đường dẫn tuyệt đối cho chắc chắn
USER_DATA_PATH = "./playwright_data" 

def run_login():
    print("Khởi động Browser Persistent...")
    with sync_playwright() as p:
        # headless=False để hiện GUI về máy bạn (qua X11)
        # Playwright sẽ tự tạo thư mục nếu chưa có
        context = p.chromium.launch_persistent_context(
            user_data_dir=USER_DATA_PATH,
            headless=False, 
            args=["--start-maximized", "--disable-blink-features=AutomationControlled"] # Tùy chọn
        )
        
        page = context.pages[0] # Persistent context luôn có sẵn 1 page
        
        print("Đang truy cập trang web...")
        page.goto("https://notebooklm.google.com/notebook/89afd560-bec3-4717-8346-f5a733a58128?authuser=1") 
        
        input(">>> HÃY LOGIN TRÊN CỬA SỔ HIỆN RA. SAU ĐÓ BẤM ENTER TẠI ĐÂY ĐỂ THOÁT...")
        
        # Khi đóng context, mọi thứ tự động lưu vào thư mục USER_DATA_PATH
        context.close()
        print("Đã lưu session thành công!")

if __name__ == "__main__":
    run_login()