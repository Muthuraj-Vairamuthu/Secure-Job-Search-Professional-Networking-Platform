import requests
import pyotp
import time

BASE_URL = "http://localhost:8000/api/v1"


def build_auth_headers(session_id, csrf_token, extra_headers=None):
    headers = {
        "Cookie": f"session_id={session_id}; csrf_token={csrf_token}",
        "X-CSRF-Token": csrf_token
    }
    if extra_headers:
        headers.update(extra_headers)
    return headers

def run_tests():
    print("starting testing...")
    email = "testuser@example.com"
    password = "SuperSecure123!"
    
    # 1. Signup Step 1
    print("Testing signup step 1...")
    r = requests.post(f"{BASE_URL}/auth/register", json={
        "email": email,
        "password": password,
        "role": "user",
        "name": "Test User"
    })
    res = r.json()
    assert res['status'] == 'pending_mfa_setup', f"Expected pending_mfa_setup, got {res}"
    
    context = res['context']
    totp_secret = res['mfa_secret_setup_key']
    totp = pyotp.TOTP(totp_secret)
    code = totp.now()
    
    # 2. Signup Step 2
    print("Testing signup step 2...")
    r = requests.post(f"{BASE_URL}/auth/register/verify", json={
        "context": context,
        "totp_code": code
    })
    res = r.json()
    assert res['status'] == 'success', f"Expected success, got {res}"

    verification_token = res.get('verification_token_preview')
    assert verification_token, f"Expected verification token preview, got {res}"

    print("Testing email verification...")
    r = requests.post(f"{BASE_URL}/auth/verify-email", json={
        "email": email,
        "token": verification_token
    })
    res = r.json()
    assert res['status'] == 'success', f"Expected success, got {res}"
    
    # 3. Login Step 1
    print("Testing login step 1...")
    r = requests.post(f"{BASE_URL}/auth/login", json={
        "email": email,
        "password": password
    })
    res = r.json()
    assert res['status'] == 'pending_mfa', f"Expected pending_mfa, got {res}"
    mfa_token = res['mfa_token']
    
    # wait to ensure different window for mfa
    print("Sleeping to avoid rate limit/mfa replay")
    time.sleep(31) 
    code = totp.now()
    
    # 4. Login Step 2
    print("Testing login step 2...")
    session = requests.Session()
    r = session.post(f"{BASE_URL}/auth/login/verify", json={
        "mfa_token": mfa_token,
        "totp_code": code
    })
    res = r.json()
    assert res['status'] == 'success', f"Expected success, got {res}"
    session_id = r.cookies.get('session_id')
    csrf_token = r.cookies.get('csrf_token')
    assert session_id, "Expected session_id cookie from login verify response"
    assert csrf_token, "Expected csrf_token cookie from login verify response"

    # 5. Upload Resume
    print("Testing resume upload...")
    with open("tests/test_resume.pdf", "wb") as f:
        f.write(b"%PDF-1.4 dummy pdf content")
    
    with open("tests/test_resume.pdf", "rb") as f:
        r = session.post(
            f"{BASE_URL}/users/resumes",
            files={"resume": f},
            headers=build_auth_headers(session_id, csrf_token)
        )
    res = r.json()
    assert res['status'] == 'success', f"Expected success, got {res}"
    
    print("All tests passed!")

if __name__ == "__main__":
    run_tests()
