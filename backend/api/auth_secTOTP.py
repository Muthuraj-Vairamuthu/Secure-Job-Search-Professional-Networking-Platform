import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional

# Security Libraries
# Install via: pip install argon2-cffi pyotp cryptography
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError
import pyotp
from cryptography.fernet import Fernet

# ==========================================
# 1. SECURITY CONFIGURATION & DATABASE SETUP
# ==========================================
# Argon2id is the OWASP recommended hashing algorithm.
# It is resistant to both GPU cracking and side-channel attacks.
ph = PasswordHasher(
    time_cost=3,          # Number of iterations
    memory_cost=65536,    # 64MB memory usage (Memory-hard)
    parallelism=4,        # Parallel execution threads
    hash_len=32,          # Hash length
    salt_len=16           # Salt length (prevents rainbow table attacks)
)

# In a deployed environment, this would be an environment variable (e.g., from os.environ)
# pointing to your production database (PostgreSQL, MySQL, etc.) or your database connection pool.
DB_NAME = "secure_auth.db"

import hashlib
import os

# [THREAT MITIGATION: Hardcoded Secrets]
# In production, this key MUST be loaded from an environment variable!
# Used to encrypt TOTP secrets at rest in our database so DB dumps don't compromise MFA.
# We persist the key to a file so encrypted data survives across restarts.
DATA_DIR_AUTH = os.path.abspath(os.path.join(os.path.dirname(__file__), '../data'))
KEY_FILE = os.path.join(DATA_DIR_AUTH, "encryption.key")
if os.path.exists(KEY_FILE):
    with open(KEY_FILE, "rb") as f:
        ENCRYPTION_KEY = f.read()
else:
    ENCRYPTION_KEY = Fernet.generate_key()
    with open(KEY_FILE, "wb") as f:
        f.write(ENCRYPTION_KEY)
cipher_suite = Fernet(ENCRYPTION_KEY)

# NOTE: The database schema (users, verification_tokens, sessions, audit_logs) 
# is assumed to be deployed and managed by a separate db migration tool 
# (like Alembic, Flyway, or raw SQL deployment scripts) rather than initialized here.


# ==========================================
# 2. SECURE DATABASE ABSTRACTIONS
# ==========================================
def db_execute(query: str, parameters: tuple = ()) -> None:
    """
    [THREAT MITIGATION: SQL Injection]
    Executes a write query securely using parameterized inputs.
    """
    # SQLite uses '?' for parameterized queries. We map '%s' to '?' for ease of use.
    sqlite_query = query.replace("%s", "?")
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute(sqlite_query, parameters)
        conn.commit()

def db_fetch_user(email: str) -> Optional[Dict[str, Any]]:
    """
    [THREAT MITIGATION: SQL Injection]
    Retrieves user data securely from the database using parameterized queries.
    """
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row # Returns dict-like objects based on columns
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE email=?", (email,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None

def db_fetch_all(query: str, parameters: tuple = ()) -> list:
    """Helper method for reading bulk data safely."""
    sqlite_query = query.replace("%s", "?")
    with sqlite3.connect(DB_NAME) as conn:
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute(sqlite_query, parameters)
        return [dict(row) for row in cursor.fetchall()]


# ==========================================
# 3. MODULAR SECURITY FUNCTIONS
# ==========================================
def validate_inputs(email: str, password: str) -> bool:
    """
    [THREAT MITIGATION: Buffer Overflows, XSS, Weak Credentials]
    Server-side validation enforcing boundaries and complexity.
    """
    # 1. Strict length limits (prevents DoS via massive payloads)
    if not (5 <= len(email) <= 255) or not (12 <= len(password) <= 128):
        return False
        
    # 2. Email format validation (implicitly rejects raw HTML/JS tags)
    if not re.match(r"^[\w\.-]+@[\w\.-]+\.\w+$", email):
        return False
        
    # 3. Strong Password Policy
    if not re.search(r"[A-Z]", password): return False           # Uppercase
    if not re.search(r"[a-z]", password): return False           # Lowercase
    if not re.search(r"\d", password): return False              # Number
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>]", password): return False # Special Char
    
    return True

def log_audit_trail(email: str, ip_address: str, event: str):
    """
    [THREAT MITIGATION: Lack of Non-repudiation]
    Maintains a secure audit trail for forensic analysis.
    """
    from core.db import insert_audit_log_entry
    insert_audit_log_entry(email, event, ip_address)

def check_rate_limit(ip_address: str, email: str) -> bool:
    """
    [THREAT MITIGATION: Brute Force, Credential Stuffing]
    Checks if an IP or Account is temporarily locked with exponential backoff.
    """
    # 1. Check Account-Based Locking
    user = db_fetch_user(email)
    if user and user.get("locked_until"):
        locked_until_dt = datetime.fromisoformat(user["locked_until"])
        if datetime.now(timezone.utc) < locked_until_dt:
            # Account is still locked
            return False

    # 2. Check IP-Based Throttling (e.g. > 20 failed attempts in 30 mins)
    thirty_mins_ago = (datetime.now(timezone.utc) - timedelta(minutes=30)).isoformat()
    recent_ip_failures = db_fetch_all(
        "SELECT COUNT(*) as count FROM audit_logs WHERE ip_address=%s AND event=%s AND timestamp >= %s",
        (ip_address, "FAILED_LOGIN_ATTEMPT", thirty_mins_ago)
    )
    if recent_ip_failures and recent_ip_failures[0]["count"] >= 20:
        return False

    return True

def handle_failed_login(email: str, ip_address: str):
    """
    [THREAT MITIGATION: Brute Force]
    Increments failed attempts and enforces exponential account locking.
    """
    log_audit_trail(email, ip_address, "FAILED_LOGIN_ATTEMPT")
    user = db_fetch_user(email)
    
    if user:
        new_fails = user["failed_attempts"] + 1
        locked_until = None
        
        # Exponential backoff rules
        if new_fails >= 20:
            # Permanent review (Lock for ~100 years)
            locked_until = (datetime.now(timezone.utc) + timedelta(days=36500)).isoformat()
        elif new_fails >= 10:
            # 30 minute lock
            locked_until = (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat()
        elif new_fails >= 5:
            # 5 minute lock
            locked_until = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
            
        db_execute(
            "UPDATE users SET failed_attempts=%s, locked_until=%s WHERE email=%s",
            (new_fails, locked_until, email)
        )


def encrypt_data(data: str) -> str:
    """Encrypts sensitive data for database storage (e.g. TOTP secrets)."""
    return cipher_suite.encrypt(data.encode()).decode()

def decrypt_data(encrypted_data: str) -> str:
    """Decrypts sensitive data from database."""
    return cipher_suite.decrypt(encrypted_data.encode()).decode()


# ==========================================
# 4. MFA ABSTRACTIONS
# ==========================================
def generate_mfa_secret() -> str:
    """Generates a secure, random base32 TOTP secret."""
    return pyotp.random_base32()

def generate_backup_codes(count: int = 10) -> list:
    """Generates secure, one-time use backup codes."""
    return [secrets.token_hex(4) for _ in range(count)]


# ==========================================
# 5. CORE CONTROLLERS
# ==========================================
def signup_step_1(email: str, password: str, ip_address: str = "127.0.0.1") -> Dict[str, Any]:
    """
    Secure Registration Step 1: Initialize User Context and generate TOTP.
    Does NOT save to DB yet. Prevents ghost accounts if user abandons QR scan.
    """
    if not validate_inputs(email, password):
        return {"status": "error", "message": "Invalid input format or password policy not met."}

    existing_user = db_fetch_user(email)
    if existing_user:
        log_audit_trail(email, ip_address, "REGISTRATION_ATTEMPT_EXISTING_USER")
        return {
            "status": "error", 
            "message": "User already exists." # In a real app, fake success to avoid enumeration
        }

    # Generate setup constraints
    password_hash = ph.hash(password)
    mfa_secret_raw = pyotp.random_base32()
    
    # We return the context so the caller (CLI/Frontend) can ask the user for the OTP
    # and then pass it to Step 2 to permanently save.
    return {
        "status": "pending_mfa_setup",
        "message": "Password accepted. Please scan the Setup Key and verify an OTP to finalize account creation.",
        "mfa_secret_setup_key": mfa_secret_raw,
        "context": {
            "email": email,
            "password_hash": password_hash,
            "mfa_secret_raw": mfa_secret_raw
        }
    }

def signup_step_2(context: Dict[str, str], raw_totp_code: str, ip_address: str = "127.0.0.1") -> Dict[str, str]:
    """
    Secure Registration Step 2: Validate the OTP. If valid, commit user to database.
    """
    mfa_secret_raw = context.get("mfa_secret_raw", "")
    email = context.get("email", "")
    password_hash = context.get("password_hash", "")
    
    # 1. Verify the code the user typed matches the secret we generated for them
    totp = pyotp.TOTP(mfa_secret_raw)
    if not totp.verify(raw_totp_code):
        return {"status": "error", "message": "Invalid TOTP Code. Account creation aborted."}
        
    # 2. OTP is valid! Encrypt the secret and permanently save the user.
    mfa_secret_encrypted = encrypt_data(mfa_secret_raw)
    
    try:
        db_execute(
            "INSERT INTO users (email, password_hash, is_verified, mfa_enabled, mfa_secret) VALUES (%s, %s, %s, %s, %s)",
            (email, password_hash, False, 1, mfa_secret_encrypted)
        )
        
        # Save verification token for email validation
        raw_token = secrets.token_urlsafe(32)
        expiry = datetime.now(timezone.utc) + timedelta(minutes=15)
        db_execute(
            "INSERT INTO verification_tokens (email, token_hash, expires_at) VALUES (%s, %s, %s)",
            (email, ph.hash(raw_token), expiry.isoformat())
        )
        
        log_audit_trail(email, ip_address, "SUCCESSFUL_REGISTRATION")
        return {
            "status": "success",
            "message": "Account created and MFA securely bound. Email verification is required before login.",
            "email_verification_token": raw_token
        }
        
    except sqlite3.IntegrityError:
        return {"status": "error", "message": "User already exists or database constraint failed."}


def login_step_1(email: str, password: str, ip_address: str = "127.0.0.1") -> Dict[str, Any]:
    """
    Secure Login Controller Step 1: Credential Verification.
    If MFA is enabled, returns a pending state requiring Step 2.
    """
    # Basic sanity check to prevent Denial of Service via massive strings
    if len(email) > 255 or len(password) > 128:
        return {"status": "error", "message": "Invalid credentials"}

    # Step 2: Rate Limiting
    if not check_rate_limit(ip_address, email):
        log_audit_trail(email, ip_address, "RATE_LIMIT_TRIGGERED")
        return {"status": "error", "message": "Account locked due to multiple failed attempts."}

    user_record = db_fetch_user(email)
    
    if not user_record:
        # [CRITICAL TRICK]: Prevent Timing Attacks!
        # If the user doesn't exist, we must still perform a slow hash equivalent 
        # to what Argon2 takes, otherwise attackers can scan IPs for existing users based on response time latency.
        try:
            ph.verify(ph.hash("dummy_password_for_timing"), password)
        except VerifyMismatchError:
            pass
            
        handle_failed_login(email, ip_address)
        return {"status": "error", "message": "Invalid credentials"} # Generic response

    # Step 1: Constant-Time Password Comparison via Argon2
    try:
        ph.verify(user_record['password_hash'], password)
        
        # Proactive Security: Upgrade hash automatically if server config changes in future
        if ph.check_needs_rehash(user_record['password_hash']):
            db_execute("UPDATE users SET password_hash=%s WHERE email=%s", (ph.hash(password), email))
            
    except VerifyMismatchError:
        handle_failed_login(email, ip_address)
        return {"status": "error", "message": "Invalid credentials"}

    # Final Security Checks
    if not user_record.get('is_verified', False):
        log_audit_trail(email, ip_address, "LOGIN_BLOCKED_EMAIL_UNVERIFIED")
        return {"status": "error", "message": "Please verify your email before logging in."}

    # Successful Step 1 Auth
    db_execute("UPDATE users SET failed_attempts=0, locked_until=NULL WHERE email=%s", (email,))
    
    # Check if MFA is enabled
    # We simulate reading user columns: mfa_enabled
    # If the user has a "mfa_enabled" attribute set to True, redirect to Step 2
    if user_record.get('mfa_enabled', False):
        log_audit_trail(email, ip_address, "SUCCESSFUL_PASSWORD_AUTH_PENDING_MFA")
        # Step 3: Multi-Stage Authentication state
        # Create a short-lived, permissionless token just for completing 2FA
        mfa_token = secrets.token_urlsafe(32)
        token_hash = hashlib.sha256(mfa_token.encode()).hexdigest()
        
        expires_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        db_execute(
            "INSERT INTO mfa_pending_sessions (token_hash, email, expires_at) VALUES (%s, %s, %s)",
            (token_hash, email, expires_at)
        )
        return {
            "status": "pending_mfa",
            "message": "Password verified. Please submit your TOTP code.",
            "mfa_token": mfa_token
        }
    
    log_audit_trail(email, ip_address, "SUCCESSFUL_LOGIN")
    
    # Step 4: Secure Session Management (No MFA scenario)
    session_id = secrets.token_urlsafe(64) 
    db_execute(
        "INSERT INTO sessions (session_hash, user_id, role, created_at, expires_at) VALUES (%s, %s, %s, %s, %s)",
        (hashlib.sha256(session_id.encode()).hexdigest(), email, 'user', datetime.now(timezone.utc).isoformat(), (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat())
    )
    
    return {
        "status": "success",
        "message": "Login successful",
        "session_token": session_id 
    }

def login_step_2(mfa_token: str, totp_code: str, ip_address: str = "127.0.0.1") -> Dict[str, Any]:
    """
    Secure Login Controller Step 2: TOTP Verification.
    """
    # 1. Fetch the short-lived MFA pending session to securely map the token back to the email
    token_hash = hashlib.sha256(mfa_token.encode()).hexdigest()
    
    mfa_session = db_fetch_all("SELECT * FROM mfa_pending_sessions WHERE token_hash=?", (token_hash,))
    if not mfa_session:
        return {"status": "error", "message": "Invalid or expired MFA session. Please restart login."}
        
    mfa_session_record = mfa_session[0]
    email = mfa_session_record['email']
    
    expires_at = datetime.fromisoformat(mfa_session_record['expires_at'])
    if datetime.now(timezone.utc) > expires_at:
        db_execute("DELETE FROM mfa_pending_sessions WHERE token_hash=?", (token_hash,))
        return {"status": "error", "message": "MFA session timed out. Please restart login."}
    
    # Rate limit check for TOTP attempts to prevent 6-digit brute force
    if not check_rate_limit(ip_address, email):
        log_audit_trail(email, ip_address, "MFA_RATE_LIMIT_TRIGGERED")
        return {"status": "error", "message": "Account locked due to multiple failed MFA attempts."}

    user = db_fetch_user(email)
    if not user or not user.get('mfa_secret'):
        return {"status": "error", "message": "MFA not configured."}

    # Step 4: OTP Verification Phase
    decrypted_secret = decrypt_data(user['mfa_secret'])
    totp = pyotp.TOTP(decrypted_secret)
    
    # Step 6: Prevent Replay Attacks
    # Ensure current time window hasn't been used yet
    last_used = user.get('last_mfa_window', 0)
    current_window = int(datetime.now(timezone.utc).timestamp() / 30)

    # Note: `verify` checks the current window and slightly older windows for clock drift.
    # But because pyotp doesn't explicitly return the matched timestamp window, 
    # we enforce checking `current_window > last_used` natively to strictly prevent replay
    if current_window <= last_used:
        handle_failed_login(email, ip_address)
        return {"status": "error", "message": "OTP has already been used. Wait for a new code."}
    
    if not totp.verify(totp_code):
        handle_failed_login(email, ip_address)
        return {"status": "error", "message": "Invalid OTP code."}

    # Success: Create the ultimate active session
    db_execute("UPDATE users SET failed_attempts=0, locked_until=NULL, last_mfa_window=%s WHERE email=%s", (current_window, email))
    log_audit_trail(email, ip_address, "SUCCESSFUL_MFA_LOGIN")
    
    # Delete the short-lived MFA pending token now that they are authenticated
    token_hash = hashlib.sha256(mfa_token.encode()).hexdigest()
    db_execute("DELETE FROM mfa_pending_sessions WHERE token_hash=%s", (token_hash,))
    
    session_id = secrets.token_urlsafe(64) 
    
    db_execute(
        "INSERT INTO sessions (session_hash, user_id, role, created_at, expires_at) VALUES (%s, %s, %s, %s, %s)",
        (hashlib.sha256(session_id.encode()).hexdigest(), email, 'user', datetime.now(timezone.utc).isoformat(), (datetime.now(timezone.utc) + timedelta(minutes=30)).isoformat())
    )
    
    return {
        "status": "success",
        "message": "Login completely successful.",
        "session_token": session_id 
    }


def verify_email_token(email: str, raw_token: str, ip_address: str = "127.0.0.1") -> Dict[str, Any]:
    """
    Validate a pending email-verification token and mark the account as verified.
    Tokens are stored hashed, so we check each active candidate with Argon2 verify.
    """
    if not email or not raw_token:
        return {"status": "error", "message": "Email and verification token are required."}

    user = db_fetch_user(email)
    if not user:
        return {"status": "error", "message": "User not found."}
    if user.get('is_verified', False):
        return {"status": "success", "message": "Email is already verified."}

    now = datetime.now(timezone.utc)
    candidates = db_fetch_all(
        "SELECT id, token_hash, expires_at FROM verification_tokens WHERE email=%s",
        (email,)
    )

    matched_token_id = None
    expired_token_ids = []
    for token_row in candidates:
        expires_at = datetime.fromisoformat(token_row['expires_at'])
        if now > expires_at:
            expired_token_ids.append(token_row['id'])
            continue

        try:
            if ph.verify(token_row['token_hash'], raw_token):
                matched_token_id = token_row['id']
                break
        except VerifyMismatchError:
            continue

    for token_id in expired_token_ids:
        db_execute("DELETE FROM verification_tokens WHERE id=%s", (token_id,))

    if matched_token_id is None:
        log_audit_trail(email, ip_address, "EMAIL_VERIFICATION_FAILED")
        return {"status": "error", "message": "Invalid or expired verification token."}

    db_execute("UPDATE users SET is_verified=%s WHERE email=%s", (True, email))
    db_execute("DELETE FROM verification_tokens WHERE email=%s", (email,))
    log_audit_trail(email, ip_address, "EMAIL_VERIFIED")
    return {"status": "success", "message": "Email verified successfully."}

# Standalone enroll_mfa() has been removed because it is now forced at signup!


def setup_demo_db():
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT UNIQUE NOT NULL,
                password_hash TEXT NOT NULL,
                is_verified BOOLEAN NOT NULL DEFAULT 0,
                failed_attempts INTEGER NOT NULL DEFAULT 0,
                locked_until TIMESTAMP,
                mfa_enabled BOOLEAN NOT NULL DEFAULT 0,
                mfa_secret TEXT,
                last_mfa_window INTEGER DEFAULT 0
            )
        ''')
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS mfa_pending_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token_hash TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL,
                expires_at TIMESTAMP NOT NULL
            )
        ''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS sessions (id INTEGER PRIMARY KEY AUTOINCREMENT, session_hash TEXT NOT NULL UNIQUE, email TEXT NOT NULL, expires_at TIMESTAMP NOT NULL)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS verification_tokens (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL, token_hash TEXT NOT NULL, expires_at TIMESTAMP NOT NULL)''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS audit_logs (id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL, ip_address TEXT NOT NULL, event TEXT NOT NULL, timestamp TIMESTAMP NOT NULL)''')
        conn.commit()

if __name__ == "__main__":
    setup_demo_db()
    
    import getpass
    
    print("=" * 60)
    print("✨ SECURE CYBERSECURITY AUTHENTICATION CLI ✨")
    print("=" * 60)
    print("This is an interactive simulation of the secure backend API.")
    print("A fresh local database has been initialized.")
    
    while True:
        print("\n" + "-"*30)
        print("1. Sign Up")
        print("2. Log In")
        print("3. Exit")
        choice = input("Select an option: ").strip()
        
        if choice == "3":
            print("Exiting...")
            break
            
        elif choice == "1":
            print("\n--- REGISTRATION ---")
            email = input("Email: ").strip()
            password = getpass.getpass("Password (e.g., SuperSecure123!): ")
            
            res = signup(email, password)
            print("Response:", res)
            
        elif choice == "2":
            print("\n--- LOGIN ---")
            email = input("Email: ").strip()
            password = getpass.getpass("Password: ")
            
            # Step 1
            res1 = login_step_1(email, password)
            
            if res1.get("status") == "success":
                print("✅ Successfully logged in!")
                print("Session Token:", res1.get("session_token"))
                
                # Ask if they want to enroll in MFA since they are logged in
                enroll_choice = input("\nWould you like to enroll in MFA (TOTP)? (y/n): ").strip().lower()
                if enroll_choice == 'y':
                    print("\n--- MFA ENROLLMENT ---")
                    # Generate a secret for them to add to their app
                    new_secret = pyotp.random_base32()
                    print(f"Your new TOTP Secret is: {new_secret}")
                    print("Normally, you'd scan a QR code. For this CLI, add this secret to Google Authenticator or an OTP app.")
                    
                    user_otp = input("Enter the 6-digit code from your app to confirm enrollment: ").strip()
                    # In a real app, the server would temporarily cache `new_secret` for this user.
                    # Here we pass it through explicitly.
                    
                    # We inject the new secret temporarily into the enroll function logic for the CLI
                    # (Mocking the stored pending_secret)
                    def cli_enroll_mfa(email: str, raw_totp_code: str, secret_to_test: str) -> Dict[str, str]:
                        user = db_fetch_user(email)
                        if not user: return {"status": "error", "message": "User not found."}
                        if user.get("mfa_enabled"): return {"status": "error", "message": "MFA is already enabled."}
                        
                        totp = pyotp.TOTP(secret_to_test)
                        if not totp.verify(raw_totp_code):
                            return {"status": "error", "message": "Invalid code. MFA has not been enabled to prevent lockout."}
                            
                        encrypted_secret = encrypt_data(secret_to_test)
                        backup_codes = generate_backup_codes(10)
                        db_execute("UPDATE users SET mfa_enabled=1, mfa_secret=%s WHERE email=%s", (encrypted_secret, email))
                        return {"status": "success", "message": "MFA successfully enabled.", "backup_codes": backup_codes}
                        
                    mfa_res = cli_enroll_mfa(email, user_otp, new_secret)
                    print("Response:", mfa_res)
                    
            elif res1.get("status") == "pending_mfa":
                print("🔒 Password accepted. MFA Required.")
                mfa_token = res1.get("mfa_token")
                
                user_otp = input("Enter your 6-digit TOTP code: ").strip()
                res2 = login_step_2(mfa_token, user_otp)
                
                if res2.get("status") == "success":
                    print("✅ Successfully logged in with MFA!")
                    print("Session Token:", res2.get("session_token"))
                else:
                    print("❌ MFA Failed:", res2)
                    
            else:
                print("❌ Login Failed:", res1)
