import urllib.request
import urllib.parse
import http.cookiejar
import json
import base64

def test_sso_live():
    cj = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(cj))

    # 1. Test initiating Google OAuth
    url = "https://cargoclear-app.web.app/api/auth/signin/google"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    
    # Custom redirect handler to not follow redirect to accounts.google.com
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    no_redirect_opener = urllib.request.build_opener(no_redirect_opener := urllib.request.HTTPCookieProcessor(cj), NoRedirect())

    try:
        resp = no_redirect_opener.open(req)
        status = resp.getcode()
        headers = resp.headers
    except urllib.error.HTTPError as e:
        status = e.code
        headers = e.headers

    print(f"Status: {status}")
    set_cookies = headers.get_all("Set-Cookie") or []
    print(f"Set-Cookie headers count: {len(set_cookies)}")
    found_session = False
    found_oauth_state = False
    for sc in set_cookies:
        name = sc.split("=")[0].strip()
        print(f"  -> Cookie: {name}")
        if name == "__session":
            found_session = True
            print(f"     __session value prefix: {sc[:40]}...")
        if name == "cargoclear_oauth_state":
            found_oauth_state = True

    assert not found_session, "FAIL: live OAuth initiation must not mint a session before Google verifies the user!"
    assert found_oauth_state, "FAIL: cargoclear_oauth_state not set!"

    loc = headers.get("Location")
    print(f"Redirect Location: {loc[:80]}...")
    parsed = urllib.parse.urlparse(loc)
    qs = urllib.parse.parse_qs(parsed.query)

    state = qs.get("state", [""])[0]
    print(f"State param received: {state[:40]}...")
    assert state, "FAIL: OAuth state is missing"
    payload_b64 = state

    # Pad base64url if needed
    padded = payload_b64 + "=" * ((4 - len(payload_b64) % 4) % 4)
    payload_json = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
    print(f"State decoded payload: nonce={payload_json.get('nonce')[:8]}..., returnTo={payload_json.get('returnTo')}, iat={payload_json.get('iat')}")

    # 2. Test callback security: Forged state should be rejected immediately
    tampered_url = "https://cargoclear-app.web.app/api/auth/callback/google?code=dummy_code&state=forged-state"
    tampered_req = urllib.request.Request(tampered_url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        t_resp = no_redirect_opener.open(tampered_req)
        t_status = t_resp.getcode()
        t_loc = t_resp.headers.get("Location")
    except urllib.error.HTTPError as e:
        t_status = e.code
        t_loc = e.headers.get("Location")

    print(f"Tampered state callback status: {t_status}, Location: {t_loc}")
    assert "error=invalid_oauth_state" in t_loc, f"Expected invalid_oauth_state, got {t_loc}"

    print("\n--- ALL CHECKS PASSED: Live Firebase Hosting Google SSO Ready ---")

if __name__ == "__main__":
    test_sso_live()
