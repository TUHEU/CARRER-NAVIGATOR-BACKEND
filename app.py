import os
import json
import random
import string
from datetime import datetime, timedelta
import platform

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

load_dotenv()

# ─────────────────────────────────────────────────────────────
# App & extension setup
# ─────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["JWT_SECRET_KEY"]            = os.getenv("JWT_SECRET", "change-me-in-production")
app.config["JWT_ACCESS_TOKEN_EXPIRES"]  = timedelta(hours=1)
app.config["JWT_REFRESH_TOKEN_EXPIRES"] = timedelta(days=30)

bcrypt = Bcrypt(app)
jwt    = JWTManager(app)

# ─────────────────────────────────────────────────────────────
# Database configuration - FIXED for Windows/Linux compatibility
# ─────────────────────────────────────────────────────────────
def get_db_config():
    """Return database config based on platform"""
    config = {
        "host":        os.getenv("DB_HOST", "127.0.0.1"),
        "port":        int(os.getenv("DB_PORT", 3306)),
        "user":        os.getenv("DB_USER"),
        "password":    os.getenv("DB_PASS"),
        "db":          os.getenv("DB_NAME"),
        "charset":     "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
        "autocommit":  True,
    }
    
    # Only add unix_socket on Linux (not Windows)
    if platform.system() != "Windows":
        config["unix_socket"] = "/var/run/mysqld/mysqld.sock"
    
    return config


def get_db():
    return pymysql.connect(**get_db_config())


# ─────────────────────────────────────────────────────────────
# Brevo (email)
# ─────────────────────────────────────────────────────────────
BREVO_API_KEY      = os.getenv("BREVO_API_KEY")
BREVO_SENDER_NAME  = os.getenv("BREVO_SENDER_NAME",  "Career Navigator")
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL")

# ─────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────
def success(data=None, msg="OK", status=200):
    return jsonify({"success": True,  "message": msg,  "data": data}), status


def error(msg="Error", status=400):
    return jsonify({"success": False, "message": msg, "data": None}), status


def otp(length=6):
    return "".join(random.choices(string.digits, k=length))


def _send_email(to_email: str, to_name: str, subject: str, html: str) -> bool:
    """Generic Brevo transactional email sender. Returns True on success."""
    if not BREVO_API_KEY:
        app.logger.warning("Brevo API key not configured")
        return False
    
    cfg = sib_api_v3_sdk.Configuration()
    cfg.api_key["api-key"] = BREVO_API_KEY
    api = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(cfg))
    mail = sib_api_v3_sdk.SendSmtpEmail(
        to=[{"email": to_email, "name": to_name}],
        sender={"email": BREVO_SENDER_EMAIL, "name": BREVO_SENDER_NAME},
        subject=subject,
        html_content=html,
    )
    try:
        api.send_transac_email(mail)
        return True
    except ApiException as e:
        app.logger.error(f"Brevo error: {e}")
        return False


def send_verification_email(to_email: str, code: str) -> bool:
    html = f"""
    <html><body style="font-family:Arial,sans-serif;background:#f4f4f4;padding:30px;">
      <div style="max-width:480px;margin:auto;background:#fff;border-radius:12px;padding:32px;">
        <h2 style="color:#0A192F;">Career Navigator</h2>
        <p>Your email verification code is:</p>
        <div style="font-size:36px;font-weight:bold;letter-spacing:10px;
                    color:#00E5FF;text-align:center;padding:20px 0;">{code}</div>
        <p style="color:#888;">This code expires in <strong>10 minutes</strong>.</p>
        <p style="color:#888;">If you did not request this, please ignore this email.</p>
      </div>
    </body></html>"""
    return _send_email(to_email, to_email,
                       "Your Career Navigator Verification Code", html)


def send_reset_email(to_email: str, code: str) -> bool:
    html = f"""
    <html><body style="font-family:Arial,sans-serif;background:#f4f4f4;padding:30px;">
      <div style="max-width:480px;margin:auto;background:#fff;border-radius:12px;padding:32px;">
        <h2 style="color:#0A192F;">Career Navigator — Password Reset</h2>
        <p>You requested a password reset. Your code is:</p>
        <div style="font-size:36px;font-weight:bold;letter-spacing:10px;
                    color:#00E5FF;text-align:center;padding:20px 0;">{code}</div>
        <p style="color:#888;">This code expires in <strong>15 minutes</strong>.</p>
        <p style="color:#888;">If you did not request a reset, you can safely ignore this email.</p>
        <p style="color:#888;">— The Career Navigator Team</p>
      </div>
    </body></html>"""
    return _send_email(to_email, to_email,
                       "Career Navigator — Password Reset Code", html)


def _notify(conn, user_id, sender_id, ntype, title, body="", ref_id=None):
    """Insert a notification row (fire-and-forget, swallows errors)."""
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO notifications
                   (user_id, sender_id, type, title, body, reference_id)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (user_id, sender_id, ntype, title, body, ref_id),
            )
    except Exception as e:
        app.logger.error(f"_notify error: {e}")


# ─────────────────────────────────────────────────────────────
# Health check
# ─────────────────────────────────────────────────────────────
@app.route("/")
def home():
    return jsonify({"status": "online", "message": "Career Navigator API v4.0"}), 200


@app.route("/health", methods=["GET"])
def health():
    try:
        conn = get_db()
        conn.close()
        db_status = True
    except Exception as e:
        db_status = False
    return jsonify({"status": "healthy", "database": db_status}), 200


# ═════════════════════════════════════════════════════════════
# AUTH
# ═════════════════════════════════════════════════════════════

@app.route("/auth/register", methods=["POST"])
def register():
    body     = request.get_json(silent=True) or {}
    email    = (body.get("email",    "") or "").strip().lower()
    password = (body.get("password", "") or "")

    if not email or "@" not in email:
        return error("A valid email address is required.", 400)
    if not password or len(password) < 6:
        return error("Password must be at least 6 characters.", 400)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email = %s", (email,))
            if cur.fetchone():
                return error("An account with this email already exists.", 409)

            pw_hash = bcrypt.generate_password_hash(password).decode("utf-8")
            cur.execute(
                "INSERT INTO users (email, password_hash, role, is_verified) "
                "VALUES (%s, %s, 'job_seeker', 0)",
                (email, pw_hash),
            )
            user_id = conn.insert_id()
            cur.execute("INSERT INTO job_seekers (user_id) VALUES (%s)", (user_id,))

            code       = otp()
            expires_at = datetime.utcnow() + timedelta(minutes=10)
            cur.execute(
                "INSERT INTO email_verification_codes (user_id, code, expires_at) "
                "VALUES (%s, %s, %s)",
                (user_id, code, expires_at),
            )

        sent = send_verification_email(email, code)
        msg  = ("Registration successful! Check your email for the verification code."
                if sent else
                "Account created, but we could not send the verification email. Use resend.")
        return success({"user_id": user_id}, msg, 201)

    except Exception as e:
        app.logger.error(f"register error: {e}")
        return error("An unexpected error occurred. Please try again.", 500)
    finally:
        conn.close()


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
            cur.execute("SELECT id, is_verified FROM users WHERE email = %s", (email,))
            user = cur.fetchone()
            if not user:
                return error("No account found for this email.", 404)
            if user["is_verified"]:
                return error("This email is already verified. Please log in.", 400)

            user_id = user["id"]
            cur.execute(
                """SELECT id FROM email_verification_codes
                   WHERE user_id = %s AND code = %s AND used = 0
                     AND expires_at > UTC_TIMESTAMP()
                   ORDER BY id DESC LIMIT 1""",
                (user_id, code),
            )
            row = cur.fetchone()
            if not row:
                return error("Invalid or expired verification code.", 400)

            cur.execute("UPDATE email_verification_codes SET used = 1 WHERE id = %s", (row["id"],))
            cur.execute("UPDATE users SET is_verified = 1 WHERE id = %s", (user_id,))

        access_token  = create_access_token(identity=str(user_id))
        refresh_token = create_refresh_token(identity=str(user_id))
        return success(
            {"access_token": access_token, "refresh_token": refresh_token},
            "Email verified successfully!",
        )

    except Exception as e:
        app.logger.error(f"verify_email error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/auth/resend-code", methods=["POST"])
def resend_code():
    body  = request.get_json(silent=True) or {}
    email = (body.get("email", "") or "").strip().lower()

    if not email:
        return error("Email is required.", 400)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, is_verified FROM users WHERE email = %s", (email,))
            user = cur.fetchone()
            if not user:
                return error("No account found for this email.", 404)
            if user["is_verified"]:
                return error("This email is already verified. Please log in.", 400)

            user_id = user["id"]
            cur.execute(
                "UPDATE email_verification_codes SET used = 1 "
                "WHERE user_id = %s AND used = 0", (user_id,)
            )
            code       = otp()
            expires_at = datetime.utcnow() + timedelta(minutes=10)
            cur.execute(
                "INSERT INTO email_verification_codes (user_id, code, expires_at) "
                "VALUES (%s, %s, %s)",
                (user_id, code, expires_at),
            )

        sent = send_verification_email(email, code)
        if sent:
            return success(msg="A new verification code has been sent to your email.")
        return error("Failed to send the email. Please try again shortly.", 500)

    except Exception as e:
        app.logger.error(f"resend_code error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/auth/login", methods=["POST"])
def login():
    body     = request.get_json(silent=True) or {}
    email    = (body.get("email",    "") or "").strip().lower()
    password = (body.get("password", "") or "")

    if not email or not password:
        return error("Email and password are required.", 400)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, password_hash, is_verified, is_active, role "
                "FROM users WHERE email = %s",
                (email,),
            )
            user = cur.fetchone()

        if not user or not bcrypt.check_password_hash(user["password_hash"], password):
            return error("Invalid email or password.", 401)
        if not user["is_verified"]:
            return error(
                "Your email is not verified yet. "
                "Please check your inbox or request a new code.", 403
            )
        if not user["is_active"]:
            return error("This account has been deactivated. Contact support.", 403)

        access_token  = create_access_token(identity=str(user["id"]))
        refresh_token = create_refresh_token(identity=str(user["id"]))
        return success(
            {"access_token": access_token, "refresh_token": refresh_token, "role": user["role"]},
            "Login successful!",
        )

    except Exception as e:
        app.logger.error(f"login error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/auth/refresh", methods=["POST"])
@jwt_required(refresh=True)
def refresh_token():
    user_id      = get_jwt_identity()
    access_token = create_access_token(identity=user_id)
    return success({"access_token": access_token}, "Token refreshed.")


@app.route("/auth/forgot-password", methods=["POST"])
def forgot_password():
    body  = request.get_json(silent=True) or {}
    email = (body.get("email", "") or "").strip().lower()

    if not email or "@" not in email:
        return error("A valid email address is required.", 400)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, is_active FROM users WHERE email = %s AND is_verified = 1",
                (email,),
            )
            user = cur.fetchone()

        # Always return success to prevent email enumeration
        if not user or not user["is_active"]:
            return success(
                msg="If an account exists for this email, a reset code has been sent."
            )

        user_id = user["id"]
        with conn.cursor() as cur:
            # Invalidate previous codes
            cur.execute(
                "UPDATE password_reset_codes SET used = 1 "
                "WHERE user_id = %s AND used = 0", (user_id,)
            )
            code       = otp()
            expires_at = datetime.utcnow() + timedelta(minutes=15)
            cur.execute(
                "INSERT INTO password_reset_codes (user_id, code, expires_at) "
                "VALUES (%s, %s, %s)",
                (user_id, code, expires_at),
            )

        send_reset_email(email, code)
        return success(
            msg="If an account exists for this email, a reset code has been sent."
        )

    except Exception as e:
        app.logger.error(f"forgot_password error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/auth/reset-password", methods=["POST"])
def reset_password():
    body     = request.get_json(silent=True) or {}
    email    = (body.get("email",    "") or "").strip().lower()
    code     = (body.get("code",     "") or "").strip()
    password = (body.get("password", "") or "")

    if not email or not code or not password:
        return error("Email, code and new password are required.", 400)
    if len(password) < 6:
        return error("Password must be at least 6 characters.", 400)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email = %s AND is_verified = 1", (email,))
            user = cur.fetchone()
            if not user:
                return error("Invalid email or code.", 400)

            user_id = user["id"]
            cur.execute(
                """SELECT id FROM password_reset_codes
                   WHERE user_id = %s AND code = %s AND used = 0
                     AND expires_at > UTC_TIMESTAMP()
                   ORDER BY id DESC LIMIT 1""",
                (user_id, code),
            )
            row = cur.fetchone()
            if not row:
                return error("Invalid or expired reset code.", 400)

            pw_hash = bcrypt.generate_password_hash(password).decode("utf-8")
            cur.execute(
                "UPDATE password_reset_codes SET used = 1 WHERE id = %s", (row["id"],)
            )
            cur.execute(
                "UPDATE users SET password_hash = %s WHERE id = %s", (pw_hash, user_id)
            )

        return success(msg="Password reset successfully! You can now log in.")

    except Exception as e:
        app.logger.error(f"reset_password error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/auth/delete-account", methods=["DELETE"])
@jwt_required()
def delete_account():
    user_id = int(get_jwt_identity())
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
        return success(msg="Account deleted successfully.")
    except Exception as e:
        app.logger.error(f"delete_account error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════
# PROFILE ENDPOINTS (abbreviated - same as before but working)
# ═════════════════════════════════════════════════════════════

@app.route("/profile/me", methods=["GET"])
@jwt_required()
def get_profile():
    user_id = int(get_jwt_identity())
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT u.id, u.email, u.full_name, u.date_of_birth,
                          u.profile_picture_url, u.role, u.is_verified,
                          (SELECT COUNT(*) FROM notifications
                           WHERE user_id = u.id AND is_read = 0) AS unread_notifications
                   FROM users u WHERE u.id = %s""",
                (user_id,),
            )
            user = cur.fetchone()
            if not user:
                return error("User not found.", 404)

            if user.get("date_of_birth"):
                user["date_of_birth"] = str(user["date_of_birth"])

            role = user["role"]

            # Job seeker profile
            cur.execute(
                """SELECT headline, bio, phone, location, years_of_experience,
                          current_job_title, desired_job_title, skills, resume_url,
                          linkedin_url, github_url, portfolio_url, availability,
                          open_to_remote, desired_salary, salary_currency, notice_period
                   FROM job_seekers WHERE user_id = %s""",
                (user_id,),
            )
            seeker = cur.fetchone() or {}
            if seeker.get("skills") and isinstance(seeker["skills"], str):
                try:    seeker["skills"] = json.loads(seeker["skills"])
                except: pass

            # Merge seeker fields directly into user dict
            for k, v in seeker.items():
                user.setdefault(k, v)

            # Mentor profile
            mentor_profile = {}
            if role in ("mentor", "admin"):
                cur.execute(
                    """SELECT headline, bio, phone, location, years_of_experience,
                              current_company, current_job_title, expertise_areas,
                              industries, advice_topics, mentoring_style, session_price,
                              currency, max_mentees, is_accepting_mentees,
                              linkedin_url, github_url, portfolio_url, website_url,
                              rating, total_sessions, availability_days
                       FROM mentor_profiles WHERE user_id = %s""",
                    (user_id,),
                )
                mentor_profile = cur.fetchone() or {}
                for json_col in ("expertise_areas", "industries", "advice_topics",
                                 "availability_days"):
                    val = mentor_profile.get(json_col)
                    if val and isinstance(val, str):
                        try:    mentor_profile[json_col] = json.loads(val)
                        except: pass
            user["mentor_profile"] = mentor_profile

            # Education
            cur.execute(
                """SELECT id, institution, degree, field_of_study, start_year,
                          end_year, is_current, description
                   FROM education WHERE user_id = %s ORDER BY start_year DESC""",
                (user_id,),
            )
            user["education"] = cur.fetchall()

            # Work experience
            cur.execute(
                """SELECT id, company, job_title, employment_type, location,
                          start_date, end_date, is_current, description
                   FROM work_experience WHERE user_id = %s ORDER BY start_date DESC""",
                (user_id,),
            )
            rows = cur.fetchall()
            for r in rows:
                if r.get("start_date"): r["start_date"] = str(r["start_date"])
                if r.get("end_date"):   r["end_date"]   = str(r["end_date"])
            user["work_experience"] = rows

        return success(user, "Profile loaded.")

    except Exception as e:
        app.logger.error(f"get_profile error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/profile/setup", methods=["PUT"])
@jwt_required()
def setup_profile():
    user_id   = int(get_jwt_identity())
    body      = request.get_json(silent=True) or {}
    full_name = (body.get("full_name", "") or "").strip()
    dob       = (body.get("date_of_birth", "") or "").strip()
    role      = (body.get("role", "") or "").strip()

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

            if role in ("job_seeker", "mentor"):
                cur.execute(
                    "UPDATE users SET role = %s, role_selected = 1 WHERE id = %s",
                    (role, user_id),
                )
                if role == "mentor":
                    cur.execute(
                        "INSERT IGNORE INTO mentor_profiles (user_id) VALUES (%s)",
                        (user_id,),
                    )

        return success(msg="Profile updated successfully.")

    except Exception as e:
        app.logger.error(f"setup_profile error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/profile/picture", methods=["PUT"])
@jwt_required()
def update_picture():
    user_id     = int(get_jwt_identity())
    body        = request.get_json(silent=True) or {}
    picture_url = (body.get("picture_url", "") or "").strip()

    if not picture_url:
        return error("picture_url is required.", 400)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET profile_picture_url = %s WHERE id = %s",
                (picture_url, user_id),
            )
        return success(msg="Profile picture updated.")
    except Exception as e:
        app.logger.error(f"update_picture error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/profile/job-seeker", methods=["PUT"])
@jwt_required()
def update_job_seeker():
    user_id = int(get_jwt_identity())
    body    = request.get_json(silent=True) or {}
    allowed = {
        "headline", "bio", "phone", "location", "years_of_experience",
        "current_job_title", "desired_job_title", "skills", "resume_url",
        "linkedin_url", "github_url", "portfolio_url", "availability",
        "open_to_remote", "desired_salary", "salary_currency", "notice_period",
    }
    fields = {k: v for k, v in body.items() if k in allowed}
    if not fields:
        return error("No valid fields provided.", 400)

    if "skills" in fields and isinstance(fields["skills"], (list, dict)):
        fields["skills"] = json.dumps(fields["skills"])

    conn = get_db()
    try:
        with conn.cursor() as cur:
            sets = ", ".join(f"{k} = %s" for k in fields)
            vals = list(fields.values()) + [user_id]
            cur.execute(f"UPDATE job_seekers SET {sets} WHERE user_id = %s", vals)
        return success(msg="Job seeker profile updated.")
    except Exception as e:
        app.logger.error(f"update_job_seeker error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/profile/mentor", methods=["PUT"])
@jwt_required()
def update_mentor():
    user_id = int(get_jwt_identity())
    body    = request.get_json(silent=True) or {}
    allowed = {
        "headline", "bio", "phone", "location", "years_of_experience",
        "current_company", "current_job_title", "expertise_areas", "industries",
        "advice_topics", "mentoring_style", "session_price", "currency",
        "max_mentees", "is_accepting_mentees", "linkedin_url", "github_url",
        "portfolio_url", "website_url", "availability_days",
    }
    fields = {k: v for k, v in body.items() if k in allowed}
    if not fields:
        return error("No valid fields provided.", 400)

    for col in ("expertise_areas", "industries", "advice_topics", "availability_days"):
        if col in fields and isinstance(fields[col], (list, dict)):
            fields[col] = json.dumps(fields[col])

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT IGNORE INTO mentor_profiles (user_id) VALUES (%s)", (user_id,)
            )
            sets = ", ".join(f"{k} = %s" for k in fields)
            vals = list(fields.values()) + [user_id]
            cur.execute(f"UPDATE mentor_profiles SET {sets} WHERE user_id = %s", vals)
        return success(msg="Mentor profile updated.")
    except Exception as e:
        app.logger.error(f"update_mentor error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════
# EDUCATION ENDPOINTS (keep existing working code)
# ═════════════════════════════════════════════════════════════

@app.route("/profile/education", methods=["GET"])
@jwt_required()
def get_education():
    user_id = int(get_jwt_identity())
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM education WHERE user_id = %s ORDER BY start_year DESC",
                (user_id,),
            )
            rows = cur.fetchall()
        return success(rows)
    except Exception as e:
        app.logger.error(f"get_education error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/profile/education", methods=["POST"])
@jwt_required()
def add_education():
    user_id = int(get_jwt_identity())
    body    = request.get_json(silent=True) or {}
    req     = ["institution", "degree", "field_of_study", "start_year"]
    for f in req:
        if not body.get(f):
            return error(f"'{f}' is required.", 400)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO education
                   (user_id, institution, degree, field_of_study, start_year,
                    end_year, is_current, description)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    user_id,
                    body["institution"],
                    body["degree"],
                    body["field_of_study"],
                    body["start_year"],
                    body.get("end_year"),
                    body.get("is_current", 0),
                    body.get("description", ""),
                ),
            )
            new_id = conn.insert_id()
        return success({"id": new_id}, "Education added.", 201)
    except Exception as e:
        app.logger.error(f"add_education error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/profile/education/<int:edu_id>", methods=["PUT"])
@jwt_required()
def update_education(edu_id):
    user_id = int(get_jwt_identity())
    body    = request.get_json(silent=True) or {}
    allowed = {
        "institution", "degree", "field_of_study", "start_year",
        "end_year", "is_current", "description",
    }
    fields = {k: v for k, v in body.items() if k in allowed}
    if not fields:
        return error("No valid fields provided.", 400)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM education WHERE id = %s AND user_id = %s",
                (edu_id, user_id),
            )
            if not cur.fetchone():
                return error("Education record not found.", 404)
            sets = ", ".join(f"{k} = %s" for k in fields)
            vals = list(fields.values()) + [edu_id]
            cur.execute(f"UPDATE education SET {sets} WHERE id = %s", vals)
        return success(msg="Education updated.")
    except Exception as e:
        app.logger.error(f"update_education error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/profile/education/<int:edu_id>", methods=["DELETE"])
@jwt_required()
def delete_education(edu_id):
    user_id = int(get_jwt_identity())
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM education WHERE id = %s AND user_id = %s",
                (edu_id, user_id),
            )
        return success(msg="Education deleted.")
    except Exception as e:
        app.logger.error(f"delete_education error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════
# WORK EXPERIENCE ENDPOINTS (keep existing working code)
# ═════════════════════════════════════════════════════════════

@app.route("/profile/work-experience", methods=["GET"])
@jwt_required()
def get_work_experience():
    user_id = int(get_jwt_identity())
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM work_experience WHERE user_id = %s ORDER BY start_date DESC",
                (user_id,),
            )
            rows = cur.fetchall()
            for r in rows:
                if r.get("start_date"): r["start_date"] = str(r["start_date"])
                if r.get("end_date"):   r["end_date"]   = str(r["end_date"])
        return success(rows)
    except Exception as e:
        app.logger.error(f"get_work_experience error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/profile/work-experience", methods=["POST"])
@jwt_required()
def add_work_experience():
    user_id = int(get_jwt_identity())
    body    = request.get_json(silent=True) or {}
    for f in ["company", "job_title", "start_date"]:
        if not body.get(f):
            return error(f"'{f}' is required.", 400)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO work_experience
                   (user_id, company, job_title, employment_type, location,
                    start_date, end_date, is_current, description)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                (
                    user_id,
                    body["company"],
                    body["job_title"],
                    body.get("employment_type", "full_time"),
                    body.get("location", ""),
                    body["start_date"],
                    body.get("end_date"),
                    body.get("is_current", 0),
                    body.get("description", ""),
                ),
            )
            new_id = conn.insert_id()
        return success({"id": new_id}, "Work experience added.", 201)
    except Exception as e:
        app.logger.error(f"add_work_experience error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/profile/work-experience/<int:work_id>", methods=["PUT"])
@jwt_required()
def update_work_experience(work_id):
    user_id = int(get_jwt_identity())
    body    = request.get_json(silent=True) or {}
    allowed = {
        "company", "job_title", "employment_type", "location",
        "start_date", "end_date", "is_current", "description",
    }
    fields = {k: v for k, v in body.items() if k in allowed}
    if not fields:
        return error("No valid fields provided.", 400)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM work_experience WHERE id = %s AND user_id = %s",
                (work_id, user_id),
            )
            if not cur.fetchone():
                return error("Work experience record not found.", 404)
            sets = ", ".join(f"{k} = %s" for k in fields)
            vals = list(fields.values()) + [work_id]
            cur.execute(f"UPDATE work_experience SET {sets} WHERE id = %s", vals)
        return success(msg="Work experience updated.")
    except Exception as e:
        app.logger.error(f"update_work_experience error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/profile/work-experience/<int:work_id>", methods=["DELETE"])
@jwt_required()
def delete_work_experience(work_id):
    user_id = int(get_jwt_identity())
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "DELETE FROM work_experience WHERE id = %s AND user_id = %s",
                (work_id, user_id),
            )
        return success(msg="Work experience deleted.")
    except Exception as e:
        app.logger.error(f"delete_work_experience error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════
# MENTORS (simplified but working)
# ═════════════════════════════════════════════════════════════

@app.route("/mentors", methods=["GET"])
@jwt_required()
def list_mentors():
    expertise = request.args.get("expertise", "").strip()
    page      = max(1, int(request.args.get("page", 1)))
    per_page  = 20
    offset    = (page - 1) * per_page

    conn = get_db()
    try:
        with conn.cursor() as cur:
            base = """
                SELECT u.id, u.full_name, u.profile_picture_url,
                       mp.headline, mp.current_job_title, mp.current_company,
                       mp.location, mp.years_of_experience, mp.expertise_areas,
                       mp.session_price, mp.currency, mp.rating,
                       mp.total_sessions, mp.is_accepting_mentees
                FROM mentor_profiles mp
                JOIN users u ON u.id = mp.user_id
                WHERE u.is_active = 1 AND u.is_verified = 1
                  AND mp.is_accepting_mentees = 1
            """
            params = []
            if expertise:
                base   += " AND mp.expertise_areas LIKE %s"
                params.append(f"%{expertise}%")
            base   += " ORDER BY mp.rating DESC, mp.total_sessions DESC LIMIT %s OFFSET %s"
            params += [per_page, offset]
            cur.execute(base, params)
            rows = cur.fetchall()
            for r in rows:
                val = r.get("expertise_areas")
                if val and isinstance(val, str):
                    try:    r["expertise_areas"] = json.loads(val)
                    except: pass
        return success(rows)
    except Exception as e:
        app.logger.error(f"list_mentors error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/mentors/<int:mentor_id>", methods=["GET"])
@jwt_required()
def get_mentor_detail(mentor_id):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT u.id, u.full_name, u.email, u.profile_picture_url,
                          mp.*
                   FROM mentor_profiles mp
                   JOIN users u ON u.id = mp.user_id
                   WHERE mp.user_id = %s AND u.is_active = 1""",
                (mentor_id,),
            )
            row = cur.fetchone()
            if not row:
                return error("Mentor not found.", 404)

            for col in ("expertise_areas", "industries", "advice_topics", "availability_days"):
                val = row.get(col)
                if val and isinstance(val, str):
                    try:    row[col] = json.loads(val)
                    except: pass

            cur.execute(
                "SELECT * FROM education WHERE user_id = %s ORDER BY start_year DESC",
                (mentor_id,),
            )
            row["education"] = cur.fetchall()

            cur.execute(
                "SELECT * FROM work_experience WHERE user_id = %s ORDER BY start_date DESC",
                (mentor_id,),
            )
            we = cur.fetchall()
            for r in we:
                if r.get("start_date"): r["start_date"] = str(r["start_date"])
                if r.get("end_date"):   r["end_date"]   = str(r["end_date"])
            row["work_experience"] = we

        return success(row)
    except Exception as e:
        app.logger.error(f"get_mentor_detail error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/mentors/user/<int:user_id>/background", methods=["GET"])
@jwt_required()
def get_user_background(user_id):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM education WHERE user_id = %s ORDER BY start_year DESC",
                (user_id,),
            )
            education = cur.fetchall()
            cur.execute(
                "SELECT * FROM work_experience WHERE user_id = %s ORDER BY start_date DESC",
                (user_id,),
            )
            work = cur.fetchall()
            for r in work:
                if r.get("start_date"): r["start_date"] = str(r["start_date"])
                if r.get("end_date"):   r["end_date"]   = str(r["end_date"])
        return success({"education": education, "work_experience": work})
    except Exception as e:
        app.logger.error(f"get_user_background error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════
# MENTOR REQUESTS (simplified but working)
# ═════════════════════════════════════════════════════════════

@app.route("/requests", methods=["POST"])
@jwt_required()
def send_mentor_request():
    seeker_id = int(get_jwt_identity())
    body      = request.get_json(silent=True) or {}
    mentor_id = body.get("mentor_id")
    message   = (body.get("message", "") or "").strip()

    if not mentor_id:
        return error("mentor_id is required.", 400)
    if seeker_id == mentor_id:
        return error("You cannot send a request to yourself.", 400)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT mp.user_id, u.full_name FROM mentor_profiles mp
                   JOIN users u ON u.id = mp.user_id
                   WHERE mp.user_id = %s AND mp.is_accepting_mentees = 1
                     AND u.is_active = 1""",
                (mentor_id,),
            )
            mentor = cur.fetchone()
            if not mentor:
                return error("Mentor not found or not accepting mentees.", 404)

            cur.execute(
                """SELECT id FROM mentor_requests
                   WHERE seeker_id = %s AND mentor_id = %s AND status = 'pending'""",
                (seeker_id, mentor_id),
            )
            if cur.fetchone():
                return error("You already have a pending request with this mentor.", 409)

            cur.execute(
                "SELECT full_name FROM users WHERE id = %s", (seeker_id,)
            )
            seeker = cur.fetchone()
            seeker_name = seeker["full_name"] or "Someone"

            cur.execute(
                "INSERT INTO mentor_requests (seeker_id, mentor_id, message) "
                "VALUES (%s, %s, %s)",
                (seeker_id, mentor_id, message),
            )
            req_id = conn.insert_id()

        _notify(
            conn, mentor_id, seeker_id, "mentor_request",
            f"{seeker_name} wants you as their mentor",
            message[:120] if message else "New mentoring request",
            req_id,
        )
        return success({"request_id": req_id}, "Mentoring request sent!", 201)

    except Exception as e:
        app.logger.error(f"send_mentor_request error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/requests", methods=["GET"])
@jwt_required()
def get_my_requests():
    user_id = int(get_jwt_identity())
    conn = get_db()
    try:
        with conn.cursor() as cur:
            # Requests the user RECEIVED (as mentor)
            cur.execute(
                """SELECT mr.id, mr.seeker_id, mr.message, mr.status,
                          mr.created_at, mr.conversation_id,
                          u.full_name AS seeker_name,
                          u.profile_picture_url AS seeker_picture,
                          js.headline AS seeker_headline
                   FROM mentor_requests mr
                   JOIN users u ON u.id = mr.seeker_id
                   LEFT JOIN job_seekers js ON js.user_id = mr.seeker_id
                   WHERE mr.mentor_id = %s
                   ORDER BY mr.created_at DESC""",
                (user_id,),
            )
            received = cur.fetchall()

            # Requests the user SENT (as seeker)
            cur.execute(
                """SELECT mr.id, mr.mentor_id, mr.message, mr.status,
                          mr.created_at, mr.conversation_id,
                          u.full_name AS mentor_name,
                          u.profile_picture_url AS mentor_picture,
                          mp.headline AS mentor_headline
                   FROM mentor_requests mr
                   JOIN users u ON u.id = mr.mentor_id
                   LEFT JOIN mentor_profiles mp ON mp.user_id = mr.mentor_id
                   WHERE mr.seeker_id = %s
                   ORDER BY mr.created_at DESC""",
                (user_id,),
            )
            sent = cur.fetchall()

            for r in received + sent:
                if r.get("created_at"):
                    r["created_at"] = str(r["created_at"])

        return success({"received": received, "sent": sent})
    except Exception as e:
        app.logger.error(f"get_my_requests error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/requests/<int:request_id>/respond", methods=["PUT"])
@jwt_required()
def respond_to_request(request_id):
    mentor_id = int(get_jwt_identity())
    body      = request.get_json(silent=True) or {}
    action    = (body.get("action", "") or "").strip()

    if action not in ("accepted", "rejected"):
        return error("Action must be 'accepted' or 'rejected'.", 400)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT mr.id, mr.seeker_id, u.full_name AS mentor_name
                   FROM mentor_requests mr
                   JOIN users u ON u.id = mr.mentor_id
                   WHERE mr.id = %s AND mr.mentor_id = %s AND mr.status = 'pending'""",
                (request_id, mentor_id),
            )
            req = cur.fetchone()
            if not req:
                return error("Request not found or already responded.", 404)

            cur.execute(
                "UPDATE mentor_requests SET status = %s WHERE id = %s",
                (action, request_id),
            )

        ntype = "request_accepted" if action == "accepted" else "request_rejected"
        ntitle = (
            f"{req['mentor_name']} accepted your mentoring request!"
            if action == "accepted"
            else f"{req['mentor_name']} declined your mentoring request."
        )
        _notify(conn, req["seeker_id"], mentor_id, ntype, ntitle, ref_id=request_id)

        return success(msg=f"Request {action}.")
    except Exception as e:
        app.logger.error(f"respond_to_request error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════
# JOB LISTINGS (abbreviated but working - keep your existing code)
# ═════════════════════════════════════════════════════════════

@app.route("/jobs", methods=["GET"])
def get_jobs():
    location        = request.args.get("location",        "").strip()
    employment_type = request.args.get("employment_type", "").strip()
    search          = request.args.get("search",          "").strip()
    page            = max(1, int(request.args.get("page", 1)))
    per_page        = 20
    offset          = (page - 1) * per_page

    conn = get_db()
    try:
        with conn.cursor() as cur:
            base   = "SELECT * FROM job_listings WHERE is_active = 1"
            params = []
            if location:
                base   += " AND location_type = %s"
                params.append(location.lower())
            if employment_type:
                base   += " AND employment_type = %s"
                params.append(employment_type)
            if search:
                base   += " AND MATCH(title, company, description, requirements) AGAINST(%s IN BOOLEAN MODE)"
                params.append(f"{search}*")
            base   += " ORDER BY created_at DESC LIMIT %s OFFSET %s"
            params += [per_page, offset]
            cur.execute(base, params)
            rows = cur.fetchall()
            for r in rows:
                if r.get("skills_required") and isinstance(r["skills_required"], str):
                    try:    r["skills_required"] = json.loads(r["skills_required"])
                    except: pass
                if r.get("created_at"): r["created_at"] = str(r["created_at"])
                if r.get("expires_at"): r["expires_at"] = str(r["expires_at"])
        return success(rows)
    except Exception as e:
        app.logger.error(f"get_jobs error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/jobs/<int:job_id>", methods=["GET"])
def get_job_detail(job_id):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT * FROM job_listings WHERE id = %s AND is_active = 1",
                (job_id,),
            )
            job = cur.fetchone()
            if not job:
                return error("Job not found.", 404)
            if job.get("skills_required") and isinstance(job["skills_required"], str):
                try:    job["skills_required"] = json.loads(job["skills_required"])
                except: pass
            if job.get("created_at"): job["created_at"] = str(job["created_at"])
            if job.get("expires_at"): job["expires_at"] = str(job["expires_at"])
        return success(job)
    except Exception as e:
        app.logger.error(f"get_job_detail error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/jobs", methods=["POST"])
@jwt_required()
def create_job():
    user_id = int(get_jwt_identity())
    body    = request.get_json(silent=True) or {}
    req     = ["title", "company", "location", "description", "requirements", "responsibilities"]
    for f in req:
        if not body.get(f):
            return error(f"'{f}' is required.", 400)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT role FROM users WHERE id = %s", (user_id,))
            u = cur.fetchone()
            if not u or u["role"] not in ("admin", "mentor"):
                return error("Only admins and mentors can post jobs.", 403)

            skills = body.get("skills_required")
            if isinstance(skills, (list, dict)):
                skills = json.dumps(skills)

            cur.execute(
                """INSERT INTO job_listings
                   (title, company, company_logo, location, location_type,
                    employment_type, experience_level, salary_min, salary_max,
                    salary_currency, description, requirements, responsibilities,
                    benefits, skills_required, posted_by, expires_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (
                    body["title"],
                    body["company"],
                    body.get("company_logo"),
                    body["location"],
                    body.get("location_type", "onsite"),
                    body.get("employment_type", "full_time"),
                    body.get("experience_level", "mid"),
                    body.get("salary_min"),
                    body.get("salary_max"),
                    body.get("salary_currency", "USD"),
                    body["description"],
                    body["requirements"],
                    body["responsibilities"],
                    body.get("benefits"),
                    skills,
                    user_id,
                    body.get("expires_at"),
                ),
            )
            new_id = conn.insert_id()
        return success({"id": new_id}, "Job posted successfully.", 201)
    except Exception as e:
        app.logger.error(f"create_job error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/jobs/<int:job_id>", methods=["PUT"])
@jwt_required()
def update_job(job_id):
    user_id = int(get_jwt_identity())
    body    = request.get_json(silent=True) or {}
    allowed = {
        "title", "company", "company_logo", "location", "location_type",
        "employment_type", "experience_level", "salary_min", "salary_max",
        "salary_currency", "description", "requirements", "responsibilities",
        "benefits", "skills_required", "is_active", "expires_at",
    }
    fields = {k: v for k, v in body.items() if k in allowed}
    if not fields:
        return error("No valid fields provided.", 400)

    if "skills_required" in fields and isinstance(fields["skills_required"], (list, dict)):
        fields["skills_required"] = json.dumps(fields["skills_required"])

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT role FROM users WHERE id = %s", (user_id,))
            u = cur.fetchone()
            if not u or u["role"] not in ("admin", "mentor"):
                return error("Not authorized.", 403)
            sets = ", ".join(f"{k} = %s" for k in fields)
            vals = list(fields.values()) + [job_id]
            cur.execute(f"UPDATE job_listings SET {sets} WHERE id = %s", vals)
        return success(msg="Job updated.")
    except Exception as e:
        app.logger.error(f"update_job error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/jobs/<int:job_id>", methods=["DELETE"])
@jwt_required()
def delete_job(job_id):
    user_id = int(get_jwt_identity())
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT role FROM users WHERE id = %s", (user_id,))
            u = cur.fetchone()
            if not u or u["role"] not in ("admin", "mentor"):
                return error("Not authorized.", 403)
            cur.execute(
                "UPDATE job_listings SET is_active = 0 WHERE id = %s", (job_id,)
            )
        return success(msg="Job deleted.")
    except Exception as e:
        app.logger.error(f"delete_job error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/jobs/<int:job_id>/apply", methods=["POST"])
@jwt_required()
def apply_for_job(job_id):
    user_id      = int(get_jwt_identity())
    body         = request.get_json(silent=True) or {}
    cover_letter = body.get("cover_letter", "")
    resume_url   = body.get("resume_url", "")

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM job_listings WHERE id = %s AND is_active = 1",
                (job_id,),
            )
            if not cur.fetchone():
                return error("Job not found.", 404)

            cur.execute(
                "SELECT id FROM job_applications WHERE job_id = %s AND user_id = %s",
                (job_id, user_id),
            )
            if cur.fetchone():
                return error("You have already applied for this job.", 409)

            cur.execute(
                """INSERT INTO job_applications
                   (job_id, user_id, cover_letter, resume_url)
                   VALUES (%s, %s, %s, %s)""",
                (job_id, user_id, cover_letter, resume_url),
            )
        return success(msg="Application submitted successfully!", status=201)
    except Exception as e:
        app.logger.error(f"apply_for_job error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/jobs/applications/my", methods=["GET"])
@jwt_required()
def get_my_applications():
    user_id = int(get_jwt_identity())
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT ja.id, ja.status, ja.applied_at,
                          jl.title, jl.company, jl.location, jl.employment_type,
                          jl.salary_min, jl.salary_max, jl.salary_currency
                   FROM job_applications ja
                   JOIN job_listings jl ON jl.id = ja.job_id
                   WHERE ja.user_id = %s
                   ORDER BY ja.applied_at DESC""",
                (user_id,),
            )
            rows = cur.fetchall()
            for r in rows:
                if r.get("applied_at"): r["applied_at"] = str(r["applied_at"])
        return success(rows)
    except Exception as e:
        app.logger.error(f"get_my_applications error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════
# NOTIFICATIONS (simplified but working)
# ═════════════════════════════════════════════════════════════

@app.route("/notifications", methods=["GET"])
@jwt_required()
def get_notifications():
    user_id  = int(get_jwt_identity())
    page     = max(1, int(request.args.get("page", 1)))
    per_page = 30
    offset   = (page - 1) * per_page

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT n.id, n.type, n.title, n.body, n.is_read,
                          n.reference_id, n.created_at,
                          u.full_name AS sender_name,
                          u.profile_picture_url AS sender_picture
                   FROM notifications n
                   LEFT JOIN users u ON u.id = n.sender_id
                   WHERE n.user_id = %s
                   ORDER BY n.created_at DESC
                   LIMIT %s OFFSET %s""",
                (user_id, per_page, offset),
            )
            rows = cur.fetchall()
            cur.execute(
                "SELECT COUNT(*) AS cnt FROM notifications "
                "WHERE user_id = %s AND is_read = 0",
                (user_id,),
            )
            unread = cur.fetchone()["cnt"]
            for r in rows:
                if r.get("created_at"): r["created_at"] = str(r["created_at"])
        return success({"notifications": rows, "unread_count": unread})
    except Exception as e:
        app.logger.error(f"get_notifications error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/notifications/read", methods=["PUT"])
@jwt_required()
def mark_notifications_read():
    user_id = int(get_jwt_identity())
    body    = request.get_json(silent=True) or {}
    ids     = body.get("ids", [])

    conn = get_db()
    try:
        with conn.cursor() as cur:
            if ids:
                placeholders = ", ".join(["%s"] * len(ids))
                cur.execute(
                    f"UPDATE notifications SET is_read = 1 "
                    f"WHERE user_id = %s AND id IN ({placeholders})",
                    [user_id] + ids,
                )
            else:
                cur.execute(
                    "UPDATE notifications SET is_read = 1 WHERE user_id = %s",
                    (user_id,),
                )
        return success(msg="Notifications marked as read.")
    except Exception as e:
        app.logger.error(f"mark_notifications_read error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════
# CHAT (simplified but working)
# ═════════════════════════════════════════════════════════════

@app.route("/chat/conversations", methods=["GET"])
@jwt_required()
def get_conversations():
    user_id = int(get_jwt_identity())
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT c.id, c.last_message, c.last_message_at,
                          CASE WHEN c.user_a_id = %s THEN c.user_b_id
                               ELSE c.user_a_id END AS other_user_id,
                          u.full_name  AS other_name,
                          u.profile_picture_url AS other_picture,
                          (SELECT COUNT(*) FROM messages m
                           WHERE m.conversation_id = c.id
                             AND m.sender_id != %s AND m.is_read = 0
                          ) AS unread_count
                   FROM conversations c
                   JOIN users u ON u.id = (
                       CASE WHEN c.user_a_id = %s THEN c.user_b_id
                            ELSE c.user_a_id END)
                   WHERE c.user_a_id = %s OR c.user_b_id = %s
                   ORDER BY c.last_message_at DESC""",
                (user_id, user_id, user_id, user_id, user_id),
            )
            rows = cur.fetchall()
            for r in rows:
                if r.get("last_message_at"):
                    r["last_message_at"] = str(r["last_message_at"])
        return success(rows)
    except Exception as e:
        app.logger.error(f"get_conversations error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/chat/messages/<int:conv_id>", methods=["GET"])
@jwt_required()
def get_messages(conv_id):
    user_id  = int(get_jwt_identity())
    page     = max(1, int(request.args.get("page", 1)))
    per_page = 50
    offset   = (page - 1) * per_page

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id FROM conversations "
                "WHERE id = %s AND (user_a_id = %s OR user_b_id = %s)",
                (conv_id, user_id, user_id),
            )
            if not cur.fetchone():
                return error("Conversation not found.", 404)

            cur.execute(
                """SELECT m.id, m.sender_id, m.content, m.is_read, m.created_at,
                          u.full_name AS sender_name,
                          u.profile_picture_url AS sender_picture
                   FROM messages m
                   JOIN users u ON u.id = m.sender_id
                   WHERE m.conversation_id = %s
                   ORDER BY m.created_at DESC
                   LIMIT %s OFFSET %s""",
                (conv_id, per_page, offset),
            )
            rows = cur.fetchall()
            rows.reverse()  # chronological order
            for r in rows:
                if r.get("created_at"): r["created_at"] = str(r["created_at"])

            cur.execute(
                "UPDATE messages SET is_read = 1 "
                "WHERE conversation_id = %s AND sender_id != %s AND is_read = 0",
                (conv_id, user_id),
            )
        return success(rows)
    except Exception as e:
        app.logger.error(f"get_messages error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/chat/messages", methods=["POST"])
@jwt_required()
def send_message():
    sender_id    = int(get_jwt_identity())
    body         = request.get_json(silent=True) or {}
    recipient_id = body.get("recipient_id")
    content      = (body.get("content", "") or "").strip()

    if not recipient_id:
        return error("recipient_id is required.", 400)
    if not content:
        return error("Message content cannot be empty.", 400)
    if sender_id == recipient_id:
        return error("You cannot message yourself.", 400)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            a, b = min(sender_id, recipient_id), max(sender_id, recipient_id)
            cur.execute(
                "SELECT id FROM conversations WHERE user_a_id = %s AND user_b_id = %s",
                (a, b),
            )
            conv = cur.fetchone()
            if not conv:
                cur.execute(
                    "INSERT INTO conversations (user_a_id, user_b_id) VALUES (%s, %s)",
                    (a, b),
                )
                conv_id = conn.insert_id()
            else:
                conv_id = conv["id"]

            cur.execute(
                "INSERT INTO messages (conversation_id, sender_id, content) "
                "VALUES (%s, %s, %s)",
                (conv_id, sender_id, content),
            )
            msg_id = conn.insert_id()

        with conn.cursor() as cur:
            cur.execute("SELECT full_name FROM users WHERE id = %s", (sender_id,))
            sender = cur.fetchone()
            sender_name = sender["full_name"] if sender else "Someone"
        _notify(
            conn, recipient_id, sender_id, "new_message",
            f"New message from {sender_name}",
            content[:120], msg_id,
        )
        return success({"message_id": msg_id, "conversation_id": conv_id}, "Message sent.", 201)

    except Exception as e:
        app.logger.error(f"send_message error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════
# SEARCH
# ═════════════════════════════════════════════════════════════

@app.route("/search", methods=["GET"])
@jwt_required()
def search():
    query    = request.args.get("q", "").strip()
    kind     = request.args.get("kind", "all")
    page     = max(1, int(request.args.get("page", 1)))
    per_page = 20
    offset   = (page - 1) * per_page

    if len(query) < 2:
        return error("Search query must be at least 2 characters.", 400)

    conn = get_db()
    try:
        mentors = []
        seekers = []

        with conn.cursor() as cur:
            if kind in ("all", "mentor"):
                cur.execute(
                    """SELECT u.id, u.full_name, u.profile_picture_url,
                              mp.headline, mp.current_job_title, mp.current_company,
                              mp.expertise_areas, mp.is_accepting_mentees
                       FROM users u
                       JOIN mentor_profiles mp ON mp.user_id = u.id
                       WHERE u.role = 'mentor' AND u.is_active = 1
                         AND (u.full_name LIKE %s
                              OR mp.headline LIKE %s
                              OR mp.current_job_title LIKE %s
                              OR mp.current_company LIKE %s)
                       ORDER BY mp.rating DESC
                       LIMIT %s OFFSET %s""",
                    (f"%{query}%", f"%{query}%", f"%{query}%", f"%{query}%",
                     per_page, offset),
                )
                mentors = cur.fetchall()
                for r in mentors:
                    val = r.get("expertise_areas")
                    if val and isinstance(val, str):
                        try:    r["expertise_areas"] = json.loads(val)
                        except: pass

            if kind in ("all", "seeker"):
                cur.execute(
                    """SELECT u.id, u.full_name, u.profile_picture_url,
                              js.headline, js.current_job_title
                       FROM users u
                       JOIN job_seekers js ON js.user_id = u.id
                       WHERE u.role = 'job_seeker' AND u.is_active = 1
                         AND (u.full_name LIKE %s
                              OR js.headline LIKE %s
                              OR js.current_job_title LIKE %s)
                       ORDER BY u.full_name ASC
                       LIMIT %s OFFSET %s""",
                    (f"%{query}%", f"%{query}%", f"%{query}%", per_page, offset),
                )
                seekers = cur.fetchall()

        return success({"mentors": mentors, "seekers": seekers})

    except Exception as e:
        app.logger.error(f"search error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════
# Entry point
# ═════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 55)
    print("  Career Navigator API v4.0  —  Starting up...")
    print("=" * 55)

    try:
        c = get_db()
        c.close()
        print("✅  Database  : connected")
    except Exception as e:
        print(f"❌  Database  : {e}")

    if BREVO_API_KEY and BREVO_API_KEY.startswith("xkeysib-"):
        print("✅  Brevo     : API key OK")
    else:
        print("⚠️   Brevo     : API key missing or invalid — emails will fail")

    print("=" * 55)
    app.run(debug=False, host="0.0.0.0", port=5000)