from functools import wraps
from flask import jsonify
from flask_jwt_extended import verify_jwt_in_request, get_jwt_identity


def admin_required(fn):
    """Decorator to require admin role"""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        user_id = int(get_jwt_identity())
        
        from models.user_model import UserModel
        user = UserModel().find_by_id(user_id)
        
        if not user or user.get('role') != 'admin':
            return jsonify({'success': False, 'message': 'Admin access required'}), 403
        
        return fn(*args, **kwargs)
    return wrapper


def mentor_required(fn):
    """Decorator to require mentor role"""
    @wraps(fn)
    def wrapper(*args, **kwargs):
        verify_jwt_in_request()
        user_id = int(get_jwt_identity())
        
        from models.user_model import UserModel
        user = UserModel().find_by_id(user_id)
        
        if not user or user.get('role') not in ['mentor', 'admin']:
            return jsonify({'success': False, 'message': 'Mentor access required'}), 403
        
        return fn(*args, **kwargs)
    return wrapper