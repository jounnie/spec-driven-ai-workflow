import re
import threading
from datetime import datetime, timedelta, timezone as dt_timezone

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.test import Client

from tests.test_invitations import file_database  # noqa: F401 - fixture

User = get_user_model()
PASSWORD = 'correct-horse-battery-1'
NEW_PASSWORD = 'another-long-password-2'
INVALID_TEXT = 'This reset link is not valid. Ask your administrator for a new one.'
CHANGED_TEXT = 'Your password has been changed. Log in with your new password.'
LINK_RE = re.compile(r'http://testserver(/reset/[^<\s]+/)')


@pytest.fixture
def admin(db):
    return User.objects.create_user('admin', password=PASSWORD, is_superuser=True, is_staff=True)


@pytest.fixture
def lead(db):
    return User.objects.create_user('lead', password=PASSWORD)


@pytest.fixture
def other(db):
    return User.objects.create_user('other', password=PASSWORD)


def create_link(admin, user):
    """Create a link through the admin's page, the way the admin does."""
    client = Client()
    client.force_login(admin)
    response = client.post(f'/leads/{user.pk}/reset-link/')
    assert response.status_code == 200
    return LINK_RE.search(response.content.decode()).group(1)


def open_link(client, path):
    """Follow Django's redirect to the token-less set-password URL."""
    response = client.get(path)
    assert response.status_code == 302
    return response['Location']


def set_password(client, url, password=NEW_PASSWORD, confirmation=None):
    return client.post(url, {
        'new_password1': password,
        'new_password2': password if confirmation is None else confirmation,
    })


def assert_invalid_page(response):
    assert response.status_code == 404
    html = response.content.decode()
    assert INVALID_TEXT in html
    assert 'site-header' in html
    assert 'error-page' in html


def can_log_in(user, password):
    # Not a real login: that would update last_login and kill outstanding links.
    return User.objects.get(pk=user.pk).check_password(password)


# Admin side: leads list

def test_leads_list_is_for_superusers_only(client, lead):
    assert client.get('/leads/').status_code == 302
    assert client.get('/leads/')['Location'].startswith('/login/')
    client.force_login(lead)
    assert client.get('/leads/').status_code == 403


def test_leads_list_shows_active_users_with_last_login(client, admin, lead, django_user_model):
    django_user_model.objects.create_user('gone', password=PASSWORD, is_active=False)
    lead.last_login = datetime(2026, 3, 4, 9, 5, tzinfo=dt_timezone.utc)
    lead.save()
    client.force_login(admin)

    html = client.get('/leads/').content.decode()

    assert 'table-scroll' in html and '<caption' in html and 'scope="row"' in html
    assert '>lead<' in html and '>admin<' in html
    assert 'gone' not in html
    assert '2026-03-04 09:05' in html
    assert 'Never' not in html.split('lead</th>')[1].split('</tr>')[0]


def test_leads_list_shows_never_for_users_without_login(client, admin, lead):
    client.force_login(admin)
    lead.last_login = None
    lead.save()

    html = client.get('/leads/').content.decode()

    assert 'Never' in html.split('>lead</th>')[1].split('</tr>')[0]


def test_leads_list_has_no_button_for_the_admin_row(client, admin, lead):
    client.force_login(admin)

    html = client.get('/leads/').content.decode()

    assert f'/leads/{lead.pk}/reset-link/' in html
    assert f'/leads/{admin.pk}/reset-link/' not in html


def test_leads_link_is_shown_to_admin_only(client, admin, lead):
    client.force_login(lead)
    assert 'href="/leads/"' not in client.get('/invite/x/').content.decode()
    client.force_login(admin)
    assert 'href="/leads/"' in client.get('/leads/').content.decode()


# Admin side: creating a link

def test_creating_a_link_needs_post(client, admin, lead):
    client.force_login(admin)

    assert client.get(f'/leads/{lead.pk}/reset-link/').status_code == 405


def test_creating_a_link_shows_the_absolute_link_once(client, admin, lead):
    client.force_login(admin)

    response = client.post(f'/leads/{lead.pk}/reset-link/')
    html = response.content.decode()

    assert response.status_code == 200
    match = LINK_RE.search(html)
    assert match
    assert 'lead' in html
    assert 'copy-link__url' in html and 'data-copy-target' in html
    assert 'This link can be used once and expires in 3 days.' in html
    assert 'href="/leads/"' in html
    assert match.group(0) not in client.get('/leads/').content.decode()


def test_link_contains_no_password_hash_or_username(client, admin, lead):
    link = create_link(admin, lead)

    assert 'lead' not in link
    assert lead.password not in link


def test_anonymous_or_lead_post_creates_no_link(client, lead, other):
    anonymous = client.post(f'/leads/{lead.pk}/reset-link/')
    client.force_login(other)
    forbidden = client.post(f'/leads/{lead.pk}/reset-link/')

    assert anonymous.status_code == 302 and anonymous['Location'].startswith('/login/')
    assert forbidden.status_code == 403
    assert b'/reset/' not in anonymous.content + forbidden.content


def test_link_for_unknown_or_inactive_user_gives_404(client, admin, lead):
    lead.is_active = False
    lead.save()
    client.force_login(admin)

    assert client.post(f'/leads/{lead.pk}/reset-link/').status_code == 404
    assert client.post('/leads/9999/reset-link/').status_code == 404


def test_link_for_own_account_gives_error_and_redirect(client, admin):
    client.force_login(admin)

    response = client.post(f'/leads/{admin.pk}/reset-link/', follow=True)

    assert response.redirect_chain[-1][0] == '/leads/'
    assert 'You cannot create a reset link for your own account.' in response.content.decode()
    assert '/reset/' not in response.content.decode()


# Lead side: form

def test_valid_link_shows_password_form(admin, lead):
    client = Client()
    url = open_link(client, create_link(admin, lead))

    response = client.get(url)
    html = response.content.decode()

    assert response.status_code == 200
    assert html.count('<h1') == 1
    assert 'name="new_password1"' in html and 'name="new_password2"' in html
    assert 'field__input' in html and '<script' not in html.replace('<script src', '')


def test_valid_link_works_when_logged_in(admin, lead, other):
    client = Client()
    client.force_login(other)
    path = create_link(admin, lead)

    assert client.get(open_link(client, path)).status_code == 200


@pytest.mark.parametrize('password, confirmation', [
    ('short-1', None),
    ('password1234', None),
    (NEW_PASSWORD, 'different-password-3'),
])
def test_bad_password_shows_error_and_link_still_works(admin, lead, password, confirmation):
    client = Client()
    path = create_link(admin, lead)
    url = open_link(client, path)

    response = set_password(client, url, password, confirmation)
    html = response.content.decode()

    assert response.status_code == 200
    assert 'field__error' in html
    assert 'value=' not in re.search(r'<input[^>]*new_password1[^>]*>', html).group(0)
    assert can_log_in(lead, PASSWORD)
    assert set_password(client, url).status_code == 302
    assert can_log_in(lead, NEW_PASSWORD)


def test_password_too_similar_to_username_is_rejected(admin, django_user_model):
    user = django_user_model.objects.create_user('annabelle-jones', password=PASSWORD)
    client = Client()
    url = open_link(client, create_link(admin, user))

    response = set_password(client, url, 'annabelle-jones1')

    assert response.status_code == 200
    assert 'too similar' in response.content.decode()
    assert can_log_in(user, PASSWORD)


def test_successful_reset_redirects_to_login_without_logging_in(admin, lead, settings):
    settings.PASSWORD_HASHERS = ['django.contrib.auth.hashers.Argon2PasswordHasher']
    client = Client()
    url = open_link(client, create_link(admin, lead))

    response = set_password(client, url)

    assert response.status_code == 302 and response['Location'] == '/login/'
    assert '_auth_user_id' not in client.session
    page = client.get('/login/').content.decode()
    assert CHANGED_TEXT in page
    lead.refresh_from_db()
    assert lead.password.startswith('argon2$')
    assert lead.check_password(NEW_PASSWORD)
    assert client.post('/login/', {'username': 'lead', 'password': NEW_PASSWORD}).status_code == 302
    assert '_auth_user_id' in client.session


def test_old_password_stops_working_and_other_sessions_are_logged_out(admin, lead):
    old_session = Client()
    old_session.force_login(lead)
    assert old_session.get('/leads/').status_code == 403  # logged in
    client = Client()
    url = open_link(client, create_link(admin, lead))

    set_password(client, url)

    assert not can_log_in(lead, PASSWORD)
    response = old_session.get('/leads/')
    assert response.status_code == 302 and response['Location'].startswith('/login/')


def test_reset_does_not_touch_other_leads(admin, lead, other):
    other_session = Client()
    other_session.force_login(other)
    other_hash = User.objects.get(pk=other.pk).password
    client = Client()
    url = open_link(client, create_link(admin, lead))

    set_password(client, url)

    assert User.objects.get(pk=other.pk).password == other_hash
    assert other_session.get('/leads/').status_code == 403  # still logged in


# Lead side: invalid links

def test_tampered_malformed_and_unknown_links_give_the_same_page(admin, lead, client):
    path = create_link(admin, lead)
    uid, token = path.strip('/').split('/')[1:]
    bad = [
        f'/reset/{uid}/{token[:-1]}{"a" if token[-1] != "a" else "b"}/',
        f'/reset/{uid}/not-a-token/',
        f'/reset/{uid}/x/',
        f'/reset/!!!/{token}/',
        f'/reset/OTk5OQ/{token}/',
        f'/reset/{uid}/set-password/',
    ]

    pages = [client.get(url) for url in bad]

    for response in pages:
        assert_invalid_page(response)
    assert len({re.sub(rb'X-CSRFToken": "[^"]*', b'', response.content) for response in pages}) == 1


def test_post_to_invalid_links_changes_nothing(admin, lead, client):
    uid = create_link(admin, lead).strip('/').split('/')[1]
    before = User.objects.get(pk=lead.pk).password

    for url in (f'/reset/{uid}/bogus-token/', f'/reset/{uid}/set-password/'):
        assert_invalid_page(set_password(client, url))

    assert User.objects.get(pk=lead.pk).password == before


def test_link_is_valid_just_before_three_days_and_invalid_after(admin, lead, monkeypatch, settings):
    assert settings.PASSWORD_RESET_TIMEOUT == 3 * 24 * 60 * 60
    created = datetime(2026, 1, 5, 9, 0)
    monkeypatch.setattr(default_token_generator, '_now', lambda: created)
    path = create_link(admin, lead)

    monkeypatch.setattr(default_token_generator, '_now', lambda: created + timedelta(days=3, seconds=-1))
    assert Client().get(path).status_code == 302
    monkeypatch.setattr(default_token_generator, '_now', lambda: created + timedelta(days=3, seconds=1))
    assert_invalid_page(Client().get(path))


def test_link_expiring_between_opening_and_submitting_is_rejected(admin, lead, monkeypatch):
    created = datetime(2026, 1, 5, 9, 0)
    monkeypatch.setattr(default_token_generator, '_now', lambda: created)
    client = Client()
    url = open_link(client, create_link(admin, lead))

    monkeypatch.setattr(default_token_generator, '_now', lambda: created + timedelta(days=4))

    assert_invalid_page(set_password(client, url))
    assert can_log_in(lead, PASSWORD)


def test_used_link_is_invalid_the_second_time(admin, lead):
    path = create_link(admin, lead)
    url = open_link(Client(), path)
    first = Client()
    first.get(path)
    set_password(first, url)

    assert_invalid_page(Client().get(path))
    assert_invalid_page(first.get(url))


def test_using_one_link_invalidates_the_other(admin, lead):
    first = create_link(admin, lead)
    second = create_link(admin, lead)
    client = Client()
    set_password(client, open_link(client, first))

    assert_invalid_page(Client().get(second))


def test_link_dies_when_the_lead_logs_in(admin, lead):
    path = create_link(admin, lead)

    assert Client().login(username='lead', password=PASSWORD)

    assert_invalid_page(Client().get(path))


def test_link_of_deactivated_user_is_invalid(admin, lead):
    path = create_link(admin, lead)
    client = Client()
    url = open_link(client, path)
    lead.is_active = False
    lead.save()

    assert_invalid_page(Client().get(path))
    assert_invalid_page(client.get(url))
    assert_invalid_page(set_password(client, url))


# Concurrency

def test_two_simultaneous_submissions_store_exactly_one_password(file_database, monkeypatch):  # noqa: F811
    admin = User.objects.create_user('admin', password=PASSWORD, is_superuser=True)
    lead = User.objects.create_user('lead', password=PASSWORD)
    path = create_link(admin, lead)
    clients = [Client(), Client()]
    urls = [open_link(client, path) for client in clients]
    passwords = ['first-long-password-1', 'second-long-password-2']
    barrier = threading.Barrier(2, timeout=10)
    from pulse import views
    original = views.PulseResetConfirmView.get_form

    def get_form_then_wait(self, form_class=None):
        form = original(self, form_class)
        if self.request.method == 'POST':
            barrier.wait()  # both requests have seen a valid link
        return form

    monkeypatch.setattr(views.PulseResetConfirmView, 'get_form', get_form_then_wait)
    statuses = {}
    errors = []

    def submit(index):
        from django.db import connection
        try:
            statuses[index] = set_password(clients[index], urls[index], passwords[index]).status_code
        except Exception as exc:  # noqa: BLE001 - reported below
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=submit, args=(i,)) for i in range(2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors
    assert sorted(statuses.values()) == [302, 404]
    winner = next(i for i, status in statuses.items() if status == 302)
    lead.refresh_from_db()
    assert lead.check_password(passwords[winner])
    assert not lead.check_password(passwords[1 - winner])
