import json
import os
import time
import urllib.request

BASE_URL = "https://cargoclear-app.web.app/api/proxy"
HEADERS = {
    "Cookie": "__session=mock-jwt-demo-cha@customs.com-LICENSED_CHA",
    "Content-Type": "application/json",
}


def main():
    print("=== Step 1: Create Case D Bundle ===")
    create_payload = {"reference": "CASE-D-TEST-LIVE", "destination_country": "IN"}
    req = urllib.request.Request(
        f"{BASE_URL}/bundles",
        data=json.dumps(create_payload).encode("utf-8"),
        headers=HEADERS,
        method="POST",
    )
    with urllib.request.urlopen(req) as resp:
        bundle = json.loads(resp.read().decode("utf-8"))
    bundle_id = bundle["id"]
    print(f"Created bundle: {bundle_id}")

    print("\n=== Step 2: Upload 4 Case D Documents ===")
    fixtures_dir = "fixtures/case_d"
    files = [
        "case_d_commercial_invoice.pdf",
        "case_d_bill_of_lading.pdf",
        "case_d_packing_list.pdf",
        "case_d_mtc_test_cert.pdf",
    ]

    for filename in files:
        filepath = os.path.join(fixtures_dir, filename)
        with open(filepath, "rb") as f:
            file_bytes = f.read()

        boundary = "----WebKitFormBoundary7MA4YWxkTrZu0gW"
        body = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
            f"Content-Type: application/pdf\r\n\r\n"
        ).encode("utf-8") + file_bytes + f"\r\n--{boundary}--\r\n".encode("utf-8")

        upload_headers = {
            "Cookie": "__session=mock-jwt-demo-cha@customs.com-LICENSED_CHA",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }

        upload_req = urllib.request.Request(
            f"{BASE_URL}/bundles/{bundle_id}/documents",
            data=body,
            headers=upload_headers,
            method="POST",
        )
        with urllib.request.urlopen(upload_req) as upload_resp:
            doc_resp = json.loads(upload_resp.read().decode("utf-8"))
            print(f"Uploaded {filename}: doc_id={doc_resp.get('document_id')}")

    print(f"\n=== Step 3: Trigger Live Pipeline Analysis on {bundle_id} ===")
    analyze_req = urllib.request.Request(
        f"{BASE_URL}/bundles/{bundle_id}/analyze",
        data=b"{}",
        headers=HEADERS,
        method="POST",
    )
    with urllib.request.urlopen(analyze_req) as resp:
        analyze_resp = json.loads(resp.read().decode("utf-8"))
        print("Analysis initiated:", analyze_resp)

    print("\n=== Step 4: Monitor Pipeline Progress ===")
    for attempt in range(1, 30):
        time.sleep(6)
        check_req = urllib.request.Request(f"{BASE_URL}/bundles/{bundle_id}", headers=HEADERS)
        try:
            with urllib.request.urlopen(check_req) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                status = data.get("status")
                print(f"Attempt {attempt} (t={attempt*6}s): Bundle Status = {status}")
                if status in ("READY_FOR_ADJUDICATION", "FAILED", "CONTRADICTION", "MATERIAL_CONTRADICTION", "MISSING_EVIDENCE"):
                    print("Reached terminal pipeline status:", status)
                    break
        except Exception as e:
            print(f"Attempt {attempt} check error: {e}")

    print("\n=== Step 5: Fetch Assessment & Validate Features ===")
    assess_req = urllib.request.Request(f"{BASE_URL}/bundles/{bundle_id}/assessment", headers=HEADERS)
    with urllib.request.urlopen(assess_req) as resp:
        assessment = json.loads(resp.read().decode("utf-8"))

    print(f"Status: {assessment.get('status')}")
    print(f"Total Checks: {len(assessment.get('checks', []))}")
    for c in assessment.get("checks", []):
        print(f"  [{c.get('severity')}] {c.get('check_id')}: {c.get('message')[:100]}...")

    print("\nValuation Summary:")
    val = assessment.get("valuation", {})
    print(f"  Transaction Value: {val.get('transaction_value')} {val.get('invoice_currency')}")
    print(f"  Assessable Value: {val.get('assessable_value')} {val.get('destination_currency')}")
    print(f"  Total Duty: {val.get('total_duty')} {val.get('destination_currency')}")
    for d in val.get("duties", []):
        print(f"    - {d.get('name')}: {d.get('rate_pct')}% -> {d.get('amount')}")

    print("\n=== Step 6: Test Declaration Pre-fill Pack ===")
    prefill_req = urllib.request.Request(f"{BASE_URL}/bundles/{bundle_id}/prefill", headers=HEADERS)
    with urllib.request.urlopen(prefill_req) as resp:
        prefill = json.loads(resp.read().decode("utf-8"))
    print(f"Prefill Banner: {prefill.get('banner')}")
    print(f"Prefill Lines Count: {len(prefill.get('lines', []))}")
    print(f"Prefill Parties: Exporter={prefill.get('parties', {}).get('exporter', {}).get('name')}, Importer={prefill.get('parties', {}).get('importer', {}).get('name')}")

    print("\n=== Step 7: Test Audit Chain Integrity ===")
    audit_req = urllib.request.Request(f"{BASE_URL}/bundles/{bundle_id}/audit", headers=HEADERS)
    with urllib.request.urlopen(audit_req) as resp:
        audit_data = json.loads(resp.read().decode("utf-8"))
    print(f"Audit Chain Verified: {audit_data.get('verified')}")
    print(f"Audit Events Total: {len(audit_data.get('events', []))}")


if __name__ == "__main__":
    main()
