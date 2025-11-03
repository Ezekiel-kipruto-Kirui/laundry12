from .base import *
if DEBUG:
    ALLOWED_HOSTS = ['127.0.0.1', 'localhost','*']
    CSRF_TRUSTED_ORIGINS = [
        'http://127.0.0.1:8000',
        'http://127.0.0.1:8080',
        'http://localhost:8000',
        'http://localhost:8080',
    ]

    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }


