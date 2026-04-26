from models.base_model import BaseModel


class ConversationModel(BaseModel):
    """Conversation model"""
    
    def get_table_name(self) -> str:
        return 'conversations'
    
    def get_or_create(self, user_a: int, user_b: int) -> int:
        """Get existing conversation or create new one"""
        ua, ub = min(user_a, user_b), max(user_a, user_b)
        
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM conversations WHERE user_a_id = %s AND user_b_id = %s",
                    (ua, ub)
                )
                conv = cur.fetchone()
                
                if conv:
                    return conv['id']
                
                cur.execute(
                    "INSERT INTO conversations (user_a_id, user_b_id) VALUES (%s, %s)",
                    (ua, ub)
                )
                return cur.lastrowid
    
    def get_user_conversations(self, user_id: int):
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT c.*,
                           CASE WHEN c.user_a_id = %s THEN ub.full_name ELSE ua.full_name END as other_name,
                           CASE WHEN c.user_a_id = %s THEN ub.profile_picture_url ELSE ua.profile_picture_url END as other_picture,
                           CASE WHEN c.user_a_id = %s THEN c.user_b_id ELSE c.user_a_id END as other_user_id
                    FROM conversations c
                    JOIN users ua ON ua.id = c.user_a_id
                    JOIN users ub ON ub.id = c.user_b_id
                    WHERE c.user_a_id = %s OR c.user_b_id = %s
                    ORDER BY c.last_message_at DESC
                """, (user_id, user_id, user_id, user_id, user_id))
                
                convs = cur.fetchall()
                for conv in convs:
                    if conv.get('last_message_at'):
                        conv['last_message_at'] = str(conv['last_message_at'])
                    if conv.get('created_at'):
                        conv['created_at'] = str(conv['created_at'])
                
                return convs


class MessageModel(BaseModel):
    """Message model"""
    
    def get_table_name(self) -> str:
        return 'messages'
    
    def send_message(self, conversation_id: int, sender_id: int, content: str) -> int:
        return self.create({
            'conversation_id': conversation_id,
            'sender_id': sender_id,
            'content': content
        })
    
    def get_messages(self, conversation_id: int, page: int = 1, per_page: int = 30):
        offset = (page - 1) * per_page
        
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT m.*, u.full_name as sender_name, u.profile_picture_url as sender_picture
                    FROM messages m
                    JOIN users u ON u.id = m.sender_id
                    WHERE m.conversation_id = %s
                    ORDER BY m.created_at ASC
                    LIMIT %s OFFSET %s
                """, (conversation_id, per_page, offset))
                
                messages = cur.fetchall()
                for msg in messages:
                    if msg.get('created_at'):
                        msg['created_at'] = str(msg['created_at'])
                
                return messages
    
    def mark_as_read(self, conversation_id: int, user_id: int):
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "UPDATE messages SET is_read = 1 WHERE conversation_id = %s AND sender_id != %s",
                    (conversation_id, user_id)
                )