from playwright.sync_api import sync_playwright
import time
from pathlib import Path

img_path = Path("data/input/upload_image.png").resolve()

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
    
    print("Navigating with wait_until='domcontentloaded'...")
    page.goto("https://www.bing.com/visualsearch", timeout=15000, wait_until="domcontentloaded")
    print(f"Navigation finished in {time.time() - t0:.2f}s! Current URL: {page.url}")
    
    # Wait for file input attached
    t_fi = time.time()
    fi = page.wait_for_selector('input[type="file"]', state="attached", timeout=8000)
    print(f"File input located in {time.time() - t_fi:.2f}s!")
    
    # Set input file
    print("Uploading file...")
    fi.set_input_files(str(img_path))
    
    # Wait for results navigation
    t_nav = time.time()
    for i in range(12):
        page.wait_for_timeout(800)
        curr = page.url
        if "search" in curr and ("bcid=" in curr or "q=" in curr or "view=detailv2" in curr):
            print(f"Results page reached at {time.time() - t_nav:.2f}s! URL: {curr[:70]}")
            break
            
    page.wait_for_timeout(2000)
    cards = page.evaluate("""() => {
        const list = [];
        for (const img of document.querySelectorAll('img[src*="th/id/OIP"], img[src*="th?id=OIP"]')) {
            list.push(img.src);
        }
        return list;
    }""")
    print(f"Discovered {len(cards)} visual match cards in {time.time() - t0:.2f}s total!")
    browser.close()
