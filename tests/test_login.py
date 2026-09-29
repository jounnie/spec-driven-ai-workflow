import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.urls import include, path

User = get_user_model()
PASSWORD = 'correct-horse-battery-1'
INVALID = 'Please enter a correct username and password.'


@login_required
def protected(request):
    return HttpResponse('secret')


urlpatterns = [path('protected/', protected), path('', include('pulse.urls'))]


@pytest.fixture
def anna(db):
    return User.objects.create_user('anna', password=PASSWORD)


def login(client, username='anna', password=PASSWORD, **extra):
    return client.post('/login/' + extra.pop('query', ''), {'username': username, 'password': password})


# Login page

def test_login_page_markup(client, anna):
    html = client.get('/login/').content.decode()

    assert html.count('<h1>') == 1 and '<h1>Log in</h1>' in html
    assert 'method="post"' in html and 'csrfmiddlewaretoken' in html
    assert 'type="password"' in html and 'autocomplete="current-password"' in html
    assert 'autocomplete="username"' in html
    assert '<label class="field__label" for="id_username">Username</label>' in html
    assert '<label class="field__label" for="id_password">Password</label>' in html
    assert 'class="button button--primary" type="submit">Log in</button>' in html


def test_correct_credentials_redirect_to_projects(client, anna):
    response = login(client)

    assert response.status_code == 302
    assert response['Location'] == '/projects/'


def test_next_is_followed_when_safe(client, anna):
    response = login(client, query='?next=/projects/5/')

    assert response['Location'] == '/projects/5/'


@pytest.mark.parametrize('target', ['https://evil.example/', '//evil.example/', 'javascript:alert(1)'])
def test_unsafe_next_is_ignored(client, anna, target):
    response = client.post('/login/', {'username': 'anna', 'password': PASSWORD, 'next': target})

    assert response['Location'] == '/projects/'
    response = login(client, query='?next=' + target)
    assert response['Location'] == '/projects/'


def test_wrong_password_and_unknown_user_show_the_same_message(client, anna):
    wrong = login(client, password='nope-nope-nope-1').content.decode()
    unknown = login(client, username='ghost').content.decode()

    for html in (wrong, unknown):
        assert '<div class="form-errors" role="alert">' in html
        assert INVALID in html
    block = lambda html: html.split('form-errors" role="alert">')[1].split('</div>')[0]
    assert block(wrong) == block(unknown)
    assert 'wrong' not in block(wrong).lower().replace('correct', '')


def test_failed_login_keeps_username_and_never_echoes_password(client, anna):
    html = login(client, password='nope-nope-nope-1').content.decode()

    assert 'value="anna"' in html
    assert 'nope-nope-nope-1' not in html


def test_inactive_user_cannot_log_in(client, anna):
    anna.is_active = False
    anna.save()

    response = login(client)

    assert response.status_code == 200
    assert INVALID in response.content.decode()
    assert '_auth_user_id' not in client.session


def test_logged_in_user_is_redirected_from_login_page(client, anna):
    client.force_login(anna)

    response = client.get('/login/')

    assert response.status_code == 302
    assert response['Location'] == '/projects/'


@pytest.mark.django_db
def test_login_redirects_to_register_while_no_user_exists(client):
    response = client.get('/login/')

    assert response.status_code == 302
    assert response['Location'] == '/register/'


def test_register_is_404_once_a_user_exists(client, anna):
    assert client.get('/register/').status_code == 404


# Header and logout

def test_header_shows_username_and_logout_form_when_logged_in(client, anna):
    client.force_login(anna)

    html = client.get('/no/such/page/').content.decode()

    assert '<li class="site-nav__user">anna</li>' in html
    assert '<form class="inline-form" method="post" action="/logout/">' in html
    assert 'button button--secondary" type="submit">Log out</button>' in html


def test_header_has_no_username_or_logout_for_anonymous(client, db):
    html = client.get('/no/such/page/').content.decode()

    assert 'site-nav__user' not in html
    assert 'Log out' not in html


def test_logout_post_ends_session_and_shows_message(client, anna):
    client.force_login(anna)

    response = client.post('/logout/', follow=True)

    assert response.redirect_chain[-1][0] == '/login/'
    assert 'You have been logged out.' in response.content.decode()
    assert '_auth_user_id' not in client.session


def test_logout_get_is_not_allowed(client, anna):
    client.force_login(anna)

    assert client.get('/logout/').status_code == 405
    assert '_auth_user_id' in client.session


def test_anonymous_logout_post_ends_on_login_page(client, anna):
    response = client.post('/logout/')

    assert response.status_code == 302
    assert response['Location'] == '/login/'


@pytest.mark.urls('tests.test_login')
def test_login_required_redirects_anonymous_and_after_logout(client, anna):
    assert client.get('/protected/')['Location'] == '/login/?next=/protected/'
    client.force_login(anna)
    assert client.get('/protected/').status_code == 200

    client.post('/logout/')

    assert client.get('/protected/')['Location'] == '/login/?next=/protected/'


# Passwords

@pytest.fixture
def real_hashers(settings):
    settings.PASSWORD_HASHERS = [
        'django.contrib.auth.hashers.Argon2PasswordHasher',
        'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    ]


def test_hasher_settings_list_argon2_first_then_pbkdf2():
    from importlib import import_module
    settings_module = import_module('config.settings')

    assert settings_module.PASSWORD_HASHERS[0].endswith('Argon2PasswordHasher')
    assert settings_module.PASSWORD_HASHERS[1].endswith('PBKDF2PasswordHasher')


def test_new_password_is_stored_with_argon2(real_hashers, django_user_model, db):
    user = django_user_model.objects.create_user('bea', password=PASSWORD)

    assert user.password.startswith('argon2')


def test_registration_stores_argon2_hash(real_hashers, client, db):
    client.post('/register/', {'username': 'anna', 'password1': PASSWORD, 'password2': PASSWORD})

    assert User.objects.get(username='anna').password.startswith('argon2')


def test_pbkdf2_password_is_upgraded_to_argon2_at_login(settings, client, db):
    settings.PASSWORD_HASHERS = ['django.contrib.auth.hashers.PBKDF2PasswordHasher']
    user = User.objects.create_user('anna', password=PASSWORD)
    assert user.password.startswith('pbkdf2_sha256')
    settings.PASSWORD_HASHERS = [
        'django.contrib.auth.hashers.Argon2PasswordHasher',
        'django.contrib.auth.hashers.PBKDF2PasswordHasher',
    ]

    response = login(client)

    assert response['Location'] == '/projects/'
    user.refresh_from_db()
    assert user.password.startswith('argon2')


def test_password_of_eleven_characters_is_rejected():
    with pytest.raises(ValidationError) as error:
        validate_password('xq7!LmZ2#pW')

    assert 'This password is too short. It must contain at least 12 characters.' in error.value.messages


def test_password_of_twelve_characters_passes_the_length_validator():
    validate_password('xq7!LmZ2#pWv')


def test_all_four_validators_stay_on(settings):
    names = [v['NAME'].rsplit('.', 1)[1] for v in settings.AUTH_PASSWORD_VALIDATORS]

    assert names == [
        'UserAttributeSimilarityValidator', 'MinimumLengthValidator',
        'CommonPasswordValidator', 'NumericPasswordValidator',
    ]
