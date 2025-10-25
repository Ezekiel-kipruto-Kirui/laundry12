# backends.py
from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model
from django.db.models import Q

class EmailOrUsernameModelBackend(ModelBackend):
    """
    Authenticate using either username or email
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        UserModel = get_user_model()
        try:
            # Try to fetch user by email or username
            user = UserModel.objects.get(
                Q(email=username) | Q(username=username)
            )
        except UserModel.DoesNotExist:
            return None
        
        if user.check_password(password):
            return user
        return None