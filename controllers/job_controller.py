from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models.job_model import JobListingModel
from models.user_model import UserModel
from services.notification_service import NotificationService
from middleware.auth_middleware import admin_required
from models.base_model import DatabaseConnection


class JobController:
    """Job listing controller - Admin and user job management"""
    
    def __init__(self):
        self._job_model = JobListingModel()
        self._user_model = UserModel()
        self._notification_service = NotificationService()
        self._db = DatabaseConnection()
    
    @jwt_required()
    @admin_required
    def create_job(self):
        """Admin: Create a new job listing"""
        admin_id = int(get_jwt_identity())
        data = request.get_json(silent=True) or {}
        
        required = ['title', 'company', 'location', 'description', 'requirements', 'responsibilities']
        for field in required:
            if field not in data or not data[field]:
                return jsonify({'success': False, 'message': f'{field} required'}), 400
        
        job_data = {
            'title': data['title'],
            'company': data['company'],
            'company_logo': data.get('company_logo'),
            'location': data['location'],
            'location_type': data.get('location_type', 'onsite'),
            'employment_type': data.get('employment_type', 'full_time'),
            'experience_level': data.get('experience_level', 'mid'),
            'salary_min': data.get('salary_min'),
            'salary_max': data.get('salary_max'),
            'salary_currency': data.get('salary_currency', 'USD'),
            'description': data['description'],
            'requirements': data['requirements'],
            'responsibilities': data['responsibilities'],
            'benefits': data.get('benefits'),
            'skills_required': data.get('skills_required'),
            'posted_by': admin_id,
            'expires_at': data.get('expires_at')
        }
        
        job_id = self._job_model.create_job(job_data)
        return jsonify({'success': True, 'message': 'Job created', 'job_id': job_id}), 201
    
    @jwt_required()
    @admin_required
    def update_job(self, job_id):
        """Admin: Update a job listing"""
        data = request.get_json(silent=True) or {}
        
        allowed = ['title', 'company', 'company_logo', 'location', 'location_type',
                  'employment_type', 'experience_level', 'salary_min', 'salary_max',
                  'salary_currency', 'description', 'requirements', 'responsibilities',
                  'benefits', 'skills_required', 'expires_at']
        
        updates = {k: data[k] for k in allowed if k in data}
        
        if not updates:
            return jsonify({'success': False, 'message': 'No fields to update'}), 400
        
        self._job_model.update_job(job_id, updates)
        return jsonify({'success': True, 'message': 'Job updated'}), 200
    
    @jwt_required()
    @admin_required
    def delete_job(self, job_id):
        """Admin: Delete (soft delete) a job listing"""
        self._job_model.delete_job(job_id)
        return jsonify({'success': True, 'message': 'Job deleted'}), 200
    
    @jwt_required()
    def get_jobs(self):
        """Get all active job listings"""
        page = max(1, int(request.args.get('page', 1)))
        per_page = min(20, int(request.args.get('per_page', 10)))
        
        filters = {
            'location': request.args.get('location'),
            'employment_type': request.args.get('employment_type'),
            'search': request.args.get('search')
        }
        filters = {k: v for k, v in filters.items() if v}
        
        jobs = self._job_model.get_active_jobs(filters, page, per_page)
        return jsonify({'success': True, 'data': jobs}), 200
    
    @jwt_required()
    def get_job_detail(self, job_id):
        """Get job listing details"""
        job = self._job_model.find_by_id(job_id)
        
        if not job or not job.get('is_active'):
            return jsonify({'success': False, 'message': 'Job not found'}), 404
        
        if job.get('created_at'):
            job['created_at'] = str(job['created_at'])
        
        return jsonify({'success': True, 'data': job}), 200
    
    @jwt_required()
    def apply_for_job(self, job_id):
        """User: Apply for a job"""
        user_id = int(get_jwt_identity())
        data = request.get_json(silent=True) or {}
        
        cover_letter = data.get('cover_letter')
        resume_url = data.get('resume_url')
        
        # Check if job exists and is active
        job = self._job_model.find_by_id(job_id)
        if not job or not job.get('is_active'):
            return jsonify({'success': False, 'message': 'Job not found'}), 404
        
        result = self._job_model.apply_for_job(job_id, user_id, cover_letter, resume_url)
        
        if not result:
            return jsonify({'success': False, 'message': 'Already applied'}), 400
        
        # Notify admin (optional)
        # Could also notify job poster
        
        return jsonify({'success': True, 'message': 'Application submitted'}), 201
    
    @jwt_required()
    def get_my_applications(self):
        """User: Get all job applications"""
        user_id = int(get_jwt_identity())
        applications = self._job_model.get_user_applications(user_id)
        return jsonify({'success': True, 'data': applications}), 200
    
    @jwt_required()
    @admin_required
    def get_applications(self, job_id):
        """Admin: Get all applications for a job"""
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT a.*, u.full_name, u.email, u.profile_picture_url
                    FROM job_applications a
                    JOIN users u ON u.id = a.user_id
                    WHERE a.job_id = %s
                    ORDER BY a.applied_at DESC
                """, (job_id,))
                apps = cur.fetchall()
                
                for app in apps:
                    if app.get('applied_at'):
                        app['applied_at'] = str(app['applied_at'])
        
        return jsonify({'success': True, 'data': apps}), 200
    
    @jwt_required()
    @admin_required
    def update_application_status(self, job_id, application_id):
        """Admin: Update application status"""
        data = request.get_json(silent=True) or {}
        status = data.get('status')
        
        valid_statuses = ['pending', 'reviewed', 'shortlisted', 'rejected', 'hired']
        if status not in valid_statuses:
            return jsonify({'success': False, 'message': f'Invalid status. Must be one of: {valid_statuses}'}), 400
        
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE job_applications SET status = %s WHERE id = %s AND job_id = %s",
                    (status, application_id, job_id)
                )
                
                # Get user_id for notification
                cur.execute(
                    "SELECT user_id FROM job_applications WHERE id = %s",
                    (application_id,)
                )
                app = cur.fetchone()
                
                if app:
                    self._notification_service.create_notification(
                        user_id=app['user_id'],
                        type='system',
                        title='Application Status Updated',
                        body=f'Your application status has been updated to {status}'
                    )
        
        return jsonify({'success': True, 'message': 'Status updated'}), 200