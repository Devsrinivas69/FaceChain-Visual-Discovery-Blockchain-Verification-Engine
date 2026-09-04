from playwright.sync_api import sync_playwright
import time
from pathlib import Path

tmp_upload = Path("data/cache/_fixed_upload.jpg")

with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    
    def log_req(r):
        if "sbiupload" in r.url or "kblob" in r.url or "view=detailv2" in r.url:
            print("=== MATCHED REQUEST ===")
            print("URL:", r.url)
            print("Method:", r.method)
            print("Headers:", r.headers)
            print("PostData length:", len(r.post_data_buffer) if r.post_data_buffer else 0)
            print("PostData start:", str(r.post_data)[:200] if r.post_data else "None")
    
    page.on("request", log_req)
    
    page.goto("https://www.bing.com/visualsearch", timeout=25000)
    page.wait_for_timeout(1500)
    fi = page.query_selector('input[type="file"]')
    if fi:
        fi.set_input_files(str(tmp_upload))
        page.wait_for_timeout(5000)
    
    browser.close()
