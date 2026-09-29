import re
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import get_user_model, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import (
    INTERNAL_RESET_SESSION_TOKEN,
    LoginView,
    LogoutView,
    PasswordResetConfirmView,
    redirect_to_login,
)
from django.core.exceptions import PermissionDenied
from django.core.signing import BadSignature
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.dateformat import format as format_date
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from django.views.decorators.http import require_http_methods, require_POST

from .conf import anonymity_limited, current_week_key, rating_scale
from .forms import RATING_FIELDS, ProjectForm, RegistrationForm, SubmissionForm
from .models import Invitation, Project, Submission


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


@require_http_methods(['GET', 'HEAD'])
@superuser_required
def leads(request):
    users = get_user_model().objects.filter(is_active=True).order_by('username', 'pk')
    return render(request, 'pulse/leads.html', {'leads': users})


@require_POST
@superuser_required
def reset_link_create(request, pk):
    user = get_object_or_404(get_user_model(), pk=pk, is_active=True)
    if user.pk == request.user.pk:
        messages.error(request, 'You cannot create a reset link for your own account.')
        return redirect('leads')
    # The token is not stored; it is shown once, on this response.
    link = request.build_absolute_uri(
        reverse(
            'password_reset_confirm',
            args=[urlsafe_base64_encode(force_bytes(user.pk)), default_token_generator.make_token(user)],
        )
    )
    return render(request, 'pulse/reset_link.html', {'lead': user, 'link': link})


def reset_invalid(request):
    """The one page for every kind of unusable reset link; it never says which."""
    return render(request, 'pulse/reset_invalid.html', status=404)


class PulseResetConfirmView(PasswordResetConfirmView):
    """Set a new password with an admin-created link (#9).

    Django's view accepts inactive users and answers 200 for bad links; this
    one rejects inactive users, answers 404 and repeats the token check inside
    a write-locked transaction.
    """

    template_name = 'pulse/password_reset_confirm.html'
    success_url = reverse_lazy('login')

    def get_user(self, uidb64):
        user = super().get_user(uidb64)
        return user if user is not None and user.is_active else None

    def get_form(self, form_class=None):
        form = super().get_form(form_class)
        # Django's help text is a <ul>, which does not fit the field component.
        form.fields['new_password1'].help_text = ''
        form.fields['new_password2'].help_text = ''
        return form

    def render_to_response(self, context, **response_kwargs):
        if not self.validlink:
            return reset_invalid(self.request)
        return super().render_to_response(context, **response_kwargs)

    def form_valid(self, form):
        session_token = self.request.session.get(INTERNAL_RESET_SESSION_TOKEN)
        # SQLite transaction_mode IMMEDIATE takes the write lock here, so the
        # user is read fresh and only one of two simultaneous requests wins.
        with transaction.atomic():
            user = self.get_user(self.kwargs['uidb64'])
            if user is None or not self.token_generator.check_token(user, session_token):
                self.validlink = False
                return reset_invalid(self.request)
            user.set_password(form.cleaned_data['new_password1'])
            user.save(update_fields=['password'])
        del self.request.session[INTERNAL_RESET_SESSION_TOKEN]
        messages.success(self.request, 'Your password has been changed. Log in with your new password.')
        return redirect(self.get_success_url())


@require_http_methods(['GET', 'HEAD', 'POST'])
@login_required
def projects(request):
    """The lead's own projects with share links and this week's counts; create form."""
    if request.method == 'POST':
        form = ProjectForm(request.POST)
        if form.is_valid():
            project = form.save(commit=False)
            project.owner = request.user
            project.save()
            messages.success(request, f'Project {project.name} created.')
            return redirect('projects')
    else:
        form = ProjectForm()

    week = current_week_key()
    # One query: the count is annotated, only for the current week key.
    own_projects = (
        Project.objects.filter(owner=request.user)
        .annotate(week_count=Count('submissions', filter=Q(submissions__week_key=week)))
        .order_by('-created_at', '-pk')
    )
    items = [
        {
            'project': project,
            'link': request.build_absolute_uri(f'/p/{project.share_token}/'),
            'count': project.week_count,
        }
        for project in own_projects
    ]
    return render(request, 'pulse/projects.html', {'items': items, 'form': form})


SHARE_TOKEN = re.compile(r'[A-Za-z0-9_-]{1,64}', re.ASCII)


def project_for_token(token):
    """Return the project of a share token, or raise Http404 for anything else."""
    if not SHARE_TOKEN.fullmatch(token):
        raise Http404
    return get_object_or_404(Project, share_token=token)


def _rating_rows(form):
    scale = rating_scale()
    ends = [f'{scale.start} = Strongly disagree', f'{scale.stop - 1} = Strongly agree']
    rows = []
    for name in RATING_FIELDS:
        field = Submission._meta.get_field(name)
        selected = ''
        if form.data is not None and name not in form.errors:
            selected = str(form.data.get(name, '')).strip()
        rows.append(
            {
                'name': name,
                'label': field.verbose_name,
                'error': name in form.errors,
                'ends': ends,
                'options': [{'value': v, 'checked': str(v) == selected} for v in scale],
            }
        )
    return rows


SUBMITTED_COOKIE = 'pulse_submitted'
SUBMITTED_COOKIE_MAX_AGE = 8 * 24 * 60 * 60


def _submitted_salt(token):
    return f'pulse.submitted.{token}'


def _already_submitted(request, token, week):
    """True when the signed cookie of this project holds the current week key."""
    try:
        value = request.get_signed_cookie(SUBMITTED_COOKIE, default=None, salt=_submitted_salt(token))
    except BadSignature:
        return False
    return value == week


def _next_monday_text():
    """Start of the next ISO week in the instance time zone, like ``5 October 2026``."""
    today = timezone.localtime(timezone.now(), timezone.get_default_timezone()).date()
    return format_date(today + timedelta(days=7 - today.weekday()), 'j F Y')


@require_http_methods(['GET', 'HEAD', 'POST'])
def respond(request, token):
    """The public rating form behind the share link; no account or session.

    The only state is the signed ``pulse_submitted`` cookie holding the week key.
    """
    project = project_for_token(token)
    week = current_week_key()
    if _already_submitted(request, token, week):
        return render(
            request, 'pulse/respond_already.html', {'project': project, 'next_monday': _next_monday_text()}
        )
    if request.method == 'POST':
        form = SubmissionForm(project, week, request.POST)
        if form.is_valid():
            form.save()
            response = redirect('respond_thanks', token=token)
            response.set_signed_cookie(
                SUBMITTED_COOKIE,
                week,
                salt=_submitted_salt(token),
                max_age=SUBMITTED_COOKIE_MAX_AGE,
                path=f'/p/{token}/',
                secure=request.is_secure(),
                httponly=True,
                samesite='Lax',
            )
            return response
    else:
        form = SubmissionForm(project, week)

    limited = anonymity_limited(Submission.objects.filter(project=project, week_key=week).count())
    context = {
        'project': project,
        'rows': _rating_rows(form),
        'limited': limited,
        'threshold': settings.PULSE_ANONYMITY_THRESHOLD,
    }
    return render(request, 'pulse/respond.html', context)


@require_http_methods(['GET', 'HEAD'])
def respond_thanks(request, token):
    project_for_token(token)
    return render(request, 'pulse/respond_thanks.html')
