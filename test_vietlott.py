import requests
from bs4 import BeautifulSoup
import re

headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36',
    'Accept-Language': 'vi-VN,vi;q=0.9',
}
r = requests.get('https://vietlott.vn/vi/tr%C3%B2-ch%C6%A1i/bingo18/ket-qua-trung-thuong', headers=headers, timeout=15)
print('Status:', r.status_code)
print('Length:', len(r.text))

# Lưu HTML ra file để xem
with open('vietlott_debug.html', 'w', encoding='utf-8') as f:
    f.write(r.text)
print('Da luu HTML vao vietlott_debug.html')

# Tìm tất cả số từ 1-18 xuất hiện trong các tag
soup = BeautifulSoup(r.text, 'lxml')

# In tất cả class trong trang
all_classes = set()
for tag in soup.find_all(True):
    for c in tag.get('class', []):
        all_classes.add(c)
print('\nTong so class:', len(all_classes))
print('All classes (20 dau):', sorted(list(all_classes))[:20])

# Tìm số 1-18 trong span/div
print('\nCac the chua so 1-18:')
for tag in soup.find_all(['span', 'div', 'td', 'li']):
    text = tag.get_text(strip=True)
    if text.isdigit() and 1 <= int(text) <= 18:
        print(f'  <{tag.name} class="{tag.get("class", [])}"> {text} </{tag.name}>')

# Tìm draw number
print('\nTim ky so:')
for pattern in [r'(\d{5,7})', r'Ky\s*#?(\d+)', r'draw.*?(\d{5,7})']:
    matches = re.findall(pattern, r.text[:3000])
    if matches:
        print(f'Pattern {pattern}: {matches[:5]}')

# In 2000 chars giữa trang
mid = len(r.text) // 2
print('\nGiua trang HTML:')
print(r.text[mid:mid+1000])
