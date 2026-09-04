import time
from pathlib import Path
from PIL import Image
import io
from playwright.sync_api import sync_playwright

def fast_bing_search(img_path: Path):
    t0 = time.time()
    
    # 1. Resize to max 800px for ultra fast upload
    im = Image.open(img_path).convert("RGB")
    if max(im.size) > 800:
        im.thumbnail((800, 800), Image.LANCZOS)
    buf = io.BytesIO()
    im.save(buf, format="JPEG", quality=80)
    
    tmp_path = Path("data/cache/_fast_test.jpg")
    tmp_path.write_bytes(buf.getvalue())
    print(f"Image prepared in {time.time() - t0:.2f}s, size: {tmp_path.stat().st_size} bytes")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--disable-extensions",
            ]
        )
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        
        # Navigate
        t_nav = time.time()
        print("Navigating...")
        try:
            page.goto("https://www.bing.com/visualsearch", timeout=12000, wait_until="domcontentloaded")
            print(f"Navigated in {time.time() - t_nav:.2f}s, URL: {page.url[:60]}")
        except Exception as e:
            print("Nav exception:", e)
            
        page.wait_for_timeout(800)
        
        # Locate input[type="file"]
        fi = page.query_selector('input[type="file"]')
        if not fi:
            try:
                fi = page.wait_for_selector('input[type="file"]', state="attached", timeout=4000)
            except Exception:
                pass
                
        if not fi:
            print("File input not found!")
            browser.close()
            return []
            
        print("File input found, uploading...")
        fi.set_input_files(str(tmp_path))
        
        # Wait for results page
        t_res = time.time()
        for i in range(10):
            page.wait_for_timeout(600)
            curr = page.url
            if "search" in curr and ("bcid=" in curr or "q=" in curr or "view=detailv2" in curr):
                print(f"Results page reached in {time.time() - t_res:.2f}s: {curr[:70]}")
                break
                
        page.wait_for_timeout(1500)
        
        # Extract cards
        cards = page.evaluate("""() => {
            const list = [];
            const seen = new Set();
            for (const img of document.querySelectorAll('img[src*="th/id/OIP"], img[src*="th?id=OIP"]')) {
                const src = img.src;
                if (!src || seen.has(src)) continue;
                seen.add(src);
                const parentA = img.closest('a') || img.parentElement?.querySelector('a');
                list.push({
                    img: src,
                    url: parentA ? parentA.href : src
                });
            }
            return list;
        }""")
        print(f"Discovered {len(cards)} cards in {time.time() - t0:.2f}s total!")
        browser.close()
        return cards

if __name__ == "__main__":
    cards = fast_bing_search(Path("data/input/upload_image.png"))
