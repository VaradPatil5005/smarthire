from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """A login. What it may do comes from its Membership, never from `is_staff`."""
