from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from services.notification_service import NotificationService


class NotificationController:
    """Notification controller"""
    
    def __init__(self):
        self._notification_service = NotificationService()
    
    @jwt_required()
    def get_notifications(self):
        user_id = int(get_jwt_identity())
        page = max(1, int(request.args.get('page', 1)))
        
        notifications, unread = self._notification_service.get_notifications(user_id, page)
        
        return jsonify({
            'success': True,
            'data': {
                'notifications': notifications,
                'unread': unread
            }
        }), 200
    
    @jwt_required()
    def mark_read(self):
        user_id = int(get_jwt_identity())
        data = request.get_json(silent=True) or {}
        ids = data.get('ids', [])
        
        self._notification_service.mark_read(user_id, ids if ids else None)
        
        return jsonify({'success': True, 'message': 'Notifications marked as read'}), 200
