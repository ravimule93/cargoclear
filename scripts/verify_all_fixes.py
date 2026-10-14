import urllib.request
import json

headers = {"Cookie": "__session=mock-jwt-demo-cha@customs.com-LICENSED_CHA"}

# 1. Test Stream immediate first byte response on analyzed bundle
print("=== 1. Testing /stream endpoint on analyzed bundle ===")
stream_url = "https://cargoclear-app.web.app/api/proxy/bundles/bnd-b91c2577aeb3/stream"
req = urllib.request.Request(stream_url, headers=headers)
try:
    with urllib.request.urlopen(req, timeout=10) as resp:
        print("Stream Status:", resp.status)
        print("Content-Type:", resp.headers.get("Content-Type"))
        line1 = resp.readline().decode("utf-8").strip()
        line2 = resp.readline().decode("utf-8").strip()
        print("Line 1:", line1)
        print("Line 2:", line2[:120])
        print("SUCCESS: Stream responded immediately with 200 OK (no 503 first byte timeout)!")
except Exception as e:
    print("Stream error:", e)

# 2. Test Stream on a brand new empty bundle with no analysis yet
print("\n=== 2. Testing /stream on newly created empty bundle ===")
create_req = urllib.request.Request(
    "https://cargoclear-app.web.app/api/proxy/bundles",
    data=json.dumps({"reference": "TEST-STREAM-EMPTY"}).encode("utf-8"),
    headers={**headers, "Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(create_req) as bresp:
    new_bundle = json.loads(bresp.read().decode("utf-8"))
new_id = new_bundle["id"]
print("Created empty bundle:", new_id)

empty_stream_req = urllib.request.Request(f"https://cargoclear-app.web.app/api/proxy/bundles/{new_id}/stream", headers=headers)
try:
    with urllib.request.urlopen(empty_stream_req, timeout=10) as resp:
        print("Empty Bundle Stream Status:", resp.status)
        line1 = resp.readline().decode("utf-8").strip()
        line2 = resp.readline().decode("utf-8").strip()
        print("Line 1:", line1)
        print("Line 2:", line2[:120])
        print("SUCCESS: Empty bundle stream connected immediately without timeout!")
except Exception as e:
    print("Empty stream error:", e)

# 3. Test Landing Page unauthenticated view
print("\n=== 3. Testing Landing Page when Unauthenticated ===")
anon_req = urllib.request.Request("https://cargoclear-app.web.app/")
with urllib.request.urlopen(anon_req) as resp:
    html = resp.read().decode("utf-8")
    has_new_empty_button = "New empty bundle" in html
    has_sso = "Commercial Single Sign-On" in html
    print("Contains 'New empty bundle' button for anonymous user:", has_new_empty_button)
    print("Contains 'Commercial Single Sign-On':", has_sso)

# 4. Test Google OAuth redirect URI
print("\n=== 4. Testing Google OAuth Redirect URI ===")
oauth_req = urllib.request.Request("https://cargoclear-app.web.app/api/auth/signin/google")


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


opener = urllib.request.build_opener(NoRedirect)
try:
    opener.open(oauth_req)
except urllib.error.HTTPError as e:
    loc = e.headers.get("Location", "")
    print("OAuth redirect status:", e.code)
    for part in loc.split("&"):
        if "redirect_uri=" in part:
            print("redirect_uri:", urllib.parse.unquote(part))
