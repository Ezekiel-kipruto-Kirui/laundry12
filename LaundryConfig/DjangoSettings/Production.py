from .base import *
import dj_database_url
import os

DEBUG = env.bool('DJANGO_DEBUG', default=False)

if not DEBUG:
    ALLOWED_HOSTS = ['www.cleanpage.shop', 'cleanpage.shop', 'elite-laundry0010.onrender.com']
    CSRF_TRUSTED_ORIGINS = [
        'https://www.cleanpage.shop',
        'https://cleanpage.shop',
        'https://elite-laundry0010.onrender.com'
    ]

    DATABASES = {
        'default': dj_database_url.config(
            default=os.getenv('DATABASE_URL'),
            conn_max_age=600,
            ssl_require=True
        )
    }

    SECURE_SSL_REDIRECT = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True
    SECURE_HSTS_SECONDS = 31536000
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_BROWSER_XSS_FILTER = True
    X_FRAME_OPTIONS = "DENY"
