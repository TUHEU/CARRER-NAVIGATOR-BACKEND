import os
import random
import string
from datetime import datetime, timedelta

from flask import Flask, jsonify, request
from flask_bcrypt import Bcrypt
from flask_jwt_extended import (
    JWTManager,
    create_access_token,
    create_refresh_token,
    get_jwt_identity,
    jwt_required,
)
import pymysql
import pymysql.cursors
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

# ──────────────────────────────────────────────────────────────────────────────
# App & extension setup
# ──────────────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET", "super-secret-key")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=1)
app.config["JWT_REFRESH_TOKEN_EXPIRES"] = timedelta(days=30)

bcrypt = Bcrypt(app)
jwt = JWTManager(app)

# ──────────────────────────────────────────────────────────────────────────────
# Database configuration
# ──────────────────────────────────────────────────────────────────────────────
DB_CONFIG = {
    "host":         os.getenv("DB_HOST",   "localhost"),
    "port":         int(os.getenv("DB_PORT", 3306)),
    "user":         os.getenv("DB_USER",   "root"),
    "password":     os.getenv("DB_PASS",   "Fahdil@1"),
    "db":           os.getenv("DB_NAME",   "career_navigator"),
    "charset":      "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
    "autocommit":  True,
}

# ──────────────────────────────────────────────────────────────────────────────
# Brevo (email) configuration
# ──────────────────────────────────────────────────────────────────────────────
BREVO_API_KEY      = os.getenv("BREVO_API_KEY")
BREVO_SENDER_NAME  = os.getenv("BREVO_SENDER_NAME", "Career Navigator")
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL", "nadaljunior999@gmail.com")

# ──────────────────────────────────────────────────────────────────────────────
# Helper utilities
# ──────────────────────────────────────────────────────────────────────────────
def get_db() -> pymysql.connections.Connection:
    """Return a new database connection."""
    return pymysql.connect(**DB_CONFIG)


def success(data=None, msg: str = "OK", status: int = 200):
    """Return a successful JSON response."""
    return jsonify({"success": True, "message": msg, "data": data}), status


def error(msg: str = "Error", status: int = 400):
    """Return an error JSON response."""
    return jsonify({"success": False, "message": msg, "data": None}), status


def generate_otp(length: int = 6) -> str:
    """Return a random numeric OTP string."""
    return "".join(random.choices(string.digits, k=length))


def send_verification_email(to_email: str, to_name: str, code: str) -> bool:
    """Send a verification OTP via Brevo transactional email. Returns True on success."""
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key["api-key"] = BREVO_API_KEY
    api = sib_api_v3_sdk.TransactionalEmailsApi(
        sib_api_v3_sdk.ApiClient(configuration)
    )
    html_content = f"""
    <html>
      <body style="font-family: Arial, sans-serif; background: #f4f4f4; padding: 30px;">
        <div style="max-width:480px; margin:auto; background:#fff; border-radius:12px; padding:32px;">
          <h2 style="color:#0A192F;">Career Navigator</h2>
          <p>Your email verification code is:</p>
          <div style="font-size:36px; font-weight:bold; letter-spacing:10px;
                      color:#00E5FF; text-align:center; padding:20px 0;">
            {code}
          </div>
          <p style="color:#888;">This code expires in <strong>10 minutes</strong>.</p>
          <p style="color:#888;">If you did not request this, please ignore this email.</p>
        </div>
      </body>
    </html>
    """
    email_obj = sib_api_v3_sdk.SendSmtpEmail(
        to=[{"email": to_email, "name": to_name}],
        sender={"email": BREVO_SENDER_EMAIL, "name": BREVO_SENDER_NAME},
        subject="Your Career Navigator Verification Code",
        html_content=html_content,
    )
    try:
        api.send_transac_email(email_obj)
        return True
    except ApiException as e:
        app.logger.error(f"Brevo error: {e}")
        return False


# ──────────────────────────────────────────────────────────────────────────────
# AUTH — Register
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/auth/register", methods=["POST"])
def register():
    body     = request.get_json(silent=True) or {}
    email    = (body.get("email",    "") or "").strip().lower()
    password = (body.get("password", ""))

    if not email or "@" not in email:
        return error("A valid email address is required.", 400)
    if not password or len(password) < 6:
        return error("Password must be at least 6 characters.", 400)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            # Reject duplicate emails
            cur.execute("SELECT id FROM users WHERE email = %s", (email,))
            if cur.fetchone():
                return error("An account with this email already exists.", 409)

            # Create user (unverified)
            pw_hash = bcrypt.generate_password_hash(password).decode("utf-8")
            cur.execute(
                "INSERT INTO users (email, password_hash, role, is_verified) "
                "VALUES (%s, %s, 'job_seeker', 0)",
                (email, pw_hash),
            )
            user_id = conn.insert_id()

            # Create companion job_seekers profile row
            cur.execute(
                "INSERT INTO job_seekers (user_id) VALUES (%s)", (user_id,)
            )

            # Generate and persist OTP
            code       = generate_otp()
            expires_at = datetime.utcnow() + timedelta(minutes=10)
            cur.execute(
                "INSERT INTO email_verification_codes "
                "(user_id, code, expires_at) VALUES (%s, %s, %s)",
                (user_id, code, expires_at),
            )

        # Send email outside the cursor block
        sent = send_verification_email(email, email, code)
        msg  = "Registration successful! Check your email for the verification code." \
               if sent else \
               "Account created, but we could not send the verification email. Use resend."
        return success({"user_id": user_id}, msg, 201)

    except Exception as e:
        app.logger.error(f"register error: {e}")
        return error("An unexpected error occurred. Please try again.", 500)
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# AUTH — Verify Email
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/auth/verify-email", methods=["POST"])
def verify_email():
    body  = request.get_json(silent=True) or {}
    email = (body.get("email", "") or "").strip().lower()
    code  = (body.get("code",  "") or "").strip()

    if not email or not code:
        return error("Email and code are required.", 400)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            # Look up the user
            cur.execute(
                "SELECT id, is_verified FROM users WHERE email = %s", (email,)
            )
            user = cur.fetchone()
            if not user:
                return error("No account found for this email.", 404)

            if user["is_verified"]:
                return error("This email is already verified. Please log in.", 400)

            user_id = user["id"]

            # Find a valid, unused OTP
            cur.execute(
                """
                SELECT id FROM email_verification_codes
                WHERE  user_id   = %s
                  AND  code      = %s
                  AND  used      = 0
                  AND  expires_at > UTC_TIMESTAMP()
                ORDER BY id DESC
                LIMIT 1
                """,
                (user_id, code),
            )
            otp_row = cur.fetchone()
            if not otp_row:
                return error("Invalid or expired verification code.", 400)

            # Mark OTP as used and verify the user in one transaction
            cur.execute(
                "UPDATE email_verification_codes SET used = 1 WHERE id = %s",
                (otp_row["id"],),
            )
            cur.execute(
                "UPDATE users SET is_verified = 1 WHERE id = %s", (user_id,)
            )

        # Issue JWT tokens so Flutter can proceed straight to profile setup
        access_token  = create_access_token(identity=str(user_id))
        refresh_token = create_refresh_token(identity=str(user_id))
        return success(
            {"access_token": access_token, "refresh_token": refresh_token},
            "Email verified successfully!",
        )

    except Exception as e:
        app.logger.error(f"verify_email error: {e}")
        return error("An unexpected error occurred. Please try again.", 500)
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# AUTH — Resend Verification Code
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/auth/resend-code", methods=["POST"])
def resend_code():
    body  = request.get_json(silent=True) or {}
    email = (body.get("email", "") or "").strip().lower()

    if not email:
        return error("Email is required.", 400)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, is_verified FROM users WHERE email = %s", (email,)
            )
            user = cur.fetchone()
            if not user:
                return error("No account found for this email.", 404)

            if user["is_verified"]:
                return error("This email is already verified. Please log in.", 400)

            user_id = user["id"]

            # Invalidate all previous unused codes for this user
            cur.execute(
                "UPDATE email_verification_codes SET used = 1 "
                "WHERE user_id = %s AND used = 0",
                (user_id,),
            )

            # Insert a fresh OTP
            code       = generate_otp()
            expires_at = datetime.utcnow() + timedelta(minutes=10)
            cur.execute(
                "INSERT INTO email_verification_codes "
                "(user_id, code, expires_at) VALUES (%s, %s, %s)",
                (user_id, code, expires_at),
            )

        sent = send_verification_email(email, email, code)
        if sent:
            return success(msg="A new verification code has been sent to your email.")
        return error("Failed to send the email. Please try again shortly.", 500)

    except Exception as e:
        app.logger.error(f"resend_code error: {e}")
        return error("An unexpected error occurred. Please try again.", 500)
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# AUTH — Login
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/auth/login", methods=["POST"])
def login():
    body     = request.get_json(silent=True) or {}
    email    = (body.get("email",    "") or "").strip().lower()
    password = (body.get("password", ""))

    if not email or not password:
        return error("Email and password are required.", 400)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, password_hash, is_verified, is_active "
                "FROM users WHERE email = %s",
                (email,),
            )
            user = cur.fetchone()

        # Use a generic message to avoid user-enumeration attacks
        if not user or not bcrypt.check_password_hash(user["password_hash"], password):
            return error("Invalid email or password.", 401)

        if not user["is_verified"]:
            return error(
                "Your email is not verified yet. "
                "Please check your inbox or request a new code.",
                403,
            )

        if not user["is_active"]:
            return error("This account has been deactivated. Contact support.", 403)

        access_token  = create_access_token(identity=str(user["id"]))
        refresh_token = create_refresh_token(identity=str(user["id"]))
        return success(
            {"access_token": access_token, "refresh_token": refresh_token},
            "Login successful!",
        )

    except Exception as e:
        app.logger.error(f"login error: {e}")
        return error("An unexpected error occurred. Please try again.", 500)
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# PROFILE — Get current user
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/profile/me", methods=["GET"])
@jwt_required()
def get_profile():
    user_id = int(get_jwt_identity())
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT
                    u.id, u.email, u.full_name, u.date_of_birth,
                    u.profile_picture, u.role, u.is_verified,
                    js.headline, js.bio, js.phone, js.location,
                    js.years_of_experience, js.current_job_title,
                    js.desired_job_title, js.skills, js.resume_url,
                    js.linkedin_url, js.github_url, js.portfolio_url,
                    js.availability
                FROM users u
                LEFT JOIN job_seekers js ON js.user_id = u.id
                WHERE u.id = %s
                """,
                (user_id,),
            )
            profile = cur.fetchone()

        if not profile:
            return error("User not found.", 404)

        # Serialize date for JSON
        if profile.get("date_of_birth"):
            profile["date_of_birth"] = str(profile["date_of_birth"])

        return success(profile, "Profile loaded.")

    except Exception as e:
        app.logger.error(f"get_profile error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# PROFILE — Setup (name + date of birth after first login)
# ──────────────────────────────────────────────────────────────────────────────
@app.route("/profile/setup", methods=["PUT"])
@jwt_required()
def setup_profile():
    user_id  = int(get_jwt_identity())
    body     = request.get_json(silent=True) or {}
    full_name = (body.get("full_name", "") or "").strip()
    dob       = (body.get("date_of_birth", "") or "").strip()

    if not full_name:
        return error("Full name is required.", 400)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            if dob:
                cur.execute(
                    "UPDATE users SET full_name = %s, date_of_birth = %s WHERE id = %s",
                    (full_name, dob, user_id),
                )
            else:
                cur.execute(
                    "UPDATE users SET full_name = %s WHERE id = %s",
                    (full_name, user_id),
                )

        return success(msg="Profile updated successfully.")

    except Exception as e:
        app.logger.error(f"setup_profile error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


# ──────────────────────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("--- Initializing Career Navigator API ---")

    try:
        test_conn = get_db()
        test_conn.close()
        print("✅  Database : connected to 'career_navigator'")
    except Exception as e:
        print(f"❌  Database : {e}")

    if BREVO_API_KEY and BREVO_API_KEY.startswith("xkeysib-"):
        print("✅  Brevo     : API key detected")
    else:
        print("⚠️   Brevo     : API key missing or invalid")

    app.run(debug=True, host="0.0.0.0", port=5000)