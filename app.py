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

# ─────────────────────────────────────────────────────────────────────────────
# App & extension setup
# ─────────────────────────────────────────────────────────────────────────────
app = Flask(__name__)
app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET", "super-secret-key")
app.config["JWT_ACCESS_TOKEN_EXPIRES"]  = timedelta(hours=1)
app.config["JWT_REFRESH_TOKEN_EXPIRES"] = timedelta(days=30)

bcrypt = Bcrypt(app)
jwt    = JWTManager(app)

# ─────────────────────────────────────────────────────────────────────────────
# Database configuration
# ─────────────────────────────────────────────────────────────────────────────
DB_CONFIG = {
    "host":        os.getenv("DB_HOST",   "localhost"),
    "port":        int(os.getenv("DB_PORT", 3306)),
    "user":        os.getenv("DB_USER",   "root"),
    "password":    os.getenv("DB_PASS",   "Fahdil@1"),
    "db":          os.getenv("DB_NAME",   "career_navigator"),
    "charset":     "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
    "autocommit":  True,
}

# ─────────────────────────────────────────────────────────────────────────────
# Brevo (email) configuration
# ─────────────────────────────────────────────────────────────────────────────
BREVO_API_KEY      = os.getenv("BREVO_API_KEY")
BREVO_SENDER_NAME  = os.getenv("BREVO_SENDER_NAME", "Career Navigator")
BREVO_SENDER_EMAIL = os.getenv("BREVO_SENDER_EMAIL")
# ─────────────────────────────────────────────────────────────────────────────
# Helper utilities
# ─────────────────────────────────────────────────────────────────────────────
def get_db():
    return pymysql.connect(**DB_CONFIG)

def success(data=None, msg="OK", status=200):
    return jsonify({"success": True,  "message": msg,   "data": data}), status

def error(msg="Error", status=400):
    return jsonify({"success": False, "message": msg,   "data": None}), status

def generate_otp(length=6):
    return "".join(random.choices(string.digits, k=length))

def send_verification_email(to_email, to_name, code):
    configuration = sib_api_v3_sdk.Configuration()
    configuration.api_key["api-key"] = BREVO_API_KEY
    api = sib_api_v3_sdk.TransactionalEmailsApi(
        sib_api_v3_sdk.ApiClient(configuration)
    )
    html_content = f"""
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


# ═════════════════════════════════════════════════════════════════════════════
# AUTH ROUTES
# ═════════════════════════════════════════════════════════════════════════════

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

            # Default job_seeker profile row
            cur.execute("INSERT INTO job_seekers (user_id) VALUES (%s)", (user_id,))

            code       = generate_otp()
            expires_at = datetime.utcnow() + timedelta(minutes=10)
            cur.execute(
                "INSERT INTO email_verification_codes (user_id, code, expires_at) "
                "VALUES (%s, %s, %s)",
                (user_id, code, expires_at),
            )

        sent = send_verification_email(email, email, code)
        msg  = ("Registration successful! Check your email for the verification code."
                if sent else
                "Account created, but we could not send the verification email. Use resend.")
        return success({"user_id": user_id}, msg, 201)

    except Exception as e:
        app.logger.error(f"register error: {e}")
        return error("An unexpected error occurred.", 500)
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
                   WHERE user_id=%s AND code=%s AND used=0 AND expires_at>UTC_TIMESTAMP()
                   ORDER BY id DESC LIMIT 1""",
                (user_id, code),
            )
            otp_row = cur.fetchone()
            if not otp_row:
                return error("Invalid or expired verification code.", 400)

            cur.execute("UPDATE email_verification_codes SET used=1 WHERE id=%s", (otp_row["id"],))
            cur.execute("UPDATE users SET is_verified=1 WHERE id=%s", (user_id,))

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
            cur.execute("SELECT id, is_verified FROM users WHERE email=%s", (email,))
            user = cur.fetchone()
            if not user:
                return error("No account found for this email.", 404)
            if user["is_verified"]:
                return error("This email is already verified.", 400)

            user_id = user["id"]
            cur.execute(
                "UPDATE email_verification_codes SET used=1 WHERE user_id=%s AND used=0",
                (user_id,),
            )
            code       = generate_otp()
            expires_at = datetime.utcnow() + timedelta(minutes=10)
            cur.execute(
                "INSERT INTO email_verification_codes (user_id, code, expires_at) VALUES (%s,%s,%s)",
                (user_id, code, expires_at),
            )

        sent = send_verification_email(email, email, code)
        if sent:
            return success(msg="A new verification code has been sent to your email.")
        return error("Failed to send email. Please try again shortly.", 500)

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
                "SELECT id, password_hash, is_verified, is_active, role, role_selected "
                "FROM users WHERE email=%s",
                (email,),
            )
            user = cur.fetchone()

        if not user or not bcrypt.check_password_hash(user["password_hash"], password):
            return error("Invalid email or password.", 401)
        if not user["is_verified"]:
            return error("Your email is not verified yet. Please check your inbox.", 403)
        if not user["is_active"]:
            return error("This account has been deactivated. Contact support.", 403)

        access_token  = create_access_token(identity=str(user["id"]))
        refresh_token = create_refresh_token(identity=str(user["id"]))
        return success(
            {
                "access_token":  access_token,
                "refresh_token": refresh_token,
                "role":          user["role"],
                "role_selected": bool(user["role_selected"]),
            },
            "Login successful!",
        )
    except Exception as e:
        app.logger.error(f"login error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════════════════════
# PROFILE ROUTES
# ═════════════════════════════════════════════════════════════════════════════

@app.route("/profile/me", methods=["GET"])
@jwt_required()
def get_profile():
    user_id = int(get_jwt_identity())
    conn = get_db()
    try:
        with conn.cursor() as cur:
            # Base user + job_seeker join
            cur.execute(
                """SELECT u.id, u.email, u.full_name, u.date_of_birth,
                          u.profile_picture, u.role, u.is_verified, u.role_selected,
                          js.headline, js.bio, js.phone, js.location,
                          js.years_of_experience, js.current_job_title,
                          js.desired_job_title, js.skills, js.resume_url,
                          js.linkedin_url, js.github_url, js.portfolio_url,
                          js.availability, js.open_to_remote,
                          js.desired_salary, js.salary_currency, js.notice_period
                   FROM users u
                   LEFT JOIN job_seekers js ON js.user_id = u.id
                   WHERE u.id = %s""",
                (user_id,),
            )
            profile = cur.fetchone()
            if not profile:
                return error("User not found.", 404)

            # Education entries
            cur.execute(
                """SELECT id, institution, degree, field_of_study,
                          start_year, end_year, is_current, description
                   FROM education WHERE user_id=%s ORDER BY start_year DESC""",
                (user_id,),
            )
            profile["education"] = cur.fetchall()

            # Work experience entries
            cur.execute(
                """SELECT id, company, job_title, employment_type, location,
                          start_date, end_date, is_current, description
                   FROM work_experience WHERE user_id=%s ORDER BY start_date DESC""",
                (user_id,),
            )
            work = cur.fetchall()
            for w in work:
                if w.get("start_date"): w["start_date"] = str(w["start_date"])
                if w.get("end_date"):   w["end_date"]   = str(w["end_date"])
            profile["work_experience"] = work

            # If mentor, also pull mentor_profile
            if profile.get("role") == "mentor":
                cur.execute(
                    """SELECT headline, bio, phone, location, years_of_experience,
                              current_company, current_job_title, expertise_areas,
                              industries, mentoring_style, session_price, currency,
                              availability_days, availability_time_from, availability_time_to,
                              max_mentees, is_accepting_mentees,
                              linkedin_url, github_url, portfolio_url, website_url,
                              rating, total_sessions
                       FROM mentor_profiles WHERE user_id=%s""",
                    (user_id,),
                )
                profile["mentor_profile"] = cur.fetchone()

        if profile.get("date_of_birth"):
            profile["date_of_birth"] = str(profile["date_of_birth"])
        profile["role_selected"] = bool(profile.get("role_selected", 0))

        return success(profile, "Profile loaded.")
    except Exception as e:
        app.logger.error(f"get_profile error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/profile/setup", methods=["PUT"])
@jwt_required()
def setup_profile():
    """Initial profile setup — name, dob, role choice."""
    user_id   = int(get_jwt_identity())
    body      = request.get_json(silent=True) or {}
    full_name = (body.get("full_name", "") or "").strip()
    dob       = (body.get("date_of_birth", "") or "").strip()
    role      = (body.get("role", "") or "").strip()  # 'job_seeker' or 'mentor'

    if not full_name:
        return error("Full name is required.", 400)
    if role not in ("job_seeker", "mentor", ""):
        return error("Role must be job_seeker or mentor.", 400)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            if role:
                cur.execute(
                    "UPDATE users SET full_name=%s, date_of_birth=%s, role=%s, role_selected=1 "
                    "WHERE id=%s",
                    (full_name, dob or None, role, user_id),
                )
                # If switching to mentor, ensure mentor_profile row exists
                if role == "mentor":
                    cur.execute(
                        "INSERT IGNORE INTO mentor_profiles (user_id) VALUES (%s)", (user_id,)
                    )
                # Ensure job_seekers row always exists too
                cur.execute(
                    "INSERT IGNORE INTO job_seekers (user_id) VALUES (%s)", (user_id,)
                )
            else:
                cur.execute(
                    "UPDATE users SET full_name=%s, date_of_birth=%s WHERE id=%s",
                    (full_name, dob or None, user_id),
                )
        return success({"role": role or None}, "Profile updated successfully.")
    except Exception as e:
        app.logger.error(f"setup_profile error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/profile/job-seeker", methods=["PUT"])
@jwt_required()
def update_job_seeker_profile():
    """Update job seeker specific fields."""
    user_id = int(get_jwt_identity())
    body    = request.get_json(silent=True) or {}

    allowed = [
        "headline", "bio", "phone", "location", "years_of_experience",
        "current_job_title", "desired_job_title", "skills", "resume_url",
        "linkedin_url", "github_url", "portfolio_url", "availability",
        "open_to_remote", "desired_salary", "salary_currency", "notice_period",
    ]
    updates = {k: body[k] for k in allowed if k in body}
    if not updates:
        return error("No fields to update.", 400)

    set_clause = ", ".join(f"{k}=%s" for k in updates)
    values     = list(updates.values()) + [user_id]

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE job_seekers SET {set_clause} WHERE user_id=%s", values
            )
        return success(msg="Job seeker profile updated.")
    except Exception as e:
        app.logger.error(f"update_job_seeker error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/profile/mentor", methods=["PUT"])
@jwt_required()
def update_mentor_profile():
    """Update mentor specific fields."""
    user_id = int(get_jwt_identity())
    body    = request.get_json(silent=True) or {}

    allowed = [
        "headline", "bio", "phone", "location", "years_of_experience",
        "current_company", "current_job_title", "expertise_areas", "industries",
        "mentoring_style", "session_price", "currency",
        "availability_days", "availability_time_from", "availability_time_to",
        "max_mentees", "is_accepting_mentees",
        "linkedin_url", "github_url", "portfolio_url", "website_url",
    ]
    updates = {k: body[k] for k in allowed if k in body}
    if not updates:
        return error("No fields to update.", 400)

    set_clause = ", ".join(f"{k}=%s" for k in updates)
    values     = list(updates.values()) + [user_id]

    conn = get_db()
    try:
        with conn.cursor() as cur:
            # Ensure mentor row exists
            cur.execute("INSERT IGNORE INTO mentor_profiles (user_id) VALUES (%s)", (user_id,))
            cur.execute(
                f"UPDATE mentor_profiles SET {set_clause} WHERE user_id=%s", values
            )
        return success(msg="Mentor profile updated.")
    except Exception as e:
        app.logger.error(f"update_mentor error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════════════════════
# EDUCATION ROUTES
# ═════════════════════════════════════════════════════════════════════════════

@app.route("/profile/education", methods=["GET"])
@jwt_required()
def get_education():
    user_id = int(get_jwt_identity())
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, institution, degree, field_of_study,
                          start_year, end_year, is_current, description
                   FROM education WHERE user_id=%s ORDER BY start_year DESC""",
                (user_id,),
            )
            rows = cur.fetchall()
        return success(rows, "Education loaded.")
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

    institution    = (body.get("institution",   "") or "").strip()
    degree         = (body.get("degree",        "") or "").strip()
    field_of_study = (body.get("field_of_study","") or "").strip()
    start_year     = body.get("start_year")
    end_year       = body.get("end_year")
    is_current     = int(body.get("is_current", 0))
    description    = body.get("description", "")

    if not institution or not degree or not field_of_study or not start_year:
        return error("institution, degree, field_of_study and start_year are required.", 400)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO education
                   (user_id, institution, degree, field_of_study,
                    start_year, end_year, is_current, description)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (user_id, institution, degree, field_of_study,
                 start_year, end_year or None, is_current, description),
            )
            new_id = conn.insert_id()
        return success({"id": new_id}, "Education entry added.", 201)
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

    allowed = ["institution","degree","field_of_study","start_year","end_year","is_current","description"]
    updates = {k: body[k] for k in allowed if k in body}
    if not updates:
        return error("No fields to update.", 400)

    set_clause = ", ".join(f"{k}=%s" for k in updates)
    values     = list(updates.values()) + [edu_id, user_id]

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE education SET {set_clause} WHERE id=%s AND user_id=%s", values
            )
        return success(msg="Education entry updated.")
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
            cur.execute("DELETE FROM education WHERE id=%s AND user_id=%s", (edu_id, user_id))
        return success(msg="Education entry deleted.")
    except Exception as e:
        app.logger.error(f"delete_education error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════════════════════
# WORK EXPERIENCE ROUTES
# ═════════════════════════════════════════════════════════════════════════════

@app.route("/profile/work-experience", methods=["GET"])
@jwt_required()
def get_work_experience():
    user_id = int(get_jwt_identity())
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT id, company, job_title, employment_type, location,
                          start_date, end_date, is_current, description
                   FROM work_experience WHERE user_id=%s ORDER BY start_date DESC""",
                (user_id,),
            )
            rows = cur.fetchall()
        for r in rows:
            if r.get("start_date"): r["start_date"] = str(r["start_date"])
            if r.get("end_date"):   r["end_date"]   = str(r["end_date"])
        return success(rows, "Work experience loaded.")
    except Exception as e:
        app.logger.error(f"get_work error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/profile/work-experience", methods=["POST"])
@jwt_required()
def add_work_experience():
    user_id = int(get_jwt_identity())
    body    = request.get_json(silent=True) or {}

    company         = (body.get("company",   "") or "").strip()
    job_title       = (body.get("job_title", "") or "").strip()
    employment_type = body.get("employment_type", "full_time")
    location        = body.get("location", "")
    start_date      = body.get("start_date")
    end_date        = body.get("end_date")
    is_current      = int(body.get("is_current", 0))
    description     = body.get("description", "")

    if not company or not job_title or not start_date:
        return error("company, job_title and start_date are required.", 400)

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """INSERT INTO work_experience
                   (user_id, company, job_title, employment_type, location,
                    start_date, end_date, is_current, description)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (user_id, company, job_title, employment_type, location,
                 start_date, end_date or None, is_current, description),
            )
            new_id = conn.insert_id()
        return success({"id": new_id}, "Work experience entry added.", 201)
    except Exception as e:
        app.logger.error(f"add_work error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/profile/work-experience/<int:work_id>", methods=["PUT"])
@jwt_required()
def update_work_experience(work_id):
    user_id = int(get_jwt_identity())
    body    = request.get_json(silent=True) or {}

    allowed = ["company","job_title","employment_type","location",
               "start_date","end_date","is_current","description"]
    updates = {k: body[k] for k in allowed if k in body}
    if not updates:
        return error("No fields to update.", 400)

    set_clause = ", ".join(f"{k}=%s" for k in updates)
    values     = list(updates.values()) + [work_id, user_id]

    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                f"UPDATE work_experience SET {set_clause} WHERE id=%s AND user_id=%s", values
            )
        return success(msg="Work experience updated.")
    except Exception as e:
        app.logger.error(f"update_work error: {e}")
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
                "DELETE FROM work_experience WHERE id=%s AND user_id=%s", (work_id, user_id)
            )
        return success(msg="Work experience entry deleted.")
    except Exception as e:
        app.logger.error(f"delete_work error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════════════════════
# MENTOR DISCOVERY
# ═════════════════════════════════════════════════════════════════════════════

@app.route("/mentors", methods=["GET"])
@jwt_required()
def list_mentors():
    """Return a paginated list of mentors. Optionally filter by expertise."""
    expertise = request.args.get("expertise", "")
    page      = max(1, int(request.args.get("page", 1)))
    per_page  = min(20, int(request.args.get("per_page", 10)))
    offset    = (page - 1) * per_page

    conn = get_db()
    try:
        with conn.cursor() as cur:
            if expertise:
                cur.execute(
                    """SELECT u.id, u.full_name, u.profile_picture,
                              mp.headline, mp.current_job_title, mp.current_company,
                              mp.expertise_areas, mp.session_price, mp.currency,
                              mp.rating, mp.total_sessions, mp.is_accepting_mentees
                       FROM mentor_profiles mp
                       JOIN users u ON u.id = mp.user_id
                       WHERE u.is_active=1 AND mp.is_accepting_mentees=1
                         AND JSON_SEARCH(mp.expertise_areas,'one',%s) IS NOT NULL
                       ORDER BY mp.rating DESC, mp.total_sessions DESC
                       LIMIT %s OFFSET %s""",
                    (f"%{expertise}%", per_page, offset),
                )
            else:
                cur.execute(
                    """SELECT u.id, u.full_name, u.profile_picture,
                              mp.headline, mp.current_job_title, mp.current_company,
                              mp.expertise_areas, mp.session_price, mp.currency,
                              mp.rating, mp.total_sessions, mp.is_accepting_mentees
                       FROM mentor_profiles mp
                       JOIN users u ON u.id = mp.user_id
                       WHERE u.is_active=1 AND mp.is_accepting_mentees=1
                       ORDER BY mp.rating DESC, mp.total_sessions DESC
                       LIMIT %s OFFSET %s""",
                    (per_page, offset),
                )
            mentors = cur.fetchall()
        return success({"mentors": mentors, "page": page, "per_page": per_page})
    except Exception as e:
        app.logger.error(f"list_mentors error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


@app.route("/mentors/<int:mentor_user_id>", methods=["GET"])
@jwt_required()
def get_mentor_detail(mentor_user_id):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """SELECT u.id, u.full_name, u.profile_picture,
                          mp.*
                   FROM mentor_profiles mp
                   JOIN users u ON u.id = mp.user_id
                   WHERE mp.user_id=%s AND u.is_active=1""",
                (mentor_user_id,),
            )
            mentor = cur.fetchone()
            if not mentor:
                return error("Mentor not found.", 404)

            # Their work experience
            cur.execute(
                """SELECT company, job_title, employment_type, start_date, end_date, is_current
                   FROM work_experience WHERE user_id=%s ORDER BY start_date DESC""",
                (mentor_user_id,),
            )
            work = cur.fetchall()
            for w in work:
                if w.get("start_date"): w["start_date"] = str(w["start_date"])
                if w.get("end_date"):   w["end_date"]   = str(w["end_date"])
            mentor["work_experience"] = work

            # Their education
            cur.execute(
                """SELECT institution, degree, field_of_study, start_year, end_year
                   FROM education WHERE user_id=%s ORDER BY start_year DESC""",
                (mentor_user_id,),
            )
            mentor["education"] = cur.fetchall()

        return success(mentor, "Mentor loaded.")
    except Exception as e:
        app.logger.error(f"get_mentor_detail error: {e}")
        return error("An unexpected error occurred.", 500)
    finally:
        conn.close()


# ═════════════════════════════════════════════════════════════════════════════
# Entry point
# ═════════════════════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("--- Initializing Career Navigator API v2 ---")
    try:
        test_conn = get_db()
        test_conn.close()
        print("✅  Database : connected to 'career_navigator'")
    except Exception as e:
        print(f"❌  Database : {e}")

    if BREVO_API_KEY.startswith("xkeysib-"):
        print("✅  Brevo    : API key detected")
    else:
        print("⚠️   Brevo    : API key missing or invalid")

    app.run(debug=False, host="0.0.0.0", port=5000)