import random
import string
from datetime import datetime, timedelta
from flask_bcrypt import Bcrypt
from flask_jwt_extended import create_access_token, create_refresh_token
from models.user_model import UserModel
from services.email_service import EmailService


class AuthService:
    """Authentication service - Encapsulation"""
    
    def __init__(self):
        self._user_model = UserModel()
        self._email_service = EmailService()
        self._bcrypt = Bcrypt()
    
    def generate_otp(self, length: int = 6) -> str:
        return ''.join(random.choices(string.digits, k=length))
    
    def hash_password(self, password: str) -> str:
        return self._bcrypt.generate_password_hash(password).decode()
    
    def verify_password(self, password: str, password_hash: str) -> bool:
        return self._bcrypt.check_password_hash(password_hash, password)
    
    def create_tokens(self, user_id: int) -> dict:
        return {
            'access_token': create_access_token(identity=str(user_id)),
            'refresh_token': create_refresh_token(identity=str(user_id))
        }
    
    def register_user(self, email: str, password: str) -> dict:
        # Check if user exists
        existing = self._user_model.find_by_email(email)
        if existing:
            if existing['is_verified']:
                return {'success': False, 'message': 'Email already registered'}
            else:
                # Resend verification code
                return self.resend_verification(email)
        
        # Create new user
        password_hash = self.hash_password(password)
        user_id = self._user_model.create({
            'email': email.lower(),
            'password_hash': password_hash,
            'role': 'job_seeker',
            'is_verified': False
        })
        
        # Create initial job seeker profile
        from models.user_model import JobSeekerModel
        JobSeekerModel().create_or_update(user_id, {})
        
        # Send verification code
        code = self.generate_otp()
        with self._user_model.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO email_verification_codes (user_id, code, expires_at) VALUES (%s, %s, %s)",
                    (user_id, code, datetime.now() + timedelta(minutes=10))
                )
        
        self._email_service.send_verification(email, code)
        
        return {'success': True, 'message': 'Verification code sent', 'user_id': user_id}
    
    def verify_email(self, email: str, code: str) -> dict:
        user = self._user_model.find_by_email(email)
        if not user:
            return {'success': False, 'message': 'User not found'}
        
        if user['is_verified']:
            return {'success': False, 'message': 'Already verified'}
        
        with self._user_model.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM email_verification_codes WHERE user_id = %s AND code = %s AND used = 0 AND expires_at > NOW()",
                    (user['id'], code)
                )
                code_record = cur.fetchone()
                
                if not code_record:
                    return {'success': False, 'message': 'Invalid or expired code'}
                
                cur.execute("UPDATE email_verification_codes SET used = 1 WHERE id = %s", (code_record['id'],))
                cur.execute("UPDATE users SET is_verified = 1 WHERE id = %s", (user['id'],))
        
        tokens = self.create_tokens(user['id'])
        tokens['role'] = user['role']
        tokens['role_selected'] = bool(user.get('role_selected', 0))
        
        return {'success': True, 'message': 'Email verified', 'data': tokens}
    
    def resend_verification(self, email: str) -> dict:
        user = self._user_model.find_by_email(email)
        if not user:
            return {'success': False, 'message': 'User not found'}
        
        if user['is_verified']:
            return {'success': False, 'message': 'Already verified'}
        
        with self._user_model.db.get_connection() as conn:
            with conn.cursor() as cur:
                # Invalidate old codes
                cur.execute(
                    "UPDATE email_verification_codes SET used = 1 WHERE user_id = %s AND used = 0",
                    (user['id'],)
                )
                
                # Create new code
                code = self.generate_otp()
                cur.execute(
                    "INSERT INTO email_verification_codes (user_id, code, expires_at) VALUES (%s, %s, %s)",
                    (user['id'], code, datetime.now() + timedelta(minutes=10))
                )
        
        self._email_service.send_verification(email, code)
        return {'success': True, 'message': 'New verification code sent'}
    
    def login(self, email: str, password: str) -> dict:
        user = self._user_model.find_by_email(email)
        if not user:
            return {'success': False, 'message': 'Invalid credentials'}
        
        if not user['is_verified']:
            return {'success': False, 'message': 'Please verify your email first'}
        
        if not user['is_active']:
            return {'success': False, 'message': 'Account deactivated'}
        
        if not self.verify_password(password, user['password_hash']):
            return {'success': False, 'message': 'Invalid credentials'}
        
        tokens = self.create_tokens(user['id'])
        tokens['role'] = user['role']
        tokens['role_selected'] = bool(user.get('role_selected', 0))
        
        return {'success': True, 'data': tokens}
    
    def forgot_password(self, email: str) -> dict:
        user = self._user_model.find_by_email(email)
        if not user or not user['is_verified']:
            # Don't reveal if user exists for security
            return {'success': True, 'message': 'If your email is registered, you will receive a reset code'}
        
        with self._user_model.db.get_connection() as conn:
            with conn.cursor() as cur:
                # Invalidate old codes
                cur.execute(
                    "UPDATE password_reset_codes SET used = 1 WHERE user_id = %s AND used = 0",
                    (user['id'],)
                )
                
                # Create new code
                code = self.generate_otp()
                cur.execute(
                    "INSERT INTO password_reset_codes (user_id, code, expires_at) VALUES (%s, %s, %s)",
                    (user['id'], code, datetime.now() + timedelta(minutes=15))
                )
        
        self._email_service.send_password_reset(email, code)
        return {'success': True, 'message': 'Reset code sent to your email'}
    
    def reset_password(self, email: str, code: str, new_password: str) -> dict:
        if len(new_password) < 6:
            return {'success': False, 'message': 'Password must be at least 6 characters'}
        
        user = self._user_model.find_by_email(email)
        if not user:
            return {'success': False, 'message': 'Invalid request'}
        
        with self._user_model.db.get_connection() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT id FROM password_reset_codes WHERE user_id = %s AND code = %s AND used = 0 AND expires_at > NOW()",
                    (user['id'], code)
                )
                code_record = cur.fetchone()
                
                if not code_record:
                    return {'success': False, 'message': 'Invalid or expired code'}
                
                new_hash = self.hash_password(new_password)
                cur.execute("UPDATE users SET password_hash = %s WHERE id = %s", (new_hash, user['id']))
                cur.execute("UPDATE password_reset_codes SET used = 1 WHERE id = %s", (code_record['id'],))
        
        return {'success': True, 'message': 'Password reset successfully'}
    
    def delete_account(self, user_id: int) -> dict:
        result = self._user_model.delete_account(user_id)
        if result:
            return {'success': True, 'message': 'Account deleted successfully'}
        return {'success': False, 'message': 'Failed to delete account'}