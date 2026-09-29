from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.views import LoginView, LogoutView, redirect_to_login
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_http_methods, require_POST

from .forms import RegistrationForm
from .models import Invitation


def health(request):
    return HttpResponse('ok', content_type='text/plain')


def index(request):
    if get_user_model().objects.exists():
        return redirect('/projects/')
    return redirect('register')


@require_http_methods(['GET', 'HEAD', 'POST'])
def register(request):
    """Open only while no user exists; the first account becomes the administrator."""
    User = get_user_model()
    if User.objects.exists():
        raise Http404

    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            # Check again inside a write-locked transaction (SQLite
            # transaction_mode IMMEDIATE), so two requests cannot both pass.
            with transaction.atomic():
                if User.objects.exists():
                    raise Http404
                user = form.save(commit=False)
                user.is_superuser = True
                user.is_staff = True
                user.is_active = True
                user.save()
            login(request, user)
            return redirect(settings.LOGIN_REDIRECT_URL)
    else:
        form = RegistrationForm()
    return render(request, 'pulse/register.html', {'form': form})


class PulseLoginView(LoginView):
    """Login page; while no account exists it sends visitors to registration."""

    redirect_authenticated_user = True

    def dispatch(self, request, *args, **kwargs):
        if not get_user_model().objects.exists():
            return redirect('register')
        return super().dispatch(request, *args, **kwargs)


class PulseLogoutView(LogoutView):
    """Logout by POST only; confirms with an info message on the login page."""

    def post(self, request, *args, **kwargs):
        response = super().post(request, *args, **kwargs)
        # The session was flushed by logout, so the message goes into the new one.
        messages.info(request, 'You have been logged out.')
        return response


def superuser_required(view):
    """Anonymous visitors go to the login page, other users get 403."""

    @wraps(view)
    def wrapper(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not request.user.is_superuser:
            raise PermissionDenied
        return view(request, *args, **kwargs)

    return wrapper


@require_http_methods(['GET', 'HEAD'])
@superuser_required
def invitations(request):
    open_invitations = [
        {
            'invitation': invitation,
            'link': request.build_absolute_uri(reverse('invite', args=[invitation.token])),
        }
        for invitation in Invitation.objects.open().order_by('-created_at', '-pk')
    ]
    used = (
        Invitation.objects.filter(used_at__isnull=False)
        .select_related('used_by')
        .order_by('-used_at', '-pk')
    )
    return render(request, 'pulse/invitations.html', {'open_invitations': open_invitations, 'used': used})


@require_POST
@superuser_required
def invitation_create(request):
    Invitation.objects.create(created_by=request.user)
    messages.success(request, 'Invitation created.')
    return redirect('invitations')


@require_POST
@superuser_required
def invitation_revoke(request, pk):
    if not Invitation.objects.filter(pk=pk).exists():
        raise Http404
    revoked = Invitation.objects.open().filter(pk=pk).update(revoked_at=timezone.now())
    if revoked:
        messages.success(request, 'Invitation revoked.')
    return redirect('invitations')


def invitation_invalid(request):
    """The one page for every kind of unusable link; it never says which."""
    return render(request, 'pulse/invitation_invalid.html', status=404)


@require_http_methods(['GET', 'HEAD', 'POST'])
def invite(request, token):
    if not Invitation.objects.open().filter(token=token).exists():
        return invitation_invalid(request)
    if request.user.is_authenticated:
        return render(request, 'pulse/invite.html', {'already_logged_in': True})

    if request.method == 'POST':
        form = RegistrationForm(request.POST)
        if form.is_valid():
            # Claim the invitation inside a write-locked transaction (SQLite
            # transaction_mode IMMEDIATE); only one request can win the claim.
            with transaction.atomic():
                claimed = (
                    Invitation.objects.open().filter(token=token).update(used_at=timezone.now())
                )
                if not claimed:
                    return invitation_invalid(request)
                user = form.save(commit=False)
                user.is_superuser = False
                user.is_staff = False
                user.is_active = True
                user.save()
                Invitation.objects.filter(token=token).update(used_by=user)
            login(request, user)
            return redirect(settings.LOGIN_REDIRECT_URL)
    else:
        form = RegistrationForm()
    return render(request, 'pulse/invite.html', {'form': form})
