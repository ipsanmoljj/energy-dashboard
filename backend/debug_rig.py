"""
Run this once to see the raw HTML from AOGR.
Paste the output here so we can fix the regex in baker_hughes_fetcher.py
"""
import requests, re

HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

url = "https://www.aogr.com/web-exclusives/us-rig-count/2026"
r = requests.get(url, headers=HEADERS, timeout=20)
print("Status:", r.status_code)
print("\n--- First 300 chars of any <tr> blocks ---")
html = r.text

# Print every table row so we can see the actual format
rows = re.findall(r'<tr[^>]*>.*?</tr>', html, re.DOTALL)
print(f"Found {len(rows)} <tr> blocks")
for i, row in enumerate(rows[:15]):
    # Strip tags for readability
    text = re.sub(r'<[^>]+>', ' ', row).strip()
    text = re.sub(r'\s+', ' ', text)
    print(f"Row {i}: {text[:120]}")

print("\n--- Any lines containing 3-digit numbers (rig counts) ---")
for line in html.splitlines():
    if re.search(r'\b[3-7]\d{2}\b', line) and ('oil' in line.lower() or 'rig' in line.lower() or 'gas' in line.lower()):
        print(repr(line[:150]))
