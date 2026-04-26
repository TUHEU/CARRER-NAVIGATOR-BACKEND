from models.base_model import BaseModel


class NotificationModel(BaseModel):
    """Notification model"""
    
    def get_table_name(self) -> str:
        return 'notifications'
    
    def create_notification(self, user_id: int, type: str, title: str, body: str = None, 
                           sender_id: int = None, reference_id: int = None) -> int:
        return self.create({
            'user_id': user_id,
            'sender_id': sender_id,
            'type': type,
            'title': title,
            'body': body,
            'reference_id': reference_id
        })
    
    def get_user_notifications(self, user_id: int, page: int = 1, per_page: int = 20):
        offset = (page - 1) * per_page
        
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT n.*, u.full_name as sender_name, u.profile_picture_url as sender_picture
                    FROM notifications n
                    LEFT JOIN users u ON u.id = n.sender_id
                    WHERE n.user_id = %s
                    ORDER BY n.created_at DESC
                    LIMIT %s OFFSET %s
                """, (user_id, per_page, offset))
                
                notifs = cur.fetchall()
                for n in notifs:
                    if n.get('created_at'):
                        n['created_at'] = str(n['created_at'])
                
                cur.execute(
                    "SELECT COUNT(*) as unread FROM notifications WHERE user_id = %s AND is_read = 0",
                    (user_id,)
                )
                unread = cur.fetchone()['unread']
                
                return notifs, unread
    
    def mark_as_read(self, user_id: int, notification_ids: list = None):
        with self.db.get_connection() as conn:
            with conn.cursor() as cur:
                if notification_ids:
                    placeholders = ','.join(['%s'] * len(notification_ids))
                    cur.execute(
                        f"UPDATE notifications SET is_read = 1 WHERE user_id = %s AND id IN ({placeholders})",
                        [user_id] + notification_ids
                    )
                else:
                    cur.execute(
                        "UPDATE notifications SET is_read = 1 WHERE user_id = %s AND is_read = 0",
                        (user_id,)
                    )


class NotificationService:
    """Notification service facade"""
    
    def __init__(self):
        self._model = NotificationModel()
    
    def notify_mentor_request(self, mentor_id: int, seeker_id: int, request_id: int, seeker_name: str):
        return self._model.create_notification(
            user_id=mentor_id,
            sender_id=seeker_id,
            type='mentor_request',
            title='New Mentorship Request',
            body=f'{seeker_name} wants you as their mentor',
            reference_id=request_id
        )
    
    def notify_request_response(self, seeker_id: int, mentor_id: int, request_id: int, 
                               mentor_name: str, accepted: bool):
        if accepted:
            return self._model.create_notification(
                user_id=seeker_id,
                sender_id=mentor_id,
                type='request_accepted',
                title='Request Accepted! 🎉',
                body=f'{mentor_name} has accepted your mentorship request',
                reference_id=request_id
            )
        else:
            return self._model.create_notification(
                user_id=seeker_id,
                sender_id=mentor_id,
                type='request_rejected',
                title='Mentorship Request Declined',
                body=f'{mentor_name} has declined your request',
                reference_id=request_id
            )
    
    def notify_new_message(self, recipient_id: int, sender_id: int, sender_name: str, 
                          message_preview: str, conversation_id: int):
        return self._model.create_notification(
            user_id=recipient_id,
            sender_id=sender_id,
            type='new_message',
            title=f'New message from {sender_name}',
            body=message_preview[:80],
            reference_id=conversation_id
        )
    
    def notify_job_alert(self, user_id: int, job_title: str, company: str, job_id: int):
        return self._model.create_notification(
            user_id=user_id,
            type='job_alert',
            title='New Job Match!',
            body=f'{job_title} at {company} matches your profile',
            reference_id=job_id
        )
    
    def get_notifications(self, user_id: int, page: int = 1):
        return self._model.get_user_notifications(user_id, page)
    
    def mark_read(self, user_id: int, ids: list = None):
        return self._model.mark_as_read(user_id, ids)