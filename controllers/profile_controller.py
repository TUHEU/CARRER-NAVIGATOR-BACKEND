from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models.user_model import UserModel, JobSeekerModel, MentorModel
from models.base_model import DatabaseConnection


class ProfileController:
    """Profile controller - Encapsulation"""
    
    def __init__(self):
        self._user_model = UserModel()
        self._job_seeker_model = JobSeekerModel()
        self._mentor_model = MentorModel()
        self._db = DatabaseConnection()
    
    @jwt_required()
    def get_profile(self):
        user_id = int(get_jwt_identity())
        profile = self._user_model.get_full_profile(user_id)
        
        if not profile:
            return jsonify({'success': False, 'message': 'User not found'}), 404
        
        # Format dates
        if profile.get('date_of_birth'):
            profile['date_of_birth'] = str(profile['date_of_birth'])
        
        # Ensure profile_picture_url is present
        if not profile.get('profile_picture_url'):
            profile['profile_picture_url'] = None
        
        return jsonify({'success': True, 'data': profile}), 200
    
    @jwt_required()
    def setup_profile(self):
        user_id = int(get_jwt_identity())
        data = request.get_json(silent=True) or {}
        
        full_name = (data.get('full_name', '') or '').strip()
        dob = data.get('date_of_birth', '') or None
        role = data.get('role', '') or ''
        
        if not full_name:
            return jsonify({'success': False, 'message': 'Full name required'}), 400
        
        if role and role not in ['job_seeker', 'mentor']:
            return jsonify({'success': False, 'message': 'Invalid role'}), 400
        
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                if role:
                    cur.execute(
                        "UPDATE users SET full_name = %s, date_of_birth = %s, role = %s, role_selected = 1 WHERE id = %s",
                        (full_name, dob, role, user_id)
                    )
                    
                    if role == 'mentor':
                        cur.execute(
                            "INSERT IGNORE INTO mentor_profiles (user_id) VALUES (%s)",
                            (user_id,)
                        )
                    cur.execute(
                        "INSERT IGNORE INTO job_seekers (user_id) VALUES (%s)",
                        (user_id,)
                    )
                else:
                    cur.execute(
                        "UPDATE users SET full_name = %s, date_of_birth = %s WHERE id = %s",
                        (full_name, dob, user_id)
                    )
        
        return jsonify({'success': True, 'message': 'Profile updated'}), 200
    
    @jwt_required()
    def update_profile_picture(self):
        user_id = int(get_jwt_identity())
        data = request.get_json(silent=True) or {}
        picture_url = (data.get('picture_url', '') or '').strip()
        
        if not picture_url:
            return jsonify({'success': False, 'message': 'picture_url required'}), 400
        
        self._user_model.update(user_id, {'profile_picture_url': picture_url})
        return jsonify({'success': True, 'message': 'Profile picture updated'}), 200
    
    @jwt_required()
    def update_job_seeker(self):
        user_id = int(get_jwt_identity())
        data = request.get_json(silent=True) or {}
        
        allowed_fields = ['headline', 'bio', 'phone', 'location', 'years_of_experience',
                         'current_job_title', 'desired_job_title', 'skills', 'resume_url',
                         'linkedin_url', 'github_url', 'portfolio_url', 'availability',
                         'open_to_remote', 'desired_salary', 'salary_currency', 'notice_period', 'interests']
        
        updates = {k: data[k] for k in allowed_fields if k in data}
        
        if not updates:
            return jsonify({'success': False, 'message': 'No fields to update'}), 400
        
        self._job_seeker_model.create_or_update(user_id, updates)
        return jsonify({'success': True, 'message': 'Profile updated'}), 200
    
    @jwt_required()
    def update_mentor(self):
        user_id = int(get_jwt_identity())
        data = request.get_json(silent=True) or {}
        
        allowed_fields = ['headline', 'bio', 'phone', 'location', 'years_of_experience',
                         'current_company', 'current_job_title', 'expertise_areas',
                         'industries', 'advice_topics', 'mentoring_style', 'session_price',
                         'currency', 'availability_days', 'availability_time_from',
                         'availability_time_to', 'max_mentees', 'is_accepting_mentees',
                         'linkedin_url', 'github_url', 'portfolio_url', 'website_url']
        
        updates = {k: data[k] for k in allowed_fields if k in data}
        
        if not updates:
            return jsonify({'success': False, 'message': 'No fields to update'}), 400
        
        # Convert expertise_areas to JSON if it's a list
        if 'expertise_areas' in updates and isinstance(updates['expertise_areas'], list):
            import json
            updates['expertise_areas'] = json.dumps(updates['expertise_areas'])
        
        self._mentor_model.create_or_update(user_id, updates)
        return jsonify({'success': True, 'message': 'Mentor profile updated'}), 200
    
    @jwt_required()
    def get_education(self):
        user_id = int(get_jwt_identity())
        
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT * FROM education WHERE user_id = %s ORDER BY start_year DESC",
                    (user_id,)
                )
                education = cur.fetchall()
        
        return jsonify({'success': True, 'data': education}), 200
    
    @jwt_required()
    def add_education(self):
        user_id = int(get_jwt_identity())
        data = request.get_json(silent=True) or {}
        
        required = ['institution', 'degree', 'field_of_study', 'start_year']
        for field in required:
            if field not in data or not data[field]:
                return jsonify({'success': False, 'message': f'{field} required'}), 400
        
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO education (user_id, institution, degree, field_of_study, 
                       start_year, end_year, is_current, description)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s)""",
                    (user_id, data['institution'], data['degree'], data['field_of_study'],
                     data['start_year'], data.get('end_year'), data.get('is_current', 0),
                     data.get('description', ''))
                )
                edu_id = cur.lastrowid
        
        return jsonify({'success': True, 'message': 'Education added', 'id': edu_id}), 201
    
    @jwt_required()
    def update_education(self, edu_id):
        user_id = int(get_jwt_identity())
        data = request.get_json(silent=True) or {}
        
        allowed = ['institution', 'degree', 'field_of_study', 'start_year', 'end_year', 'is_current', 'description']
        updates = {k: data[k] for k in allowed if k in data}
        
        if not updates:
            return jsonify({'success': False, 'message': 'No fields to update'}), 400
        
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE education SET {', '.join([f'{k}=%s' for k in updates.keys()])} WHERE id = %s AND user_id = %s",
                    list(updates.values()) + [edu_id, user_id]
                )
        
        return jsonify({'success': True, 'message': 'Education updated'}), 200
    
    @jwt_required()
    def delete_education(self, edu_id):
        user_id = int(get_jwt_identity())
        
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM education WHERE id = %s AND user_id = %s",
                    (edu_id, user_id)
                )
        
        return jsonify({'success': True, 'message': 'Education deleted'}), 200
    
    @jwt_required()
    def get_work_experience(self):
        user_id = int(get_jwt_identity())
        
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
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
        
        return jsonify({'success': True, 'data': work}), 200
    
    @jwt_required()
    def add_work_experience(self):
        user_id = int(get_jwt_identity())
        data = request.get_json(silent=True) or {}
        
        required = ['company', 'job_title', 'start_date']
        for field in required:
            if field not in data or not data[field]:
                return jsonify({'success': False, 'message': f'{field} required'}), 400
        
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """INSERT INTO work_experience (user_id, company, job_title, employment_type,
                       location, start_date, end_date, is_current, description)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (user_id, data['company'], data['job_title'], data.get('employment_type', 'full_time'),
                     data.get('location'), data['start_date'], data.get('end_date'),
                     data.get('is_current', 0), data.get('description', ''))
                )
                work_id = cur.lastrowid
        
        return jsonify({'success': True, 'message': 'Work experience added', 'id': work_id}), 201
    
    @jwt_required()
    def update_work_experience(self, work_id):
        user_id = int(get_jwt_identity())
        data = request.get_json(silent=True) or {}
        
        allowed = ['company', 'job_title', 'employment_type', 'location', 'start_date', 'end_date', 'is_current', 'description']
        updates = {k: data[k] for k in allowed if k in data}
        
        if not updates:
            return jsonify({'success': False, 'message': 'No fields to update'}), 400
        
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE work_experience SET {', '.join([f'{k}=%s' for k in updates.keys()])} WHERE id = %s AND user_id = %s",
                    list(updates.values()) + [work_id, user_id]
                )
        
        return jsonify({'success': True, 'message': 'Work experience updated'}), 200
    
    @jwt_required()
    def delete_work_experience(self, work_id):
        user_id = int(get_jwt_identity())
        
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM work_experience WHERE id = %s AND user_id = %s",
                    (work_id, user_id)
                )
        
        return jsonify({'success': True, 'message': 'Work experience deleted'}), 200