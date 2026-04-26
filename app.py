"""Career Navigator API - Complete OOP Backend"""

from flask import Flask, jsonify
from flask_cors import CORS
from flask_bcrypt import Bcrypt
from flask_jwt_extended import JWTManager
from datetime import timedelta
import os
from dotenv import load_dotenv

from config import config
from controllers.auth_controller import AuthController
from controllers.profile_controller import ProfileController
from controllers.mentor_controller import MentorController
from controllers.job_controller import JobController
from controllers.chat_controller import ChatController
from controllers.notification_controller import NotificationController
from controllers.search_controller import SearchController
from models.base_model import DatabaseManager

load_dotenv()

# Initialize Flask app
app = Flask(__name__)
CORS(app, resources={r"/*": {"origins": "*"}})

# Configuration
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET', 'super-secret-key-change-in-production')
app.config['JWT_ACCESS_TOKEN_EXPIRES'] = timedelta(hours=2)
app.config['JWT_REFRESH_TOKEN_EXPIRES'] = timedelta(days=30)

# Initialize extensions
bcrypt = Bcrypt(app)
jwt = JWTManager(app)

# Initialize controllers
auth_controller = AuthController()
profile_controller = ProfileController()
mentor_controller = MentorController()
job_controller = JobController()
chat_controller = ChatController()
notification_controller = NotificationController()
search_controller = SearchController()


# =============================================
# AUTH ROUTES
# =============================================
@app.route('/auth/register', methods=['POST'])
def register():
    return auth_controller.register()

@app.route('/auth/verify-email', methods=['POST'])
def verify_email():
    return auth_controller.verify_email()

@app.route('/auth/resend-code', methods=['POST'])
def resend_code():
    return auth_controller.resend_code()

@app.route('/auth/login', methods=['POST'])
def login():
    return auth_controller.login()

@app.route('/auth/forgot-password', methods=['POST'])
def forgot_password():
    return auth_controller.forgot_password()

@app.route('/auth/reset-password', methods=['POST'])
def reset_password():
    return auth_controller.reset_password()

@app.route('/auth/logout', methods=['POST'])
def logout():
    return auth_controller.logout()

@app.route('/auth/delete-account', methods=['DELETE'])
def delete_account():
    return auth_controller.delete_account()


# =============================================
# PROFILE ROUTES
# =============================================
@app.route('/profile/me', methods=['GET'])
def get_profile():
    return profile_controller.get_profile()

@app.route('/profile/setup', methods=['PUT'])
def setup_profile():
    return profile_controller.setup_profile()

@app.route('/profile/picture', methods=['PUT'])
def update_picture():
    return profile_controller.update_profile_picture()

@app.route('/profile/job-seeker', methods=['PUT'])
def update_job_seeker():
    return profile_controller.update_job_seeker()

@app.route('/profile/mentor', methods=['PUT'])
def update_mentor():
    return profile_controller.update_mentor()

# Education routes
@app.route('/profile/education', methods=['GET'])
def get_education():
    return profile_controller.get_education()

@app.route('/profile/education', methods=['POST'])
def add_education():
    return profile_controller.add_education()

@app.route('/profile/education/<int:edu_id>', methods=['PUT'])
def update_education(edu_id):
    return profile_controller.update_education(edu_id)

@app.route('/profile/education/<int:edu_id>', methods=['DELETE'])
def delete_education(edu_id):
    return profile_controller.delete_education(edu_id)

# Work experience routes
@app.route('/profile/work-experience', methods=['GET'])
def get_work_experience():
    return profile_controller.get_work_experience()

@app.route('/profile/work-experience', methods=['POST'])
def add_work_experience():
    return profile_controller.add_work_experience()

@app.route('/profile/work-experience/<int:work_id>', methods=['PUT'])
def update_work_experience(work_id):
    return profile_controller.update_work_experience(work_id)

@app.route('/profile/work-experience/<int:work_id>', methods=['DELETE'])
def delete_work_experience(work_id):
    return profile_controller.delete_work_experience(work_id)


# =============================================
# MENTOR ROUTES
# =============================================
@app.route('/mentors', methods=['GET'])
def list_mentors():
    return mentor_controller.list_mentors()

@app.route('/mentors/<int:mentor_id>', methods=['GET'])
def get_mentor_details(mentor_id):
    return mentor_controller.get_mentor_details(mentor_id)

@app.route('/requests', methods=['POST'])
def send_request():
    return mentor_controller.send_request()

@app.route('/requests', methods=['GET'])
def get_requests():
    return mentor_controller.get_requests()

@app.route('/requests/<int:request_id>/respond', methods=['PUT'])
def respond_to_request(request_id):
    return mentor_controller.respond_to_request(request_id)

@app.route('/mentors/user/<int:user_id>/background', methods=['GET'])
def get_user_background(user_id):
    return mentor_controller.get_user_background(user_id)


# =============================================
# JOB LISTING ROUTES
# =============================================
@app.route('/jobs', methods=['GET'])
def get_jobs():
    return job_controller.get_jobs()

@app.route('/jobs', methods=['POST'])
def create_job():
    return job_controller.create_job()

@app.route('/jobs/<int:job_id>', methods=['GET'])
def get_job_detail(job_id):
    return job_controller.get_job_detail(job_id)

@app.route('/jobs/<int:job_id>', methods=['PUT'])
def update_job(job_id):
    return job_controller.update_job(job_id)

@app.route('/jobs/<int:job_id>', methods=['DELETE'])
def delete_job(job_id):
    return job_controller.delete_job(job_id)

@app.route('/jobs/<int:job_id>/apply', methods=['POST'])
def apply_for_job(job_id):
    return job_controller.apply_for_job(job_id)

@app.route('/jobs/applications/my', methods=['GET'])
def get_my_applications():
    return job_controller.get_my_applications()

@app.route('/jobs/<int:job_id>/applications', methods=['GET'])
def get_applications(job_id):
    return job_controller.get_applications(job_id)

@app.route('/jobs/<int:job_id>/applications/<int:application_id>/status', methods=['PUT'])
def update_application_status(job_id, application_id):
    return job_controller.update_application_status(job_id, application_id)


# =============================================
# CHAT ROUTES
# =============================================
@app.route('/chat/conversations', methods=['GET'])
def get_conversations():
    return chat_controller.get_conversations()

@app.route('/chat/messages/<int:conversation_id>', methods=['GET'])
def get_messages(conversation_id):
    return chat_controller.get_messages(conversation_id)

@app.route('/chat/messages', methods=['POST'])
def send_message():
    return chat_controller.send_message()


# =============================================
# NOTIFICATION ROUTES
# =============================================
@app.route('/notifications', methods=['GET'])
def get_notifications():
    return notification_controller.get_notifications()

@app.route('/notifications/read', methods=['PUT'])
def mark_notifications_read():
    return notification_controller.mark_read()


# =============================================
# SEARCH ROUTE
# =============================================
@app.route('/search', methods=['GET'])
def search():
    return search_controller.search()


# =============================================
# HEALTH CHECK
# =============================================
@app.route('/health', methods=['GET'])
def health():
    return jsonify({
        'status': 'healthy',
        'database': DatabaseManager.test()
    }), 200


if __name__ == '__main__':
    print("─" * 50)
    print("  Career Navigator API — v4.0 (OOP Complete)")
    print(f"  Database connected: {DatabaseManager.test()}")
    print("─" * 50)
    app.run(debug=False, host='0.0.0.0', port=5000)