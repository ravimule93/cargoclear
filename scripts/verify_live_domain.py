import urllib.request
import re

print("=== Checking Homepage (https://cargoclear-app.web.app/) ===")
req = urllib.request.Request("https://cargoclear-app.web.app/")
with urllib.request.urlopen(req) as resp:
    print("Status:", resp.status)
    print("Cache-Control:", resp.headers.get("Cache-Control"))
    html = resp.read().decode("utf-8")

matches = re.findall(r'(?:src|href)="(/_next/[^"]+)"', html)
print(f"Total _next assets referenced: {len(matches)}")

errs = []
for path in matches:
    asset_url = "https://cargoclear-app.web.app" + path
    try:
        with urllib.request.urlopen(asset_url) as aresp:
            if aresp.status != 200:
                errs.append((path, aresp.status))
    except Exception as e:
        errs.append((path, str(e)))

print(f"Failed chunks count: {len(errs)}")
if not errs:
    print("SUCCESS: 100% of homepage JS/CSS chunks loaded with HTTP 200!")
print("Contains 'Live GCP':", "Live GCP" in html)

print("\n=== Checking Workbench (https://cargoclear-app.web.app/workbench/bnd-b91c2577aeb3) ===")
wb_req = urllib.request.Request(
    "https://cargoclear-app.web.app/workbench/bnd-b91c2577aeb3",
    headers={"Cookie": "__session=mock-jwt-demo-cha@customs.com-LICENSED_CHA"}
)
with urllib.request.urlopen(wb_req) as resp:
    print("Workbench Status:", resp.status)
    print("Workbench Cache-Control:", resp.headers.get("Cache-Control"))
    wb_html = resp.read().decode("utf-8")

wb_matches = re.findall(r'(?:src|href)="(/_next/[^"]+)"', wb_html)
print(f"Total _next assets in workbench: {len(wb_matches)}")
wb_errs = []
for path in wb_matches:
    asset_url = "https://cargoclear-app.web.app" + path
    try:
        with urllib.request.urlopen(asset_url) as aresp:
            if aresp.status != 200:
                wb_errs.append((path, aresp.status))
    except Exception as e:
        wb_errs.append((path, str(e)))

print(f"Workbench Failed chunks count: {len(wb_errs)}")
if not wb_errs:
    print("SUCCESS: 100% of workbench JS/CSS chunks loaded with HTTP 200!")
print("Workbench Contains 'Live GCP':", "Live GCP" in wb_html)
