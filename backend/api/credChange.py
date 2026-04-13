"""
credChange.py — Credential Change Module
Imports the shared auth library and adds a secure change_password flow.

Flow:
  1. Verify email + current password (Argon2id)
  2. Verify current TOTP code (anti-replay enforced)
  3. Validate new password against policy
  4. Re-hash and commit to DB
"""

import getpass
import pyotp
from datetime import datetime, timezone, timedelta
from typing import Dict, Any

from auth_secTOTP import (
    ph, db_fetch_user, db_execute, decrypt_data,
    validate_inputs, log_audit_trail, check_rate_limit, handle_failed_login,
    setup_demo_db
)
from argon2.exceptions import VerifyMismatchError


# ==========================================
# CORE FUNCTION: change_password
# ==========================================
def change_password(
    email: str,
    current_password: str,
    totp_code: str,
    new_password: str,
    ip_address: str = "127.0.0.1"
) -> Dict[str, Any]:
    """
    Securely changes a user's password.

    Guards:
      - Rate limiting (brute force protection)
      - Argon2id verification of current password
      - TOTP verification (with replay attack prevention)
      - New password policy validation
      - Re-hash with Argon2id before storing
    """

    # 1. Basic length sanity check (DoS protection)
    if len(email) > 255 or len(current_password) > 128:
        return {"status": "error", "message": "Invalid input."}

    # 2. Rate limit check
    if not check_rate_limit(ip_address, email):
        log_audit_trail(email, ip_address, "RATE_LIMIT_TRIGGERED_CRED_CHANGE")
        return {"status": "error", "message": "Account locked. Try again later."}

    # 3. Fetch user
    user = db_fetch_user(email)
    if not user:
        # Timing-safe dummy verify to prevent user enumeration
        try:
            ph.verify(ph.hash("dummy"), current_password)
        except VerifyMismatchError:
            pass
        return {"status": "error", "message": "Invalid credentials."}

    # 4. Verify current password (constant-time Argon2id)
    try:
        ph.verify(user["password_hash"], current_password)
    except VerifyMismatchError:
        handle_failed_login(email, ip_address)
        return {"status": "error", "message": "Invalid credentials."}

    # 5. Verify TOTP (MFA must be enabled for all users)
    if not user.get("mfa_enabled") or not user.get("mfa_secret"):
        return {"status": "error", "message": "MFA not configured on this account."}

    decrypted_secret = decrypt_data(user["mfa_secret"])
    totp = pyotp.TOTP(decrypted_secret)

    # Replay attack prevention
    last_used = user.get("last_mfa_window", 0) or 0
    current_window = int(datetime.now(timezone.utc).timestamp() / 30)

    if current_window <= last_used:
        return {"status": "error", "message": "OTP already used. Wait for the next 30-second window."}

    if not totp.verify(totp_code):
        handle_failed_login(email, ip_address)
        return {"status": "error", "message": "Invalid TOTP code."}

    # 6. Validate new password policy
    # We reuse validate_inputs but only care about the password portion
    dummy_email = "a@b.com"  # placeholder to pass email check
    if not validate_inputs(dummy_email, new_password):
        return {
            "status": "error",
            "message": (
                "New password must be 12–128 characters and contain "
                "uppercase, lowercase, a number, and a special character."
            )
        }

    # 7. Prevent reuse of the same password
    try:
        ph.verify(user["password_hash"], new_password)
        return {"status": "error", "message": "New password must differ from your current password."}
    except VerifyMismatchError:
        pass  # Good — passwords are different

    # 8. Hash and commit new password; update replay window
    new_hash = ph.hash(new_password)
    db_execute(
        "UPDATE users SET password_hash=%s, failed_attempts=0, locked_until=NULL, last_mfa_window=%s WHERE email=%s",
        (new_hash, current_window, email)
    )
    log_audit_trail(email, ip_address, "SUCCESSFUL_PASSWORD_CHANGE")

    return {"status": "success", "message": "Password changed successfully."}


# ==========================================
# INTERACTIVE CLI
# ==========================================
def main():
    setup_demo_db()

    print("=" * 60)
    print("🔐 CREDENTIAL CHANGE CLI")
    print("=" * 60)
    print("Change your password with full MFA verification.\n")

    while True:
        print("\n" + "-" * 40)
        print("1. 🔑 Change Password")
        print("2. 🚪 Exit")
        choice = input("\nSelect an option (1-2): ").strip()

        if choice == "2":
            print("Goodbye!")
            break

        elif choice == "1":
            print("\n--- 🔑 CHANGE PASSWORD ---")
            email = input("Email: ").strip()
            current_pw = getpass.getpass("Current Password: ")
            totp_code = input("TOTP Code (from authenticator app): ").strip()
            new_pw = getpass.getpass("New Password: ")
            confirm_pw = getpass.getpass("Confirm New Password: ")

            if new_pw != confirm_pw:
                print("\n❌ Passwords do not match.")
                continue

            result = change_password(email, current_pw, totp_code, new_pw)

            if result["status"] == "success":
                print("\n✅", result["message"])
            else:
                print("\n❌ FAILED:", result["message"])

        else:
            print("Invalid option.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nExiting. Goodbye!")
