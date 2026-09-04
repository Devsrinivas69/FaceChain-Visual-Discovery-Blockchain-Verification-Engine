from playwright.sync_api import sync_playwright
import time
from pathlib import Path

tmp_upload = Path("data/cache/_fixed_upload.jpg")

t0 = time.time()
with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-setuid-sandbox",
            "--disable-dev-shm-usage",
            "--disable-gpu",
            "--disable-blink-features=AutomationControlled",
        ]
    )
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        viewport={"width": 1400, "height": 1000},
    )
    page = context.new_page()
    
    # Block heavy tracking and fonts
    def block_unneeded(route):
        req_url = route.request.url.lower()
        res_type = route.request.resource_type
        if res_type in ["media", "font"] or any(x in req_url for x in ["bat.bing.com", "onecollector", "google-analytics", "clarity.ms", "doubleclick"]):
            route.abort()
        else:
            route.continue_()
            
    page.route("**/*", block_unneeded)
    
    print("Navigating with domcontentloaded...")
    t_nav = time.time()
    page.goto("https://www.bing.com/visualsearch", timeout=15000, wait_until="domcontentloaded")
    print(f"Navigation completed in {time.time() - t_nav:.2f}s! URL: {page.url[:60]}")
    
    # Wait for file input with state='attached' (since it is a hidden element!)
    fi = page.wait_for_selector('input[type="file"]', state="attached", timeout=6000)
    print("File input located!")
    
    # Upload
    fi.set_input_files(str(tmp_upload))
    print("Uploaded! Waiting for search results...")
    
    t_wait = time.time()
    for i in range(10):
        page.wait_for_timeout(600)
        curr = page.url
        if "search" in curr and ("bcid=" in curr or "q=" in curr or "view=detailv2" in curr):
            print(f"Results URL reached in {time.time() - t_wait:.2f}s! URL: {curr[:70]}")
            break
            
    page.wait_for_timeout(1500)
    
    # Count cards
    count = page.evaluate("() => document.querySelectorAll('img[src*=\"th/id/OIP\"], img[src*=\"th?id=OIP\"]').length")
    print(f"Visual match images found: {count}")
    print(f"TOTAL TIME: {time.time() - t0:.2f}s")
    browser.close()
