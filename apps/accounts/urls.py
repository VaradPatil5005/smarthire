from django.contrib.auth.views import LogoutView
from django.urls import path

from .views import ThrottledLoginView, join

urlpatterns = [
    path("login/", ThrottledLoginView.as_view(), name="login"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("join/", join, name="join"),
]
