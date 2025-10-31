from .base import *

ALLOWED_HOSTS = ['127.0.0.1', 'localhost','*']
CSRF_TRUSTED_ORIGINS = [
    'http://127.0.0.1:8000',
    'http://127.0.0.1:8080',
    'http://localhost:8000',
    'http://localhost:8080',
]


SECURE_SSL_REDIRECT = False
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False