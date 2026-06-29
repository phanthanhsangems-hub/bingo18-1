import requests
import json

headers_base = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'vi-VN,vi;q=0.9',
    'Referer': 'https://vietlott.vn/',
}

# Test 1: AjaxPro API
print("=== Test AjaxPro API ===")
url = "https://vietlott.vn/ajaxpro/Vietlott.PlugIn.WebParts.GameBingo18Box,Vietlott.PlugIn.ashx"
methods = ["GetGameDrawDetails", "GetBingo18Result", "GetLatestResult", "GetResult"]
for method in methods:
    try:
        h = {**headers_base, 'X-AjaxPro-Method': method, 'Content-Type': 'text/plain; charset=utf-8'}
        r = requests.post(url, headers=h, data='{"gameDrawId":0}', timeout=10)
        print(f"Method {method}: {r.status_code} - {r.text[:200]}")
    except Exception as e:
        print(f"Method {method}: ERROR {e}")

# Test 2: URL mới không dấu
print("\n=== Test URL khong dau ===")
urls = [
    "https://vietlott.vn/vi/tro-choi/bingo18/ket-qua-trung-thuong",
    "https://vietlott.vn/vi/trochoi/bingo18/ket-qua-trung-thuong",
    "https://vietlott.vn/vi/games/bingo18/results",
    "https://vietlott.vn/api/bingo18/latest",
]
for url in urls:
    try:
        r = requests.get(url, headers=headers_base, timeout=10)
        print(f"GET {url}: {r.status_code} len={len(r.text)}")
        if r.status_code == 200 and len(r.text) > 5000:
            print(f"  -> Co noi dung! Luu vao debug2.html")
            with open(f'debug_{url.split("/")[-1]}.html', 'w', encoding='utf-8') as f:
                f.write(r.text)
    except Exception as e:
        print(f"GET {url}: ERROR {e}")

# Test 3: API JSON endpoint
print("\n=== Test API JSON ===")
api_urls = [
    "https://vietlott.vn/api/gameresult/bingo18",
    "https://api.vietlott.vn/api/gameresult?gameType=bingo18",
    "https://vietlott.vn/api/v1/bingo18/result",
]
for url in api_urls:
    try:
        h = {**headers_base, 'Accept': 'application/json'}
        r = requests.get(url, headers=h, timeout=10)
        print(f"GET {url}: {r.status_code} - {r.text[:200]}")
    except Exception as e:
        print(f"GET {url}: ERROR {e}")
