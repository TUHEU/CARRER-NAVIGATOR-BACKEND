from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models.user_model import UserModel, MentorModel
from models.chat_model import ConversationModel
from services.email_service import EmailService
from services.notification_service import NotificationService
from models.base_model import DatabaseConnection


class MentorController:
    """Mentor controller - Handles mentor listing and requests"""
    
    def __init__(self):
        self._user_model = UserModel()
        self._mentor_model = MentorModel()
        self._conversation_model = ConversationModel()
        self._email_service = EmailService()
        self._notification_service = NotificationService()
        self._db = DatabaseConnection()
    
    @jwt_required()
    def list_mentors(self):
        expertise = request.args.get('expertise', '')
        page = max(1, int(request.args.get('page', 1)))
        per_page = min(20, int(request.args.get('per_page', 10)))
        
        mentors = self._mentor_model.list_mentors(expertise, page, per_page)
        return jsonify({'success': True, 'data': mentors}), 200
    
    @jwt_required()
    def get_mentor_details(self, mentor_id):
        mentor = self._user_model.get_full_profile(mentor_id)
        
        if not mentor or mentor.get('role') != 'mentor':
            return jsonify({'success': False, 'message': 'Mentor not found'}), 404
        
        return jsonify({'success': True, 'data': mentor}), 200
    
    @jwt_required()
    def send_request(self):
        seeker_id = int(get_jwt_identity())
        data = request.get_json(silent=True) or {}
        mentor_id = data.get('mentor_id')
        message = (data.get('message', '') or '').strip()
        
        if not mentor_id:
            return jsonify({'success': False, 'message': 'mentor_id required'}), 400
        
        # Check if user is job seeker
        user = self._user_model.find_by_id(seeker_id)
        if user['role'] != 'job_seeker':
            return jsonify({'success': False, 'message': 'Only job seekers can send requests'}), 403
        
        # Get mentor details
        mentor = self._user_model.find_by_id(mentor_id)
        if not mentor or mentor['role'] != 'mentor':
            return jsonify({'success': False, 'message': 'Mentor not found'}), 404
        
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                # Check for existing pending request
                cur.execute(
                    "SELECT id, status FROM mentor_requests WHERE seeker_id = %s AND mentor_id = %s",
                    (seeker_id, mentor_id)
                )
                existing = cur.fetchone()
                
                if existing:
                    if existing['status'] in ('pending', 'accepted'):
                        return jsonify({'success': False, 'message': f'Request already {existing["status"]}'}), 400
                    cur.execute(
                        "UPDATE mentor_requests SET status = 'pending', message = %s WHERE id = %s",
                        (message or None, existing['id'])
                    )
                    request_id = existing['id']
                else:
                    cur.execute(
                        "INSERT INTO mentor_requests (seeker_id, mentor_id, message) VALUES (%s, %s, %s)",
                        (seeker_id, mentor_id, message or None)
                    )
                    request_id = cur.lastrowid
        
        # Send notifications
        self._notification_service.notify_mentor_request(
            mentor_id, seeker_id, request_id, user['full_name'] or 'A job seeker'
        )
        self._email_service.send_mentor_request(mentor['email'], user['full_name'] or 'A job seeker')
        
        return jsonify({'success': True, 'message': 'Request sent', 'request_id': request_id}), 201
    
    @jwt_required()
    def get_requests(self):
        user_id = int(get_jwt_identity())
        user = self._user_model.find_by_id(user_id)
        
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                if user['role'] == 'mentor':
                    cur.execute("""
                        SELECT mr.*, u.full_name as seeker_name, u.profile_picture_url as seeker_picture
                        FROM mentor_requests mr
                        JOIN users u ON u.id = mr.seeker_id
                        WHERE mr.mentor_id = %s
                        ORDER BY mr.created_at DESC
                    """, (user_id,))
                else:
                    cur.execute("""
                        SELECT mr.*, u.full_name as mentor_name, u.profile_picture_url as mentor_picture,
                               mp.headline
                        FROM mentor_requests mr
                        JOIN users u ON u.id = mr.mentor_id
                        LEFT JOIN mentor_profiles mp ON mp.user_id = mr.mentor_id
                        WHERE mr.seeker_id = %s
                        ORDER BY mr.created_at DESC
                    """, (user_id,))
                
                requests = cur.fetchall()
                for r in requests:
                    if r.get('created_at'):
                        r['created_at'] = str(r['created_at'])
                    if r.get('updated_at'):
                        r['updated_at'] = str(r['updated_at'])
        
        return jsonify({'success': True, 'data': requests}), 200
    
    @jwt_required()
    def respond_to_request(self, request_id):
        mentor_id = int(get_jwt_identity())
        data = request.get_json(silent=True) or {}
        action = (data.get('action', '') or '').strip()
        
        if action not in ['accept', 'reject']:
            return jsonify({'success': False, 'message': 'action must be accept or reject'}), 400
        
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id, seeker_id FROM mentor_requests WHERE id = %s AND mentor_id = %s AND status = 'pending'",
                    (request_id, mentor_id)
                )
                request = cur.fetchone()
                
                if not request:
                    return jsonify({'success': False, 'message': 'Request not found or not pending'}), 404
                
                new_status = 'accepted' if action == 'accept' else 'rejected'
                cur.execute(
                    "UPDATE mentor_requests SET status = %s WHERE id = %s",
                    (new_status, request_id)
                )
                
                # Get mentor name for notification
                cur.execute("SELECT full_name FROM users WHERE id = %s", (mentor_id,))
                mentor = cur.fetchone()
        
        # Send notification to seeker
        self._notification_service.notify_request_response(
            request['seeker_id'], mentor_id, request_id,
            mentor['full_name'] or 'Mentor', action == 'accept'
        )
        
        # If accepted, ensure conversation exists (trigger will handle)
        if action == 'accept':
            with self._db.get_connection() as conn:
                with conn.cursor() as cur:
                    # Get or create conversation
                    ua, ub = min(request['seeker_id'], mentor_id), max(request['seeker_id'], mentor_id)
                    cur.execute(
                        "SELECT id FROM conversations WHERE user_a_id = %s AND user_b_id = %s",
                        (ua, ub)
                    )
                    conv = cur.fetchone()
                    
                    if conv:
                        conversation_id = conv['id']
                    else:
                        cur.execute(
                            "INSERT INTO conversations (user_a_id, user_b_id) VALUES (%s, %s)",
                            (ua, ub)
                        )
                        conversation_id = cur.lastrowid
                    
                    cur.execute(
                        "UPDATE mentor_requests SET conversation_id = %s WHERE id = %s",
                        (conversation_id, request_id)
                    )
        
        return jsonify({'success': True, 'message': f'Request {new_status}'}), 200
    
    @jwt_required()
    def get_user_background(self, user_id):
        current_user_id = int(get_jwt_identity())
        
        # Check if they have an accepted mentorship connection
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id FROM mentor_requests 
                    WHERE status = 'accepted' 
                    AND ((seeker_id = %s AND mentor_id = %s) OR (seeker_id = %s AND mentor_id = %s))
                """, (current_user_id, user_id, user_id, current_user_id))
                
                if not cur.fetchone():
                    return jsonify({'success': False, 'message': 'No accepted connection'}), 403
                
                # Get education
                cur.execute(
                    "SELECT * FROM education WHERE user_id = %s ORDER BY start_year DESC",
                    (user_id,)
                )
                education = cur.fetchall()
                
                # Get work experience
                cur.execute(
                    "SELECT * FROM work_experience WHERE user_id = %s ORDER BY start_date DESC",
                    (user_id,)
                )
                work = cur.fetchall()
                for w in work:
                    if w.get('start_date'):
                        w['start_date'] = str(w['start_date'])
                    if w.get('end_date'):
                        w['end_date'] = str(w['end_date'])
        
        return jsonify({
            'success': True,
            'data': {
                'education': education,
                'work_experience': work
            }
        }), 200