import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Base configuration class - Abstraction"""
    
    # Database
    DB_HOST = os.getenv('DB_HOST', 'localhost')
    DB_PORT = int(os.getenv('DB_PORT', 3306))
    DB_USER = os.getenv('DB_USER', 'root')
    DB_PASSWORD = os.getenv('DB_PASSWORD', '')
    DB_NAME = os.getenv('DB_NAME', 'career_navigator')
    
    # JWT
    JWT_SECRET = os.getenv('JWT_SECRET', 'super-secret-key-change-in-production')
    JWT_ACCESS_EXPIRES = timedelta(hours=2)
    JWT_REFRESH_EXPIRES = timedelta(days=30)
    
    # Email (Brevo)
    BREVO_API_KEY = os.getenv('BREVO_API_KEY', '')
    BREVO_SENDER_EMAIL = os.getenv('BREVO_SENDER_EMAIL', 'noreply@careernavigator.com')
    BREVO_SENDER_NAME = os.getenv('BREVO_SENDER_NAME', 'Career Navigator')
    
    # Admin
    ADMIN_EMAIL = 'tuheu.moussa@ictuniversity.edu.cm'
    
    # Pagination
    DEFAULT_PER_PAGE = 20
    MAX_PER_PAGE = 100


class DevelopmentConfig(Config):
    DEBUG = True
    TESTING = False


class ProductionConfig(Config):
    DEBUG = False
    TESTING = False
    
    
config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'default': DevelopmentConfig
}