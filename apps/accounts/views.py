from django.contrib.auth import get_user_model, login
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.views import LoginView
from django.db import transaction
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .services import (
    clear_failures,
    find_usable_invitation,
    is_throttled,
    record_failure,
    redeem_invitation,
)


class ThrottledAuthenticationForm(AuthenticationForm):
    def clean(self):
        # The value authentication will use, so padding or Unicode variants share one counter.
        username = self.cleaned_data.get("username") or self.data.get("username", "")
        ip_address = self.request.META.get("REMOTE_ADDR", "")
        if is_throttled(username, ip_address):
            self.add_error(None, "Too many failed attempts. Please try again in 15 minutes.")
            raise self.get_invalid_login_error()
        try:
            cleaned = super().clean()
        except Exception:
            record_failure(username, ip_address)
            raise
        clear_failures(username, ip_address)
        return cleaned


class ThrottledLoginView(LoginView):
    template_name = "accounts/login.html"
    authentication_form = ThrottledAuthenticationForm


class JoinForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = get_user_model()
        fields = ("username",)


@require_http_methods(["GET", "POST"])
def join(request):
    """Redeem an invitation. No role, organisation or staff flag is ever read from the form."""
    token = request.POST.get("token", "")
    form = JoinForm(request.POST if token else None)
    error = ""
    if request.method == "POST" and token:
        invitation = find_usable_invitation(token)
        if invitation is None:
            error = "This invitation has expired or was already used. Ask for a new one."
        elif form.is_valid():
            try:
                # Account and membership must either both exist or neither exist.
                with transaction.atomic():
                    user = form.save()
                    redeem_invitation(invitation, user)
            except ValueError:
                error = "This invitation has expired or was already used. Ask for a new one."
            else:
                login(request, user, backend="django.contrib.auth.backends.ModelBackend")
                return redirect("home")
    elif request.method == "POST":
        error = "Enter your invitation code."
    return render(request, "accounts/join.html", {"form": form, "error": error, "token": token})
