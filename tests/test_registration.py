import threading
from html.parser import HTMLParser

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db import connections
from django.test import Client

from pulse import forms

User = get_user_model()
PASSWORD = 'correct-horse-battery-1'


class Fields(HTMLParser):
    """Collects input attributes by name, plus the text of elements by class."""

    def __init__(self, html):
        super().__init__()
        self.inputs = {}
        self.classes = []
        self.text = {}
        self._stack = []
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'input':
            self.inputs[attrs.get('name')] = attrs
        css = attrs.get('class', '')
        self.classes.extend(css.split())
        self._stack.append((tag, attrs.get('id'), css))

    def handle_endtag(self, tag):
        if self._stack:
            self._stack.pop()

    def handle_data(self, data):
        for _, ident, _ in self._stack:
            if ident:
                self.text[ident] = self.text.get(ident, '') + data


def post(client, username='anna', password=PASSWORD, confirmation=None):
    return client.post('/register/', {
        'username': username,
        'password1': password,
        'password2': password if confirmation is None else confirmation,
    })


# Root redirect

@pytest.mark.django_db
def test_root_redirects_to_register_while_no_user_exists(client):
    response = client.get('/')

    assert response.status_code == 302
    assert response['Location'] == '/register/'


@pytest.mark.django_db
def test_root_redirects_to_projects_once_a_user_exists(client):
    User.objects.create_user('anna', password=PASSWORD)

    response = client.get('/')

    assert response.status_code == 302
    assert response['Location'] == '/projects/'


# The form

@pytest.mark.django_db
def test_register_form_shows_fields_and_admin_notice(client):
    response = client.get('/register/')

    assert response.status_code == 200
    html = response.content.decode()
    assert 'This account will be the administrator of this instance.' in html
    fields = Fields(html)
    assert set(fields.inputs) >= {'username', 'password1', 'password2'}
    assert fields.inputs['password1']['type'] == 'password'
    assert fields.inputs['password2']['type'] == 'password'
    for name in ('username', 'password1', 'password2'):
        assert f'for="id_{name}"' in html
    assert 'button--primary' in fields.classes


# Successful registration

@pytest.mark.django_db
def test_valid_registration_creates_active_superuser_and_logs_in(client):
    response = post(client)

    assert response.status_code == 302
    assert response['Location'] == '/projects/'
    user = User.objects.get()
    assert user.username == 'anna'
    assert user.is_superuser and user.is_staff and user.is_active
    assert user.check_password(PASSWORD)
    assert client.session['_auth_user_id'] == str(user.pk)


# Errors

@pytest.mark.django_db
def test_password_failing_validators_shows_message_and_creates_no_user(client):
    response = post(client, password='12345678')

    assert response.status_code == 200
    assert not User.objects.exists()
    html = response.content.decode()
    assert 'This password is entirely numeric.' in html
    fields = Fields(html)
    assert fields.inputs['password1'].get('aria-invalid') is None
    assert fields.inputs['password2']['aria-invalid'] == 'true'
    assert 'id_password2_error' in fields.inputs['password2']['aria-describedby']
    assert 'field--invalid' in fields.classes
    assert 'field__error' in fields.classes


@pytest.mark.django_db
def test_too_short_password_shows_minimum_length_message(client):
    response = post(client, password='xq7!Lm')

    assert not User.objects.exists()
    assert 'at least 8 characters' in response.content.decode()


@pytest.mark.django_db
def test_mismatched_confirmation_shows_error_and_creates_no_user(client):
    response = post(client, confirmation='something-else-entirely-2')

    assert response.status_code == 200
    assert not User.objects.exists()
    fields = Fields(response.content.decode())
    assert fields.inputs['password2']['aria-invalid'] == 'true'
    assert 'match' in fields.text['id_password2_error']
    assert fields.classes.count('field--invalid') == 1


@pytest.mark.django_db
def test_errors_keep_the_username_but_never_the_password(client):
    response = post(client, username='anna', confirmation='something-else-entirely-2')

    html = response.content.decode()
    fields = Fields(html)
    assert fields.inputs['username']['value'] == 'anna'
    assert 'value' not in fields.inputs['password1']
    assert 'value' not in fields.inputs['password2']
    assert PASSWORD not in html
    assert 'something-else-entirely-2' not in html


@pytest.mark.django_db
def test_username_value_is_escaped_when_redisplayed(client):
    response = post(client, username='"><b>x', password='12345678')

    html = response.content.decode()
    assert '<b>x' not in html
    assert '&lt;b&gt;x' in html or '&quot;&gt;&lt;b&gt;x' in html


@pytest.mark.django_db
def test_invalid_username_is_reported_on_its_own_field(client):
    response = post(client, username='not valid!')

    assert not User.objects.exists()
    fields = Fields(response.content.decode())
    assert fields.inputs['username']['aria-invalid'] == 'true'


# Registration closes

@pytest.mark.django_db
def test_register_returns_404_for_get_and_post_once_a_user_exists(client):
    User.objects.create_user('anna', password=PASSWORD)

    assert client.get('/register/').status_code == 404
    assert post(client, username='bob').status_code == 404
    assert User.objects.count() == 1


@pytest.mark.django_db
def test_register_returns_404_when_the_only_user_is_inactive(client):
    User.objects.create_user('anna', password=PASSWORD, is_active=False)

    assert client.get('/register/').status_code == 404
    assert post(client, username='bob').status_code == 404
    assert User.objects.count() == 1


@pytest.mark.django_db
def test_register_returns_404_for_a_visitor_who_is_logged_in(client):
    user = User.objects.create_user('anna', password=PASSWORD)
    client.force_login(user)

    assert client.get('/register/').status_code == 404
    assert post(client, username='bob').status_code == 404


@pytest.mark.django_db
def test_user_from_createsuperuser_closes_registration(client):
    call_command(
        'createsuperuser', interactive=False, username='host', email='host@example.com',
    )

    assert client.get('/register/').status_code == 404
    assert post(client, username='bob').status_code == 404
    assert client.get('/').status_code == 302
    assert client.get('/')['Location'] == '/projects/'


@pytest.mark.django_db
def test_second_registration_after_the_first_is_rejected(client):
    assert post(client).status_code == 302

    other = Client()
    assert post(other, username='bob').status_code == 404
    assert User.objects.count() == 1


@pytest.mark.django_db
def test_register_rejects_other_methods(client):
    assert client.put('/register/').status_code == 405


# Concurrency

@pytest.fixture
def file_database(transactional_db, tmp_path):
    """Point `default` at a real SQLite file for this test.

    The in-memory test database is shared between threads with table-level
    locks, which does not behave like the production file; the write lock
    that serialises the registrations needs a real file.
    """
    original_name = connections.settings['default']['NAME']
    original = connections['default']
    del connections['default']  # in-memory connections ignore close()
    connections.settings['default']['NAME'] = tmp_path / 'race.sqlite3'
    call_command('migrate', verbosity=0)
    yield
    connections['default'].close()
    del connections['default']
    connections.settings['default']['NAME'] = original_name
    connections['default'] = original


def test_two_simultaneous_registrations_create_exactly_one_user(file_database, monkeypatch):
    barrier = threading.Barrier(2, timeout=10)
    original = forms.RegistrationForm.is_valid

    def is_valid_then_wait(self):
        result = original(self)
        barrier.wait()  # both requests have passed the "no user yet" check
        return result

    monkeypatch.setattr(forms.RegistrationForm, 'is_valid', is_valid_then_wait)
    statuses = {}
    errors = []

    def register(username):
        from django.db import connection
        try:
            statuses[username] = post(Client(), username=username).status_code
        except Exception as exc:  # noqa: BLE001 - reported below
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=register, args=(name,)) for name in ('anna', 'bob')]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors
    assert User.objects.count() == 1
    assert sorted(statuses.values()) == [302, 404]
    assert User.objects.get().is_superuser
