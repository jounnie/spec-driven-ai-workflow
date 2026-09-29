import re
import threading
from datetime import datetime, timedelta, timezone as dt_timezone

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connections
from django.test import Client
from django.utils import timezone

from pulse import forms
from pulse.models import Invitation

User = get_user_model()
PASSWORD = 'correct-horse-battery-1'
INVALID_TEXT = 'This invitation link is not valid. Ask your administrator for a new one.'
UTC = dt_timezone.utc


@pytest.fixture
def admin(db):
    return User.objects.create_user('admin', password=PASSWORD, is_superuser=True, is_staff=True)


@pytest.fixture
def lead(db):
    return User.objects.create_user('lead', password=PASSWORD)


@pytest.fixture
def invitation(admin):
    return Invitation.objects.create(created_by=admin)


def sign_up(client, token, username='anna', password=PASSWORD, confirmation=None):
    return client.post(f'/invite/{token}/', {
        'username': username,
        'password1': password,
        'password2': password if confirmation is None else confirmation,
    })


def assert_invalid_page(response):
    assert response.status_code == 404
    html = response.content.decode()
    assert INVALID_TEXT in html
    assert 'site-header' in html  # base layout


# Model

def test_token_is_urlsafe_and_unique(admin):
    first = Invitation.objects.create(created_by=admin)
    second = Invitation.objects.create(created_by=admin)

    assert first.token != second.token
    assert len(first.token) == 43


def test_invitation_expires_seven_days_after_creation(admin):
    created = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
    invitation = Invitation(created_by=admin, created_at=created)
    invitation.save()

    assert invitation.expires_at == created + timedelta(days=7)


def test_invitation_is_valid_strictly_before_expiry(admin):
    created = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
    invitation = Invitation.objects.create(created_by=admin, created_at=created)
    expires = invitation.expires_at

    assert invitation.is_open(expires - timedelta(microseconds=1))
    assert not invitation.is_open(expires)
    assert not invitation.is_open(expires + timedelta(seconds=1))


@pytest.mark.django_db
def test_open_queryset_uses_the_same_boundary(admin):
    invitation = Invitation.objects.create(created_by=admin)

    assert list(Invitation.objects.open(invitation.expires_at - timedelta(seconds=1))) == [invitation]
    assert list(Invitation.objects.open(invitation.expires_at)) == []


def test_deleting_users_keeps_the_invitation(admin, lead, invitation):
    invitation.used_by = lead
    invitation.used_at = timezone.now()
    invitation.save()

    lead.delete()
    admin.delete()
    invitation.refresh_from_db()

    assert invitation.used_by is None and invitation.created_by is None


# Admin side: access

def test_invitations_page_redirects_anonymous_to_login(client, db):
    response = client.get('/invitations/')

    assert response.status_code == 302
    assert response['Location'].startswith('/login/?next=/invitations/')


def test_invitations_page_is_forbidden_for_non_admin(client, lead):
    client.force_login(lead)

    assert client.get('/invitations/').status_code == 403


def test_invitations_page_is_open_to_admin(client, admin):
    client.force_login(admin)

    assert client.get('/invitations/').status_code == 200


def test_header_shows_invitations_link_to_admin_only(client, admin, lead):
    client.force_login(admin)
    assert 'href="/invitations/"' in client.get('/invitations/').content.decode()
    client.force_login(lead)
    assert 'href="/invitations/"' not in client.get('/login/').content.decode()


# Admin side: create

def test_create_redirects_and_shows_message(client, admin):
    client.force_login(admin)

    response = client.post('/invitations/create/')

    assert response.status_code == 302 and response['Location'] == '/invitations/'
    assert Invitation.objects.count() == 1
    assert Invitation.objects.get().created_by == admin
    html = client.get('/invitations/').content.decode()
    assert 'Invitation created.' in html
    assert Invitation.objects.count() == 1  # reloading did not create another


def test_create_by_get_is_not_allowed(client, admin):
    client.force_login(admin)

    assert client.get('/invitations/create/').status_code == 405
    assert Invitation.objects.count() == 0


def test_create_by_anonymous_creates_nothing(client, db):
    response = client.post('/invitations/create/')

    assert response.status_code == 302 and response['Location'].startswith('/login/')
    assert Invitation.objects.count() == 0


def test_create_by_non_admin_creates_nothing(client, lead):
    client.force_login(lead)

    assert client.post('/invitations/create/').status_code == 403
    assert Invitation.objects.count() == 0


def test_creating_invitations_gives_different_tokens_and_keeps_others_open(client, admin):
    client.force_login(admin)

    client.post('/invitations/create/')
    client.post('/invitations/create/')

    first, second = Invitation.objects.order_by('pk')
    assert first.token != second.token
    assert Invitation.objects.open().count() == 2


# Admin side: list

def test_list_shows_absolute_link_with_copy_button(client, admin, invitation):
    client.force_login(admin)

    html = client.get('/invitations/').content.decode()

    link = f'http://testserver/invite/{invitation.token}/'
    assert f'<code class="copy-link__url" id="invitation-link-{invitation.pk}">{link}</code>' in html
    assert f'data-copy-target="invitation-link-{invitation.pk}"' in html
    assert 'aria-live="polite"' in html


def test_list_shows_dates_and_revoke_button_for_open_invitations(client, admin):
    created = timezone.now() - timedelta(days=1)
    invitation = Invitation.objects.create(created_by=admin, created_at=created)
    client.force_login(admin)

    html = client.get('/invitations/').content.decode()

    assert created.strftime('%Y-%m-%d') in html
    assert f'action="/invitations/{invitation.pk}/revoke/"' in html
    assert 'Revoke</button>' in html


def test_list_hides_expired_and_revoked_invitations(client, admin):
    old = Invitation.objects.create(created_by=admin, created_at=timezone.now() - timedelta(days=8))
    revoked = Invitation.objects.create(created_by=admin, revoked_at=timezone.now())
    client.force_login(admin)

    html = client.get('/invitations/').content.decode()

    assert old.token not in html and revoked.token not in html
    assert 'Revoke</button>' not in html


def test_list_shows_who_used_an_invitation_and_deleted_account(client, admin, lead):
    used = Invitation.objects.create(created_by=admin, used_by=lead, used_at=timezone.now())
    Invitation.objects.create(created_by=admin, used_by=None, used_at=timezone.now())
    client.force_login(admin)

    html = client.get('/invitations/').content.decode()

    assert '<th scope="row">lead</th>' in html
    assert '<th scope="row">deleted account</th>' in html
    assert used.token not in html  # a used link is not offered
    assert 'Revoke</button>' not in html


def test_list_uses_data_tables_and_design_system_markup(client, admin, lead, invitation):
    Invitation.objects.create(created_by=admin, used_by=lead, used_at=timezone.now())
    client.force_login(admin)

    html = client.get('/invitations/').content.decode()

    assert html.count('<h1>') == 1
    assert html.count('class="table-scroll"') == 2  # open and used lists
    assert html.count('<caption') == 2
    assert 'th scope="col"' in html and 'style=' not in html and '<script>' not in html
    assert 'onclick' not in html


# Admin side: revoke

def test_revoke_makes_link_invalid_and_sets_revoked_at(client, admin, invitation):
    client.force_login(admin)

    response = client.post(f'/invitations/{invitation.pk}/revoke/')

    assert response.status_code == 302 and response['Location'] == '/invitations/'
    invitation.refresh_from_db()
    assert invitation.revoked_at is not None
    assert_invalid_page(Client().get(f'/invite/{invitation.token}/'))


def test_revoke_by_get_is_not_allowed(client, admin, invitation):
    client.force_login(admin)

    assert client.get(f'/invitations/{invitation.pk}/revoke/').status_code == 405


def test_revoking_used_expired_or_revoked_changes_nothing(client, admin, lead):
    used_at = datetime(2026, 1, 1, tzinfo=UTC)
    used = Invitation.objects.create(created_by=admin, used_by=lead, used_at=used_at)
    expired = Invitation.objects.create(created_by=admin, created_at=timezone.now() - timedelta(days=9))
    already = Invitation.objects.create(created_by=admin, revoked_at=used_at)
    client.force_login(admin)

    for invitation in (used, expired, already):
        assert client.post(f'/invitations/{invitation.pk}/revoke/').status_code == 302

    used.refresh_from_db(), expired.refresh_from_db(), already.refresh_from_db()
    assert used.revoked_at is None and expired.revoked_at is None
    assert already.revoked_at == used_at


def test_revoke_by_non_admin_or_anonymous_changes_nothing(client, lead, invitation):
    assert client.post(f'/invitations/{invitation.pk}/revoke/').status_code == 302
    client.force_login(lead)
    assert client.post(f'/invitations/{invitation.pk}/revoke/').status_code == 403

    invitation.refresh_from_db()
    assert invitation.revoked_at is None


def test_revoke_unknown_invitation_is_404(client, admin):
    client.force_login(admin)

    assert client.post('/invitations/9999/revoke/').status_code == 404


# Invitee side

def test_valid_link_shows_sign_up_form(client, invitation):
    response = client.get(f'/invite/{invitation.token}/')

    assert response.status_code == 200
    html = response.content.decode()
    assert html.count('<h1>') == 1
    for name in ('username', 'password1', 'password2'):
        assert f'name="{name}"' in html
    assert 'csrfmiddlewaretoken' in html
    assert 'style=' not in html and '<script>' not in html


def test_sign_up_creates_lead_marks_invitation_used_and_logs_in(client, invitation):
    response = sign_up(client, invitation.token)

    assert response.status_code == 302 and response['Location'] == '/projects/'
    user = User.objects.get(username='anna')
    assert user.is_active and not user.is_superuser and not user.is_staff
    invitation.refresh_from_db()
    assert invitation.used_by == user and invitation.used_at is not None
    assert client.session['_auth_user_id'] == str(user.pk)


def test_new_lead_can_log_out_and_log_in_again(client, invitation):
    sign_up(client, invitation.token)

    assert client.post('/logout/').status_code == 302
    response = client.post('/login/', {'username': 'anna', 'password': PASSWORD})

    assert response.status_code == 302 and response['Location'] == '/projects/'


def test_new_account_has_argon2_hash(client, invitation, settings):
    settings.PASSWORD_HASHERS = ['django.contrib.auth.hashers.Argon2PasswordHasher']

    sign_up(client, invitation.token)

    user = User.objects.get(username='anna')
    assert user.password.startswith('argon2$')
    assert user.check_password(PASSWORD)


@pytest.mark.parametrize('existing', ['anna', 'Anna', 'ANNA'])
def test_existing_username_is_rejected_case_insensitively(client, invitation, existing):
    User.objects.create_user(existing, password=PASSWORD)

    response = sign_up(client, invitation.token, username='anna')

    assert response.status_code == 200
    html = response.content.decode()
    assert 'field__error' in html and 'value="anna"' in html
    assert User.objects.count() == 2  # admin + existing
    invitation.refresh_from_db()
    assert invitation.used_at is None


def test_inactive_account_and_admin_username_count_as_existing(client, invitation):
    User.objects.create_user('sleeper', password=PASSWORD, is_active=False)

    assert 'field__error' in sign_up(client, invitation.token, username='Sleeper').content.decode()
    assert 'field__error' in sign_up(client, invitation.token, username='ADMIN').content.decode()
    invitation.refresh_from_db()
    assert invitation.used_at is None


@pytest.mark.parametrize('password, confirmation', [
    ('short-pw-1', None),
    (PASSWORD, 'another-password-2'),
])
def test_bad_password_shows_error_and_keeps_invitation_unused(client, invitation, password, confirmation):
    response = sign_up(client, invitation.token, password=password, confirmation=confirmation)

    assert response.status_code == 200
    html = response.content.decode()
    assert 'field__error' in html
    assert 'value="anna"' in html
    assert password not in html.replace('value="anna"', '')
    assert not User.objects.filter(username='anna').exists()
    invitation.refresh_from_db()
    assert invitation.used_at is None


@pytest.mark.parametrize('case', ['expired', 'used', 'revoked'])
def test_unusable_links_show_the_same_page(client, admin, lead, case):
    kwargs = {
        'expired': {'created_at': timezone.now() - timedelta(days=8)},
        'used': {'used_at': timezone.now(), 'used_by': lead},
        'revoked': {'revoked_at': timezone.now()},
    }[case]
    invitation = Invitation.objects.create(created_by=admin, **kwargs)

    get = client.get(f'/invite/{invitation.token}/')
    post = sign_up(client, invitation.token)

    assert_invalid_page(get)
    assert_invalid_page(post)
    assert not User.objects.filter(username='anna').exists()


def test_unknown_and_malformed_tokens_show_the_same_page(client, invitation):
    pages = {
        re.sub(rb'[A-Za-z0-9]{64}', b'CSRF', client.get(path).content)
        for path in ('/invite/unknown-token/', '/invite/' + 'x' * 500 + '/', '/invite/%20/', f'/invite/{invitation.token}x/')
    }
    for path in ('/invite/unknown-token/', '/invite/%00/'):
        assert_invalid_page(client.get(path))
    assert len(pages) == 1
    assert_invalid_page(sign_up(client, 'unknown-token'))


def test_logged_in_user_gets_a_notice_and_nothing_is_used(client, lead, invitation):
    client.force_login(lead)

    get = client.get(f'/invite/{invitation.token}/')
    post = sign_up(client, invitation.token)

    for response in (get, post):
        assert response.status_code == 200
        assert 'You are already logged in as lead. Log out to use this invitation.' in response.content.decode()
    assert not User.objects.filter(username='anna').exists()
    invitation.refresh_from_db()
    assert invitation.used_at is None


# Concurrency

@pytest.fixture
def file_database(transactional_db, tmp_path):
    """Point `default` at a real SQLite file (see tests/test_registration.py)."""
    original_name = connections.settings['default']['NAME']
    original = connections['default']
    del connections['default']
    connections.settings['default']['NAME'] = tmp_path / 'race.sqlite3'
    call_command('migrate', verbosity=0)
    yield
    connections['default'].close()
    del connections['default']
    connections.settings['default']['NAME'] = original_name
    connections['default'] = original


@pytest.mark.parametrize('names', [('anna', 'anna2'), ('anna', 'anna')])
def test_two_simultaneous_sign_ups_create_exactly_one_account(file_database, monkeypatch, names):
    admin = User.objects.create_user('admin', password=PASSWORD, is_superuser=True)
    invitation = Invitation.objects.create(created_by=admin)
    barrier = threading.Barrier(2, timeout=10)
    original = forms.RegistrationForm.is_valid

    def is_valid_then_wait(self):
        result = original(self)
        barrier.wait()  # both requests have seen a valid, unused invitation
        return result

    monkeypatch.setattr(forms.RegistrationForm, 'is_valid', is_valid_then_wait)
    statuses = []
    errors = []

    def submit(username):
        from django.db import connection
        try:
            statuses.append(sign_up(Client(), invitation.token, username=username).status_code)
        except Exception as exc:  # noqa: BLE001 - reported below
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=submit, args=(name,)) for name in names]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors
    assert sorted(statuses) == [302, 404]
    assert User.objects.exclude(username='admin').count() == 1
    invitation.refresh_from_db()
    assert invitation.used_by is not None
