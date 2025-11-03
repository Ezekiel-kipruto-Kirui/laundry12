from .base import *

DEBUG = env.bool('DJANGO_DEBUG',default=False)

# NPM_BIN_PATH = env("NPM_BIN_PATH", default=None)
if not DEBUG:
    ALLOWED_HOSTS = ['www.cleanpage.shop','cleanpage.shop','elite-laundry0010.onrender.com']
    CSRF_TRUSTED_ORIGINS = [
        'https://www.cleanpage.shop',
        'https://cleanpage.shop',
        'https://elite-laundry0010.onrender.com'
    ]
    DATABASES = {
        'default': dj_database_url.config(
            default=os.getenv('DATABASE_URL'),
            conn_max_age=600,
        )
    }
    SECURE_SSL_REDIRECT = True  # Redirect all HTTP to HTTPS
    SESSION_COOKIE_SECURE = True  # Secure session cookies
    CSRF_COOKIE_SECURE = True  # Secure CSRF cookies
    SECURE_HSTS_SECONDS = 31536000  # 1 year HSTS duration
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SECURE_HSTS_PRELOAD = True  # Allow inclusion in browser preload lists

    # Prevent browser from guessing content types
    SECURE_CONTENT_TYPE_NOSNIFF = True
    SECURE_BROWSER_XSS_FILTER = True
    X_FRAME_OPTIONS = "DENY"  # Prevent clickjacking


