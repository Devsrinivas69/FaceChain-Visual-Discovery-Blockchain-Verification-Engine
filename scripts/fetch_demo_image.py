"""Download a well-indexed public domain portrait for demo.jpg."""
import requests, pathlib, sys

headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

sources = [
    # Obama official White House portrait (US Govt public domain)
    ("Obama", "https://upload.wikimedia.org/wikipedia/commons/8/8d/President_Barack_Obama.jpg"),
    # Steve Jobs (widely indexed, CC license)
    ("Jobs", "https://upload.wikimedia.org/wikipedia/commons/b/b9/Steve_Jobs_Headshot_2010-CROP_%28cropped_2%29.jpg"),
    # Wikipedia mobile redirect (may bypass strict referrer check)
    ("Einstein-m", "https://en.m.wikipedia.org/wiki/Special:FilePath/Albert_Einstein_Head.jpg"),
]

out = pathlib.Path("data/input/demo.jpg")

for name, url in sources:
    try:
        r = requests.get(url, headers=headers, timeout=20, allow_redirects=True)
        ctype = r.headers.get("content-type", "?")
        sz = len(r.content)
        print(f"{name}: HTTP {r.status_code}  {sz:,} bytes  {ctype}")
        if r.status_code == 200 and sz > 30000 and "image" in ctype:
            out.write_bytes(r.content)
            print(f"  --> Saved to {out}  ({sz:,} bytes)")
            sys.exit(0)
    except Exception as e:
        print(f"{name}: ERROR {e}")

print("All sources failed — keeping original demo.jpg")
