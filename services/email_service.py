from abc import ABC, abstractmethod
import sib_api_v3_sdk
from sib_api_v3_sdk.rest import ApiException
from config import Config


class EmailProvider(ABC):
    """Abstract email provider - Abstraction"""
    
    @abstractmethod
    def send(self, to: str, subject: str, html_content: str) -> bool:
        pass


class BrevoEmailProvider(EmailProvider):
    """Brevo/Sendinblue implementation - Polymorphism"""
    
    def __init__(self):
        self._api_key = Config.BREVO_API_KEY
        self._sender = Config.BREVO_SENDER_EMAIL
        self._sender_name = Config.BREVO_SENDER_NAME
        self._enabled = bool(self._api_key and self._sender)
    
    def send(self, to: str, subject: str, html_content: str) -> bool:
        if not self._enabled:
            print(f"[EMAIL DISABLED] Would send to {to}: {subject}")
            return False
        
        try:
            configuration = sib_api_v3_sdk.Configuration()
            configuration.api_key['api-key'] = self._api_key
            api_instance = sib_api_v3_sdk.TransactionalEmailsApi(
                sib_api_v3_sdk.ApiClient(configuration)
            )
            
            send_smtp_email = sib_api_v3_sdk.SendSmtpEmail(
                to=[{"email": to, "name": to}],
                sender={"email": self._sender, "name": self._sender_name},
                subject=subject,
                html_content=html_content
            )
            
            api_instance.send_transac_email(send_smtp_email)
            return True
        except ApiException as e:
            print(f"Email error: {e}")
            return False


class EmailService:
    """Email service facade - Encapsulation"""
    
    _instance = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._provider = BrevoEmailProvider()
        return cls._instance
    
    def send_verification(self, email: str, code: str) -> bool:
        html = f"""
        <!DOCTYPE html>
        <html>
        <head><meta charset="UTF-8"></head>
        <body style="font-family: Arial, sans-serif; background: #0A192F; padding: 40px;">
            <div style="max-width: 500px; margin: 0 auto; background: #0D2137; border-radius: 20px; padding: 30px; border: 1px solid #00E5FF;">
                <h1 style="color: #00E5FF; text-align: center;">Career Navigator</h1>
                <p style="color: #ffffff;">Your verification code is:</p>
                <div style="font-size: 42px; font-weight: bold; color: #00E5FF; text-align: center; letter-spacing: 10px; padding: 20px;">{code}</div>
                <p style="color: #8892B0;">This code expires in 10 minutes.</p>
                <hr style="border-color: #233554;">
                <p style="color: #8892B0; font-size: 12px;">If you didn't request this, please ignore this email.</p>
            </div>
        </body>
        </html>
        """
        return self._provider.send(email, "Verify Your Email - Career Navigator", html)
    
    def send_password_reset(self, email: str, code: str) -> bool:
        html = f"""
        <!DOCTYPE html>
        <html>
        <head><meta charset="UTF-8"></head>
        <body style="font-family: Arial, sans-serif; background: #0A192F; padding: 40px;">
            <div style="max-width: 500px; margin: 0 auto; background: #0D2137; border-radius: 20px; padding: 30px; border: 1px solid #00E5FF;">
                <h1 style="color: #00E5FF; text-align: center;">Reset Your Password</h1>
                <p style="color: #ffffff;">Your password reset code is:</p>
                <div style="font-size: 42px; font-weight: bold; color: #FF6B6B; text-align: center; letter-spacing: 10px; padding: 20px;">{code}</div>
                <p style="color: #8892B0;">This code expires in 15 minutes.</p>
                <hr style="border-color: #233554;">
                <p style="color: #8892B0; font-size: 12px;">If you didn't request this, please ignore this email.</p>
            </div>
        </body>
        </html>
        """
        return self._provider.send(email, "Reset Your Password - Career Navigator", html)
    
    def send_mentor_request(self, mentor_email: str, seeker_name: str) -> bool:
        html = f"""
        <!DOCTYPE html>
        <html>
        <head><meta charset="UTF-8"></head>
        <body style="font-family: Arial, sans-serif; background: #0A192F; padding: 40px;">
            <div style="max-width: 500px; margin: 0 auto; background: #0D2137; border-radius: 20px; padding: 30px; border: 1px solid #00E5FF;">
                <h1 style="color: #00E5FF; text-align: center;">New Mentorship Request</h1>
                <p style="color: #ffffff;"><strong>{seeker_name}</strong> has sent you a mentorship request.</p>
                <p style="color: #8892B0;">Open the Career Navigator app to respond to this request.</p>
                <hr style="border-color: #233554;">
                <p style="color: #8892B0; font-size: 12px;">Login to your account to view and respond.</p>
            </div>
        </body>
        </html>
        """
        return self._provider.send(mentor_email, "New Mentorship Request - Career Navigator", html)