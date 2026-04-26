from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from services.auth_service import AuthService
from services.notification_service import NotificationService


class AuthController:
    """Authentication controller - Encapsulation"""
    
    def __init__(self):
        self._auth_service = AuthService()
        self._notification_service = NotificationService()
    
    def register(self):
        data = request.get_json(silent=True) or {}
        email = (data.get('email', '') or '').strip().lower()
        password = data.get('password', '')
        
        if not email or '@' not in email:
            return jsonify({'success': False, 'message': 'Valid email required'}), 400
        
        if not password or len(password) < 6:
            return jsonify({'success': False, 'message': 'Password must be at least 6 characters'}), 400
        
        result = self._auth_service.register_user(email, password)
        status = 201 if result['success'] else 400
        return jsonify(result), status
    
    def verify_email(self):
        data = request.get_json(silent=True) or {}
        email = (data.get('email', '') or '').strip().lower()
        code = (data.get('code', '') or '').strip()
        
        if not email or not code:
            return jsonify({'success': False, 'message': 'Email and code required'}), 400
        
        result = self._auth_service.verify_email(email, code)
        status = 200 if result['success'] else 400
        return jsonify(result), status
    
    def resend_code(self):
        data = request.get_json(silent=True) or {}
        email = (data.get('email', '') or '').strip().lower()
        
        if not email:
            return jsonify({'success': False, 'message': 'Email required'}), 400
        
        result = self._auth_service.resend_verification(email)
        return jsonify(result), 200 if result['success'] else 400
    
    def login(self):
        data = request.get_json(silent=True) or {}
        email = (data.get('email', '') or '').strip().lower()
        password = data.get('password', '')
        
        if not email or not password:
            return jsonify({'success': False, 'message': 'Email and password required'}), 400
        
        result = self._auth_service.login(email, password)
        status = 200 if result['success'] else 401
        return jsonify(result), status
    
    def forgot_password(self):
        data = request.get_json(silent=True) or {}
        email = (data.get('email', '') or '').strip().lower()
        
        if not email:
            return jsonify({'success': False, 'message': 'Email required'}), 400
        
        result = self._auth_service.forgot_password(email)
        return jsonify(result), 200
    
    def reset_password(self):
        data = request.get_json(silent=True) or {}
        email = (data.get('email', '') or '').strip().lower()
        code = (data.get('code', '') or '').strip()
        password = data.get('password', '')
        
        if not email or not code or not password:
            return jsonify({'success': False, 'message': 'Email, code, and password required'}), 400
        
        result = self._auth_service.reset_password(email, code, password)
        return jsonify(result), 200 if result['success'] else 400
    
    @jwt_required()
    def logout(self):
        # JWT is stateless, just return success
        return jsonify({'success': True, 'message': 'Logged out successfully'}), 200
    
    @jwt_required()
    def delete_account(self):
        user_id = int(get_jwt_identity())
        result = self._auth_service.delete_account(user_id)
        return jsonify(result), 200 if result['success'] else 400
