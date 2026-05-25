import requests
lines = requests.get('https://ir.eia.gov/wpsr/table4.csv', headers={'User-Agent': 'Mozilla/5.0'}).text.splitlines()
for l in lines:
    if 'Cush' in l:
        parts = [p.strip().strip('"') for p in l.split(',')]
        print(repr(parts[:4]))

lines2 = requests.get('https://ir.eia.gov/wpsr/table1.csv', headers={'User-Agent': 'Mozilla/5.0'}).text.splitlines()
for l in lines2:
    if '(1)' in l and 'Production' in l:
        parts = [p.strip().strip('"') for p in l.split(',')]
        print("PRODUCTION:", repr(parts[:5]))
    if '(31)' in l:
        parts = [p.strip().strip('"') for p in l.split(',')]
        print("GAS DEMAND:", repr(parts[:5]))
    if '(33)' in l:
        parts = [p.strip().strip('"') for p in l.split(',')]
        print("DIST DEMAND:", repr(parts[:5]))
    if '(8)' in l and 'Import' in l:
        parts = [p.strip().strip('"') for p in l.split(',')]
        print("IMPORTS:", repr(parts[:5]))
