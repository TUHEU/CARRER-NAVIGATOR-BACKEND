"""Career Navigator API v3 - OOP Flask Backend"""
import os, json, random, string
from datetime import datetime, timedelta
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager, create_access_token, create_refresh_token, get_jwt_identity, jwt_required
import pymysql, pymysql.cursors
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException

load_dotenv()
app = Flask(__name__)
app.config["JWT_SECRET_KEY"] = os.getenv("JWT_SECRET", "super-secret-key")
app.config["JWT_ACCESS_TOKEN_EXPIRES"] = timedelta(hours=2)
app.config["JWT_REFRESH_TOKEN_EXPIRES"] = timedelta(days=30)
bcrypt = Bcrypt(app)
jwt = JWTManager(app)

class DatabaseManager:
    _config = {"host": os.getenv("DB_HOST","localhost"), "port": int(os.getenv("DB_PORT",3306)),
               "user": os.getenv("DB_USER","root"), "password": os.getenv("DB_PASS",""),
               "db": os.getenv("DB_NAME","career_navigator"), "charset": "utf8mb4",
               "cursorclass": pymysql.cursors.DictCursor, "autocommit": True}
    @classmethod
    def connect(cls): return pymysql.connect(**cls._config)
    @classmethod
    def test(cls):
        try: c=cls.connect(); c.close(); return True
        except: return False

class EmailService:
    _key = os.getenv("BREVO_API_KEY","")
    _from = os.getenv("BREVO_SENDER_EMAIL","")
    _name = os.getenv("BREVO_SENDER_NAME","Career Navigator")
    @classmethod
    def _send(cls, to, subject, html):
        if not cls._key or not cls._from: return False
        cfg = sib_api_v3_sdk.Configuration(); cfg.api_key["api-key"] = cls._key
        api = sib_api_v3_sdk.TransactionalEmailsApi(sib_api_v3_sdk.ApiClient(cfg))
        try:
            api.send_transac_email(sib_api_v3_sdk.SendSmtpEmail(
                to=[{"email":to,"name":to}], sender={"email":cls._from,"name":cls._name},
                subject=subject, html_content=html)); return True
        except ApiException as e: app.logger.error(f"Email error:{e}"); return False
    @classmethod
    def verification(cls, email, code):
        return cls._send(email, "Career Navigator — Verify Email",
            f"<div style='font-family:Arial;padding:30px'><h2>Career Navigator</h2>"
            f"<p>Your verification code:</p><h1 style='color:#00E5FF;letter-spacing:8px'>{code}</h1>"
            f"<p>Expires in 10 minutes.</p></div>")
    @classmethod
    def password_reset(cls, email, code):
        return cls._send(email, "Career Navigator — Password Reset",
            f"<div style='font-family:Arial;padding:30px'><h2>Password Reset</h2>"
            f"<p>Your reset code:</p><h1 style='color:#FF6B6B;letter-spacing:8px'>{code}</h1>"
            f"<p>Expires in 15 minutes. Ignore if not requested.</p></div>")
    @classmethod
    def mentor_request(cls, mentor_email, seeker_name):
        return cls._send(mentor_email, "New Mentorship Request",
            f"<div style='font-family:Arial;padding:30px'><h2>Career Navigator</h2>"
            f"<p><b>{seeker_name}</b> sent you a mentorship request. Open the app to respond.</p></div>")

def ok(data=None, msg="OK", status=200): return jsonify({"success":True,"message":msg,"data":data}), status
def err(msg="Error", status=400): return jsonify({"success":False,"message":msg,"data":None}), status
def otp(n=6): return "".join(random.choices(string.digits, k=n))

# ── AUTH ──────────────────────────────────────────────────────────────────────
@app.route("/auth/register", methods=["POST"])
def register():
    b = request.get_json(silent=True) or {}
    email = (b.get("email","") or "").strip().lower()
    pw = (b.get("password","") or "")
    if not email or "@" not in email: return err("Valid email required.", 400)
    if not pw or len(pw) < 6: return err("Password min 6 chars.", 400)
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email=%s", (email,))
            if cur.fetchone(): return err("Email already registered.", 409)
            h = bcrypt.generate_password_hash(pw).decode()
            cur.execute("INSERT INTO users (email,password_hash,role,is_verified) VALUES (%s,%s,'job_seeker',0)", (email,h))
            uid = conn.insert_id()
            cur.execute("INSERT INTO job_seekers (user_id) VALUES (%s)", (uid,))
            code = otp(); exp = datetime.utcnow()+timedelta(minutes=10)
            cur.execute("INSERT INTO email_verification_codes (user_id,code,expires_at) VALUES (%s,%s,%s)", (uid,code,exp))
        sent = EmailService.verification(email, code)
        return ok({"user_id":uid}, "Registered! Check email for code." if sent else "Registered but email failed. Use resend.", 201)
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

@app.route("/auth/verify-email", methods=["POST"])
def verify_email():
    b = request.get_json(silent=True) or {}
    email = (b.get("email","") or "").strip().lower()
    code = (b.get("code","") or "").strip()
    if not email or not code: return err("Email and code required.", 400)
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, is_verified FROM users WHERE email=%s", (email,))
            u = cur.fetchone()
            if not u: return err("No account found.", 404)
            if u["is_verified"]: return err("Already verified.", 400)
            uid = u["id"]
            cur.execute("SELECT id FROM email_verification_codes WHERE user_id=%s AND code=%s AND used=0 AND expires_at>UTC_TIMESTAMP() ORDER BY id DESC LIMIT 1", (uid,code))
            row = cur.fetchone()
            if not row: return err("Invalid or expired code.", 400)
            cur.execute("UPDATE email_verification_codes SET used=1 WHERE id=%s", (row["id"],))
            cur.execute("UPDATE users SET is_verified=1 WHERE id=%s", (uid,))
        a = create_access_token(identity=str(uid))
        r = create_refresh_token(identity=str(uid))
        return ok({"access_token":a,"refresh_token":r}, "Email verified!")
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

@app.route("/auth/resend-code", methods=["POST"])
def resend_code():
    b = request.get_json(silent=True) or {}
    email = (b.get("email","") or "").strip().lower()
    if not email: return err("Email required.", 400)
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id, is_verified FROM users WHERE email=%s", (email,))
            u = cur.fetchone()
            if not u: return err("No account found.", 404)
            if u["is_verified"]: return err("Already verified.", 400)
            uid = u["id"]
            cur.execute("UPDATE email_verification_codes SET used=1 WHERE user_id=%s AND used=0", (uid,))
            code = otp(); exp = datetime.utcnow()+timedelta(minutes=10)
            cur.execute("INSERT INTO email_verification_codes (user_id,code,expires_at) VALUES (%s,%s,%s)", (uid,code,exp))
        EmailService.verification(email, code)
        return ok(msg="New code sent.")
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

@app.route("/auth/login", methods=["POST"])
def login():
    b = request.get_json(silent=True) or {}
    email = (b.get("email","") or "").strip().lower()
    pw = (b.get("password","") or "")
    if not email or not pw: return err("Email and password required.", 400)
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id,password_hash,is_verified,is_active,role,role_selected FROM users WHERE email=%s", (email,))
            u = cur.fetchone()
        if not u or not bcrypt.check_password_hash(u["password_hash"], pw): return err("Invalid credentials.", 401)
        if not u["is_verified"]: return err("Email not verified.", 403)
        if not u["is_active"]: return err("Account deactivated.", 403)
        a = create_access_token(identity=str(u["id"]))
        r = create_refresh_token(identity=str(u["id"]))
        return ok({"access_token":a,"refresh_token":r,"role":u["role"],"role_selected":bool(u["role_selected"])}, "Login successful!")
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

@app.route("/auth/forgot-password", methods=["POST"])
def forgot_password():
    b = request.get_json(silent=True) or {}
    email = (b.get("email","") or "").strip().lower()
    if not email: return err("Email required.", 400)
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email=%s AND is_verified=1", (email,))
            u = cur.fetchone()
            if u:
                uid = u["id"]
                cur.execute("UPDATE password_reset_codes SET used=1 WHERE user_id=%s AND used=0", (uid,))
                code = otp(); exp = datetime.utcnow()+timedelta(minutes=15)
                cur.execute("INSERT INTO password_reset_codes (user_id,code,expires_at) VALUES (%s,%s,%s)", (uid,code,exp))
                EmailService.password_reset(email, code)
        return ok(msg="If this email exists, a reset code has been sent.")
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

@app.route("/auth/reset-password", methods=["POST"])
def reset_password():
    b = request.get_json(silent=True) or {}
    email = (b.get("email","") or "").strip().lower()
    code = (b.get("code","") or "").strip()
    new_pw = (b.get("password","") or "")
    if not email or not code or not new_pw: return err("email, code and password required.", 400)
    if len(new_pw) < 6: return err("Password min 6 chars.", 400)
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM users WHERE email=%s", (email,))
            u = cur.fetchone()
            if not u: return err("Invalid request.", 400)
            uid = u["id"]
            cur.execute("SELECT id FROM password_reset_codes WHERE user_id=%s AND code=%s AND used=0 AND expires_at>UTC_TIMESTAMP() ORDER BY id DESC LIMIT 1", (uid,code))
            row = cur.fetchone()
            if not row: return err("Invalid or expired code.", 400)
            h = bcrypt.generate_password_hash(new_pw).decode()
            cur.execute("UPDATE users SET password_hash=%s WHERE id=%s", (h,uid))
            cur.execute("UPDATE password_reset_codes SET used=1 WHERE id=%s", (row["id"],))
        return ok(msg="Password reset. Please log in.")
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

# ── PROFILE ───────────────────────────────────────────────────────────────────
@app.route("/profile/me", methods=["GET"])
@jwt_required()
def get_me():
    uid = int(get_jwt_identity())
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT u.id,u.email,u.full_name,u.date_of_birth,u.profile_picture,
                          u.profile_picture_url,u.role,u.is_verified,u.role_selected,
                          js.headline,js.bio,js.phone,js.location,js.years_of_experience,
                          js.current_job_title,js.desired_job_title,js.skills,js.resume_url,
                          js.linkedin_url,js.github_url,js.portfolio_url,js.availability,
                          js.open_to_remote,js.desired_salary,js.salary_currency,js.notice_period,js.interests
                   FROM users u LEFT JOIN job_seekers js ON js.user_id=u.id WHERE u.id=%s""", (uid,))
            p = cur.fetchone()
            if not p: return err("User not found.", 404)
            cur.execute("SELECT id,institution,degree,field_of_study,start_year,end_year,is_current,description FROM education WHERE user_id=%s ORDER BY start_year DESC", (uid,))
            p["education"] = cur.fetchall()
            cur.execute("SELECT id,company,job_title,employment_type,location,start_date,end_date,is_current,description FROM work_experience WHERE user_id=%s ORDER BY start_date DESC", (uid,))
            work = cur.fetchall()
            for w in work:
                if w.get("start_date"): w["start_date"] = str(w["start_date"])
                if w.get("end_date"): w["end_date"] = str(w["end_date"])
            p["work_experience"] = work
            if p.get("role") == "mentor":
                cur.execute("SELECT * FROM mentor_profiles WHERE user_id=%s", (uid,))
                p["mentor_profile"] = cur.fetchone()
            cur.execute("SELECT COUNT(*) as cnt FROM notifications WHERE user_id=%s AND is_read=0", (uid,))
            r = cur.fetchone(); p["unread_notifications"] = r["cnt"] if r else 0
        if p.get("date_of_birth"): p["date_of_birth"] = str(p["date_of_birth"])
        p["role_selected"] = bool(p.get("role_selected",0))
        return ok(p, "Profile loaded.")
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

@app.route("/profile/setup", methods=["PUT"])
@jwt_required()
def setup_profile():
    uid = int(get_jwt_identity())
    b = request.get_json(silent=True) or {}
    name = (b.get("full_name","") or "").strip()
    dob = (b.get("date_of_birth","") or "").strip()
    role = (b.get("role","") or "").strip()
    if not name: return err("Full name required.", 400)
    if role not in ("job_seeker","mentor",""): return err("Role must be job_seeker or mentor.", 400)
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            if role:
                cur.execute("UPDATE users SET full_name=%s,date_of_birth=%s,role=%s,role_selected=1 WHERE id=%s", (name,dob or None,role,uid))
                if role == "mentor": cur.execute("INSERT IGNORE INTO mentor_profiles (user_id) VALUES (%s)", (uid,))
                cur.execute("INSERT IGNORE INTO job_seekers (user_id) VALUES (%s)", (uid,))
            else:
                cur.execute("UPDATE users SET full_name=%s,date_of_birth=%s WHERE id=%s", (name,dob or None,uid))
        return ok({"role":role or None}, "Profile updated.")
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

@app.route("/profile/picture", methods=["PUT"])
@jwt_required()
def update_picture():
    uid = int(get_jwt_identity())
    b = request.get_json(silent=True) or {}
    url = (b.get("picture_url","") or "").strip()
    if not url: return err("picture_url required.", 400)
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET profile_picture_url=%s WHERE id=%s", (url,uid))
        return ok(msg="Picture updated.")
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

@app.route("/profile/job-seeker", methods=["PUT"])
@jwt_required()
def update_job_seeker():
    uid = int(get_jwt_identity())
    b = request.get_json(silent=True) or {}
    allowed = ["headline","bio","phone","location","years_of_experience","current_job_title",
               "desired_job_title","skills","resume_url","linkedin_url","github_url",
               "portfolio_url","availability","open_to_remote","desired_salary",
               "salary_currency","notice_period","interests"]
    updates = {k:b[k] for k in allowed if k in b}
    if not updates: return err("No fields to update.", 400)
    sc = ", ".join(f"{k}=%s" for k in updates)
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE job_seekers SET {sc} WHERE user_id=%s", list(updates.values())+[uid])
        return ok(msg="Job seeker profile updated.")
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

@app.route("/profile/mentor", methods=["PUT"])
@jwt_required()
def update_mentor():
    uid = int(get_jwt_identity())
    b = request.get_json(silent=True) or {}
    allowed = ["headline","bio","phone","location","years_of_experience","current_company",
               "current_job_title","expertise_areas","industries","advice_topics",
               "mentoring_style","session_price","currency","availability_days",
               "availability_time_from","availability_time_to","max_mentees",
               "is_accepting_mentees","linkedin_url","github_url","portfolio_url","website_url"]
    updates = {k:b[k] for k in allowed if k in b}
    if not updates: return err("No fields to update.", 400)
    sc = ", ".join(f"{k}=%s" for k in updates)
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT IGNORE INTO mentor_profiles (user_id) VALUES (%s)", (uid,))
            cur.execute(f"UPDATE mentor_profiles SET {sc} WHERE user_id=%s", list(updates.values())+[uid])
        return ok(msg="Mentor profile updated.")
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

# ── EDUCATION ─────────────────────────────────────────────────────────────────
@app.route("/profile/education", methods=["GET"])
@jwt_required()
def get_education():
    uid = int(get_jwt_identity())
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id,institution,degree,field_of_study,start_year,end_year,is_current,description FROM education WHERE user_id=%s ORDER BY start_year DESC", (uid,))
            return ok(cur.fetchall(), "Education loaded.")
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

@app.route("/profile/education", methods=["POST"])
@jwt_required()
def add_education():
    uid = int(get_jwt_identity())
    b = request.get_json(silent=True) or {}
    inst = (b.get("institution","") or "").strip()
    deg = (b.get("degree","") or "").strip()
    fos = (b.get("field_of_study","") or "").strip()
    sy = b.get("start_year"); ey = b.get("end_year")
    curr = int(b.get("is_current",0)); desc = b.get("description","")
    if not inst or not deg or not fos or not sy: return err("institution, degree, field_of_study, start_year required.", 400)
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO education (user_id,institution,degree,field_of_study,start_year,end_year,is_current,description) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", (uid,inst,deg,fos,sy,ey or None,curr,desc))
            return ok({"id":conn.insert_id()}, "Education added.", 201)
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

@app.route("/profile/education/<int:edu_id>", methods=["PUT"])
@jwt_required()
def update_education(edu_id):
    uid = int(get_jwt_identity())
    b = request.get_json(silent=True) or {}
    allowed = ["institution","degree","field_of_study","start_year","end_year","is_current","description"]
    updates = {k:b[k] for k in allowed if k in b}
    if not updates: return err("No fields.", 400)
    sc = ", ".join(f"{k}=%s" for k in updates)
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE education SET {sc} WHERE id=%s AND user_id=%s", list(updates.values())+[edu_id,uid])
        return ok(msg="Updated.")
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

@app.route("/profile/education/<int:edu_id>", methods=["DELETE"])
@jwt_required()
def delete_education(edu_id):
    uid = int(get_jwt_identity())
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM education WHERE id=%s AND user_id=%s", (edu_id,uid))
        return ok(msg="Deleted.")
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

# ── WORK EXPERIENCE ───────────────────────────────────────────────────────────
@app.route("/profile/work-experience", methods=["GET"])
@jwt_required()
def get_work():
    uid = int(get_jwt_identity())
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id,company,job_title,employment_type,location,start_date,end_date,is_current,description FROM work_experience WHERE user_id=%s ORDER BY start_date DESC", (uid,))
            rows = cur.fetchall()
        for r in rows:
            if r.get("start_date"): r["start_date"] = str(r["start_date"])
            if r.get("end_date"): r["end_date"] = str(r["end_date"])
        return ok(rows, "Work loaded.")
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

@app.route("/profile/work-experience", methods=["POST"])
@jwt_required()
def add_work():
    uid = int(get_jwt_identity())
    b = request.get_json(silent=True) or {}
    co = (b.get("company","") or "").strip(); jt = (b.get("job_title","") or "").strip()
    et = b.get("employment_type","full_time"); loc = b.get("location","")
    sd = b.get("start_date"); ed = b.get("end_date")
    curr = int(b.get("is_current",0)); desc = b.get("description","")
    if not co or not jt or not sd: return err("company, job_title, start_date required.", 400)
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("INSERT INTO work_experience (user_id,company,job_title,employment_type,location,start_date,end_date,is_current,description) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)", (uid,co,jt,et,loc,sd,ed or None,curr,desc))
            return ok({"id":conn.insert_id()}, "Work added.", 201)
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

@app.route("/profile/work-experience/<int:wid>", methods=["PUT"])
@jwt_required()
def update_work(wid):
    uid = int(get_jwt_identity())
    b = request.get_json(silent=True) or {}
    allowed = ["company","job_title","employment_type","location","start_date","end_date","is_current","description"]
    updates = {k:b[k] for k in allowed if k in b}
    if not updates: return err("No fields.", 400)
    sc = ", ".join(f"{k}=%s" for k in updates)
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            cur.execute(f"UPDATE work_experience SET {sc} WHERE id=%s AND user_id=%s", list(updates.values())+[wid,uid])
        return ok(msg="Updated.")
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

@app.route("/profile/work-experience/<int:wid>", methods=["DELETE"])
@jwt_required()
def delete_work(wid):
    uid = int(get_jwt_identity())
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM work_experience WHERE id=%s AND user_id=%s", (wid,uid))
        return ok(msg="Deleted.")
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

# ── MENTORS ───────────────────────────────────────────────────────────────────
@app.route("/mentors", methods=["GET"])
@jwt_required()
def list_mentors():
    exp = request.args.get("expertise",""); page = max(1,int(request.args.get("page",1)))
    pp = min(20,int(request.args.get("per_page",10))); offset = (page-1)*pp
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            base = """SELECT u.id,u.full_name,u.profile_picture_url,mp.headline,
                      mp.current_job_title,mp.current_company,mp.expertise_areas,
                      mp.session_price,mp.currency,mp.rating,mp.total_sessions,
                      mp.is_accepting_mentees FROM mentor_profiles mp
                      JOIN users u ON u.id=mp.user_id WHERE u.is_active=1 AND mp.is_accepting_mentees=1"""
            if exp:
                cur.execute(base+" AND JSON_SEARCH(mp.expertise_areas,'one',%s) IS NOT NULL ORDER BY mp.rating DESC LIMIT %s OFFSET %s", (f"%{exp}%",pp,offset))
            else:
                cur.execute(base+" ORDER BY mp.rating DESC LIMIT %s OFFSET %s", (pp,offset))
            return ok({"mentors":cur.fetchall(),"page":page,"per_page":pp})
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

@app.route("/mentors/<int:mid>", methods=["GET"])
@jwt_required()
def get_mentor(mid):
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT u.id,u.full_name,u.profile_picture_url,mp.* FROM mentor_profiles mp JOIN users u ON u.id=mp.user_id WHERE mp.user_id=%s AND u.is_active=1", (mid,))
            m = cur.fetchone()
            if not m: return err("Mentor not found.", 404)
            cur.execute("SELECT company,job_title,employment_type,start_date,end_date,is_current FROM work_experience WHERE user_id=%s ORDER BY start_date DESC", (mid,))
            work = cur.fetchall()
            for w in work:
                if w.get("start_date"): w["start_date"] = str(w["start_date"])
                if w.get("end_date"): w["end_date"] = str(w["end_date"])
            m["work_experience"] = work
            cur.execute("SELECT institution,degree,field_of_study,start_year,end_year FROM education WHERE user_id=%s ORDER BY start_year DESC", (mid,))
            m["education"] = cur.fetchall()
        return ok(m, "Mentor loaded.")
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

@app.route("/mentors/user/<int:user_id>/background", methods=["GET"])
@jwt_required()
def get_user_background(user_id):
    mentor_id = int(get_jwt_identity())
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM mentor_requests WHERE mentor_id=%s AND seeker_id=%s AND status='accepted'", (mentor_id,user_id))
            if not cur.fetchone(): return err("No accepted connection.", 403)
            cur.execute("SELECT institution,degree,field_of_study,start_year,end_year,is_current,description FROM education WHERE user_id=%s ORDER BY start_year DESC", (user_id,))
            edu = cur.fetchall()
            cur.execute("SELECT company,job_title,employment_type,location,start_date,end_date,is_current,description FROM work_experience WHERE user_id=%s ORDER BY start_date DESC", (user_id,))
            work = cur.fetchall()
            for w in work:
                if w.get("start_date"): w["start_date"] = str(w["start_date"])
                if w.get("end_date"): w["end_date"] = str(w["end_date"])
        return ok({"education":edu,"work_experience":work}, "User background loaded.")
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

# ── REQUESTS ──────────────────────────────────────────────────────────────────
@app.route("/requests", methods=["POST"])
@jwt_required()
def send_request():
    seeker_id = int(get_jwt_identity())
    b = request.get_json(silent=True) or {}
    mentor_id = b.get("mentor_id"); msg = (b.get("message","") or "").strip()
    if not mentor_id: return err("mentor_id required.", 400)
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id,email,full_name FROM users WHERE id=%s AND role='mentor' AND is_active=1", (mentor_id,))
            mentor = cur.fetchone()
            if not mentor: return err("Mentor not found.", 404)
            cur.execute("SELECT id,status FROM mentor_requests WHERE seeker_id=%s AND mentor_id=%s", (seeker_id,mentor_id))
            ex = cur.fetchone()
            if ex:
                if ex["status"] in ("pending","accepted"): return err(f"Request already {ex['status']}.", 409)
                cur.execute("UPDATE mentor_requests SET status='pending',message=%s WHERE seeker_id=%s AND mentor_id=%s", (msg or None,seeker_id,mentor_id))
                req_id = ex["id"]
            else:
                cur.execute("INSERT INTO mentor_requests (seeker_id,mentor_id,message) VALUES (%s,%s,%s)", (seeker_id,mentor_id,msg or None))
                req_id = conn.insert_id()
            cur.execute("SELECT full_name FROM users WHERE id=%s", (seeker_id,))
            s = cur.fetchone(); sname = (s["full_name"] if s else None) or "A job seeker"
            cur.execute("INSERT INTO notifications (user_id,sender_id,type,title,body,reference_id) VALUES (%s,%s,'mentor_request',%s,%s,%s)", (mentor_id,seeker_id,"New Mentorship Request",f"{sname} wants you as their mentor.",req_id))
        EmailService.mentor_request(mentor["email"], sname)
        return ok({"request_id":req_id}, "Request sent.", 201)
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

@app.route("/requests", methods=["GET"])
@jwt_required()
def my_requests():
    uid = int(get_jwt_identity())
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT role FROM users WHERE id=%s", (uid,))
            u = cur.fetchone(); role = u["role"] if u else "job_seeker"
            if role == "mentor":
                cur.execute("SELECT mr.*,u.full_name as seeker_name,u.profile_picture_url as seeker_picture FROM mentor_requests mr JOIN users u ON u.id=mr.seeker_id WHERE mr.mentor_id=%s ORDER BY mr.created_at DESC", (uid,))
            else:
                cur.execute("SELECT mr.*,u.full_name as mentor_name,u.profile_picture_url as mentor_picture,mp.headline FROM mentor_requests mr JOIN users u ON u.id=mr.mentor_id LEFT JOIN mentor_profiles mp ON mp.user_id=mr.mentor_id WHERE mr.seeker_id=%s ORDER BY mr.created_at DESC", (uid,))
            rows = cur.fetchall()
            for r in rows:
                if r.get("created_at"): r["created_at"] = str(r["created_at"])
                if r.get("updated_at"): r["updated_at"] = str(r["updated_at"])
        return ok(rows, "Requests loaded.")
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

@app.route("/requests/<int:rid>/respond", methods=["PUT"])
@jwt_required()
def respond_request(rid):
    mentor_id = int(get_jwt_identity())
    b = request.get_json(silent=True) or {}
    action = (b.get("action","") or "").strip()
    if action not in ("accept","reject"): return err("action must be accept or reject.", 400)
    ns = "accepted" if action=="accept" else "rejected"
    nt = "request_accepted" if action=="accept" else "request_rejected"
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id,seeker_id FROM mentor_requests WHERE id=%s AND mentor_id=%s AND status='pending'", (rid,mentor_id))
            req = cur.fetchone()
            if not req: return err("Request not found or not pending.", 404)
            cur.execute("UPDATE mentor_requests SET status=%s WHERE id=%s", (ns,rid))
            title = "Your request was accepted! 🎉" if action=="accept" else "Mentorship request declined."
            body_text = "You can now chat with your mentor." if action=="accept" else None
            cur.execute("INSERT INTO notifications (user_id,sender_id,type,title,body,reference_id) VALUES (%s,%s,%s,%s,%s,%s)", (req["seeker_id"],mentor_id,nt,title,body_text,rid))
        return ok(msg=f"Request {ns}.")
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

# ── NOTIFICATIONS ─────────────────────────────────────────────────────────────
@app.route("/notifications", methods=["GET"])
@jwt_required()
def get_notifications():
    uid = int(get_jwt_identity())
    page = max(1,int(request.args.get("page",1))); pp = min(50,int(request.args.get("per_page",20)))
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT n.*,u.full_name as sender_name,u.profile_picture_url as sender_picture FROM notifications n LEFT JOIN users u ON u.id=n.sender_id WHERE n.user_id=%s ORDER BY n.created_at DESC LIMIT %s OFFSET %s", (uid,pp,(page-1)*pp))
            notifs = cur.fetchall()
            for n in notifs:
                if n.get("created_at"): n["created_at"] = str(n["created_at"])
            cur.execute("SELECT COUNT(*) as cnt FROM notifications WHERE user_id=%s AND is_read=0", (uid,))
            r = cur.fetchone(); unread = r["cnt"] if r else 0
        return ok({"notifications":notifs,"unread":unread})
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

@app.route("/notifications/read", methods=["PUT"])
@jwt_required()
def mark_notifications_read():
    uid = int(get_jwt_identity())
    b = request.get_json(silent=True) or {}; ids = b.get("ids",[])
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            if ids:
                fmt = ",".join(["%s"]*len(ids))
                cur.execute(f"UPDATE notifications SET is_read=1 WHERE user_id=%s AND id IN ({fmt})", [uid]+ids)
            else:
                cur.execute("UPDATE notifications SET is_read=1 WHERE user_id=%s", (uid,))
        return ok(msg="Marked read.")
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

# ── CHAT ──────────────────────────────────────────────────────────────────────
@app.route("/chat/conversations", methods=["GET"])
@jwt_required()
def get_conversations():
    uid = int(get_jwt_identity())
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("""SELECT c.*,
                CASE WHEN c.user_a_id=%s THEN ub.full_name ELSE ua.full_name END as other_name,
                CASE WHEN c.user_a_id=%s THEN ub.profile_picture_url ELSE ua.profile_picture_url END as other_picture,
                CASE WHEN c.user_a_id=%s THEN c.user_b_id ELSE c.user_a_id END as other_user_id
                FROM conversations c JOIN users ua ON ua.id=c.user_a_id JOIN users ub ON ub.id=c.user_b_id
                WHERE c.user_a_id=%s OR c.user_b_id=%s ORDER BY c.last_message_at DESC""", (uid,uid,uid,uid,uid))
            convs = cur.fetchall()
            for cv in convs:
                if cv.get("last_message_at"): cv["last_message_at"] = str(cv["last_message_at"])
                if cv.get("created_at"): cv["created_at"] = str(cv["created_at"])
        return ok(convs, "Conversations loaded.")
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

@app.route("/chat/messages/<int:conv_id>", methods=["GET"])
@jwt_required()
def get_messages(conv_id):
    uid = int(get_jwt_identity())
    page = max(1,int(request.args.get("page",1))); pp = min(50,int(request.args.get("per_page",30)))
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM conversations WHERE id=%s AND (user_a_id=%s OR user_b_id=%s)", (conv_id,uid,uid))
            if not cur.fetchone(): return err("Conversation not found.", 404)
            cur.execute("SELECT m.*,u.full_name as sender_name,u.profile_picture_url as sender_picture FROM messages m JOIN users u ON u.id=m.sender_id WHERE m.conversation_id=%s ORDER BY m.created_at DESC LIMIT %s OFFSET %s", (conv_id,pp,(page-1)*pp))
            msgs = cur.fetchall()
            for m in msgs:
                if m.get("created_at"): m["created_at"] = str(m["created_at"])
            cur.execute("UPDATE messages SET is_read=1 WHERE conversation_id=%s AND sender_id!=%s", (conv_id,uid))
        return ok(list(reversed(msgs)), "Messages loaded.")
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

@app.route("/chat/messages", methods=["POST"])
@jwt_required()
def send_message():
    sender_id = int(get_jwt_identity())
    b = request.get_json(silent=True) or {}
    other_id = b.get("recipient_id"); content = (b.get("content","") or "").strip()
    if not other_id or not content: return err("recipient_id and content required.", 400)
    conn = DatabaseManager.connect()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT id FROM mentor_requests WHERE status='accepted' AND ((seeker_id=%s AND mentor_id=%s) OR (seeker_id=%s AND mentor_id=%s))", (sender_id,other_id,other_id,sender_id))
            if not cur.fetchone(): return err("Chat only available with accepted mentor/mentee.", 403)
            ua = min(sender_id,other_id); ub = max(sender_id,other_id)
            cur.execute("SELECT id FROM conversations WHERE user_a_id=%s AND user_b_id=%s", (ua,ub))
            cv = cur.fetchone()
            if cv: conv_id = cv["id"]
            else:
                cur.execute("INSERT INTO conversations (user_a_id,user_b_id) VALUES (%s,%s)", (ua,ub))
                conv_id = conn.insert_id()
            cur.execute("INSERT INTO messages (conversation_id,sender_id,content) VALUES (%s,%s,%s)", (conv_id,sender_id,content))
            msg_id = conn.insert_id()
            cur.execute("UPDATE conversations SET last_message=%s,last_message_at=NOW() WHERE id=%s", (content[:100],conv_id))
            cur.execute("SELECT full_name FROM users WHERE id=%s", (sender_id,))
            s = cur.fetchone(); sname = (s["full_name"] if s else None) or "Someone"
            cur.execute("INSERT INTO notifications (user_id,sender_id,type,title,body,reference_id) VALUES (%s,%s,'new_message',%s,%s,%s)", (other_id,sender_id,f"New message from {sname}",content[:80],msg_id))
        return ok({"message_id":msg_id,"conversation_id":conv_id}, "Message sent.", 201)
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

# ── SEARCH ────────────────────────────────────────────────────────────────────
@app.route("/search", methods=["GET"])
@jwt_required()
def search():
    q = (request.args.get("q","") or "").strip()
    kind = request.args.get("kind","all")
    page = max(1,int(request.args.get("page",1))); pp = min(20,int(request.args.get("per_page",10)))
    if not q or len(q)<2: return err("Query min 2 chars.", 400)
    like = f"%{q}%"; offset = (page-1)*pp
    conn = DatabaseManager.connect(); results = {"mentors":[],"seekers":[]}
    try:
        with conn.cursor() as cur:
            if kind in ("all","mentors"):
                cur.execute("SELECT u.id,u.full_name,u.profile_picture_url,mp.headline,mp.current_job_title,mp.current_company,mp.expertise_areas,mp.is_accepting_mentees,'mentor' as type FROM mentor_profiles mp JOIN users u ON u.id=mp.user_id WHERE u.is_active=1 AND (u.full_name LIKE %s OR mp.headline LIKE %s OR mp.current_job_title LIKE %s OR mp.current_company LIKE %s) LIMIT %s OFFSET %s", (like,like,like,like,pp,offset))
                results["mentors"] = cur.fetchall()
            if kind in ("all","seekers"):
                cur.execute("SELECT u.id,u.full_name,u.profile_picture_url,js.headline,js.current_job_title,js.desired_job_title,'job_seeker' as type FROM job_seekers js JOIN users u ON u.id=js.user_id WHERE u.is_active=1 AND u.role='job_seeker' AND (u.full_name LIKE %s OR js.headline LIKE %s OR js.current_job_title LIKE %s OR js.desired_job_title LIKE %s) LIMIT %s OFFSET %s", (like,like,like,like,pp,offset))
                results["seekers"] = cur.fetchall()
        return ok(results, f"Results for '{q}'.")
    except Exception as e: app.logger.error(e); return err("Unexpected error.", 500)
    finally: conn.close()

if __name__ == "__main__":
    print("─"*50)
    print("  Career Navigator API — v3")
    print(f"  DB connected : {DatabaseManager.test()}")
    print(f"  Brevo ready  : {bool(EmailService._key)}")
    print("─"*50)
    app.run(debug=False, host="0.0.0.0", port=5000)