from flask import request, jsonify
from flask_jwt_extended import jwt_required
from models.base_model import DatabaseManager


class SearchController:
    """Search controller - Handles searching mentors and job seekers"""
    
    def __init__(self):
        self._db = DatabaseManager()
    
    @jwt_required()
    def search(self):
        query = (request.args.get('q', '') or '').strip()
        kind = request.args.get('kind', 'all')
        page = max(1, int(request.args.get('page', 1)))
        per_page = min(20, int(request.args.get('per_page', 10)))
        
        if len(query) < 2:
            return jsonify({
                'success': True,
                'data': {'mentors': [], 'seekers': []}
            }), 200
        
        like = f"%{query}%"
        offset = (page - 1) * per_page
        results = {'mentors': [], 'seekers': []}
        
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                # Search mentors
                if kind in ('all', 'mentors'):
                    cur.execute("""
                        SELECT u.id, u.full_name, u.email, u.profile_picture_url,
                               mp.headline, mp.current_job_title, mp.current_company,
                               mp.expertise_areas, mp.is_accepting_mentees,
                               'mentor' as role
                        FROM mentor_profiles mp
                        JOIN users u ON u.id = mp.user_id
                        WHERE u.is_active = 1 
                          AND (u.full_name LIKE %s 
                               OR mp.headline LIKE %s 
                               OR mp.current_job_title LIKE %s
                               OR mp.current_company LIKE %s)
                        LIMIT %s OFFSET %s
                    """, (like, like, like, like, per_page, offset))
                    
                    mentors = cur.fetchall()
                    for m in mentors:
                        if m.get('expertise_areas') and isinstance(m['expertise_areas'], str):
                            import json
                            try:
                                m['expertise_areas'] = json.loads(m['expertise_areas'])
                            except:
                                m['expertise_areas'] = []
                    results['mentors'] = mentors
                
                # Search job seekers
                if kind in ('all', 'seekers'):
                    cur.execute("""
                        SELECT u.id, u.full_name, u.email, u.profile_picture_url,
                               js.headline, js.current_job_title, js.desired_job_title,
                               js.skills, js.availability,
                               'job_seeker' as role
                        FROM job_seekers js
                        JOIN users u ON u.id = js.user_id
                        WHERE u.is_active = 1 AND u.role = 'job_seeker'
                          AND (u.full_name LIKE %s 
                               OR js.headline LIKE %s 
                               OR js.current_job_title LIKE %s
                               OR js.desired_job_title LIKE %s)
                        LIMIT %s OFFSET %s
                    """, (like, like, like, like, per_page, offset))
                    
                    seekers = cur.fetchall()
                    for s in seekers:
                        if s.get('skills') and isinstance(s['skills'], str):
                            import json
                            try:
                                s['skills'] = json.loads(s['skills'])
                            except:
                                s['skills'] = []
                    results['seekers'] = seekers
        
        return jsonify({'success': True, 'data': results}), 200
