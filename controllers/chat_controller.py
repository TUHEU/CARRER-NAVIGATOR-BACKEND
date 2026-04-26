from flask import request, jsonify
from flask_jwt_extended import jwt_required, get_jwt_identity
from models.chat_model import ConversationModel, MessageModel
from models.user_model import UserModel
from services.notification_service import NotificationService
from models.base_model import DatabaseConnection


class ChatController:
    """Chat controller - Handles conversations and messages"""
    
    def __init__(self):
        self._conversation_model = ConversationModel()
        self._message_model = MessageModel()
        self._user_model = UserModel()
        self._notification_service = NotificationService()
        self._db = DatabaseConnection()
    
    @jwt_required()
    def get_conversations(self):
        user_id = int(get_jwt_identity())
        conversations = self._conversation_model.get_user_conversations(user_id)
        return jsonify({'success': True, 'data': conversations}), 200
    
    @jwt_required()
    def get_messages(self, conversation_id):
        user_id = int(get_jwt_identity())
        page = max(1, int(request.args.get('page', 1)))
        per_page = min(50, int(request.args.get('per_page', 30)))
        
        # Verify user belongs to conversation
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM conversations WHERE id = %s AND (user_a_id = %s OR user_b_id = %s)",
                    (conversation_id, user_id, user_id)
                )
                if not cur.fetchone():
                    return jsonify({'success': False, 'message': 'Conversation not found'}), 404
        
        messages = self._message_model.get_messages(conversation_id, page, per_page)
        
        # Mark messages as read
        self._message_model.mark_as_read(conversation_id, user_id)
        
        return jsonify({'success': True, 'data': messages}), 200
    
    @jwt_required()
    def send_message(self):
        sender_id = int(get_jwt_identity())
        data = request.get_json(silent=True) or {}
        recipient_id = data.get('recipient_id')
        content = (data.get('content', '') or '').strip()
        
        if not recipient_id or not content:
            return jsonify({'success': False, 'message': 'recipient_id and content required'}), 400
        
        # Check if users have an accepted mentorship connection
        with self._db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id FROM mentor_requests 
                    WHERE status = 'accepted' 
                    AND ((seeker_id = %s AND mentor_id = %s) OR (seeker_id = %s AND mentor_id = %s))
                """, (sender_id, recipient_id, recipient_id, sender_id))
                
                if not cur.fetchone():
                    # Check if admin is involved
                    cur.execute(
                        "SELECT role FROM users WHERE id IN (%s, %s) AND role = 'admin'",
                        (sender_id, recipient_id)
                    )
                    if not cur.fetchone():
                        return jsonify({
                            'success': False, 
                            'message': 'Chat only available with accepted mentor/mentee connections'
                        }), 403
        
        # Get or create conversation
        conversation_id = self._conversation_model.get_or_create(sender_id, recipient_id)
        
        # Send message
        message_id = self._message_model.send_message(conversation_id, sender_id, content)
        
        # Get sender name for notification
        sender = self._user_model.find_by_id(sender_id)
        sender_name = sender.get('full_name') or 'Someone'
        
        # Notify recipient
        self._notification_service.notify_new_message(
            recipient_id, sender_id, sender_name, content, conversation_id
        )
        
        return jsonify({
            'success': True,
            'message': 'Message sent',
            'data': {
                'message_id': message_id,
                'conversation_id': conversation_id
            }
        }), 201