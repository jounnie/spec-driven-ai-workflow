from django.conf import settings
from django.contrib.auth import get_user_model, login
from django.db import transaction
from django.http import Http404, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from .forms import RegistrationForm


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
