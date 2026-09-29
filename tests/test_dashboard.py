import re
from datetime import datetime, timezone as dt_timezone

import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.utils import timezone

from pulse.models import Project, Submission

User = get_user_model()
PASSWORD = 'correct-horse-battery-1'
UTC = dt_timezone.utc


@pytest.fixture
def admin(db):
    return User.objects.create_user('admin', password=PASSWORD, is_superuser=True, is_staff=True)


@pytest.fixture
def anna(db):
    return User.objects.create_user('anna', password=PASSWORD)


@pytest.fixture
def ben(db):
    return User.objects.create_user('ben', password=PASSWORD)


def submit(project, week_key, rating=3):
    return Submission.objects.create(
        project=project, week_key=week_key,
        workload=rating, clarity=rating, collaboration=rating, progress=rating,
    )


def freeze(monkeypatch, *args):
    monkeypatch.setattr(timezone, 'now', lambda: datetime(*args, tzinfo=UTC))


# Access

def test_anonymous_get_redirects_to_login(client):
    response = client.get('/projects/')

    assert response.status_code == 302
    assert response['Location'] == '/login/?next=/projects/'


def test_anonymous_post_redirects_and_creates_nothing(client, db):
    response = client.post('/projects/', {'name': 'Apollo'})

    assert response.status_code == 302
    assert response['Location'] == '/login/?next=/projects/'
    assert Project.objects.count() == 0


def test_login_lands_on_projects(client, anna):
    response = client.post('/login/', {'username': 'anna', 'password': PASSWORD})

    assert response.status_code == 302
    assert response['Location'] == '/projects/'


def test_header_shows_projects_link_for_lead_and_admin(client, anna, admin):
    for user in (anna, admin):
        client.force_login(user)
        html = client.get('/projects/').content.decode()

        assert re.search(r'<a href="/projects/" aria-current="page">Projects</a>', html)


def test_projects_link_is_not_current_on_other_pages(client, anna):
    client.force_login(anna)

    html = client.get('/health/').content.decode() + client.get('/nope/').content.decode()

    assert '<a href="/projects/">Projects</a>' in client.get('/nope/').content.decode()
    assert 'aria-current="page">Projects' not in html


def test_anonymous_header_has_no_projects_link(client, admin):
    html = client.get('/login/').content.decode()

    assert 'href="/projects/"' not in html


def test_each_user_sees_only_their_own_projects(client, anna, ben, admin):
    mine = {u.username: Project.objects.create(owner=u, name=f'Project of {u.username}') for u in (anna, ben, admin)}

    for user in (anna, ben, admin):
        client.force_login(user)
        html = client.get('/projects/').content.decode()

        for other, project in mine.items():
            assert (project.name in html) == (other == user.username)
            assert (project.share_token in html) == (other == user.username)


# List

def test_projects_are_listed_newest_first(client, anna):
    old = Project.objects.create(owner=anna, name='Old')
    Project.objects.filter(pk=old.pk).update(created_at=datetime(2020, 1, 1, tzinfo=UTC))
    first = Project.objects.create(owner=anna, name='First')
    second = Project.objects.create(owner=anna, name='Second')
    Project.objects.filter(pk__in=[first.pk, second.pk]).update(created_at=datetime(2024, 1, 1, tzinfo=UTC))
    client.force_login(anna)

    html = client.get('/projects/').content.decode()

    assert html.index('Second') < html.index('First') < html.index('Old')


def test_entry_shows_name_link_share_link_and_copy_button(client, anna):
    project = Project.objects.create(owner=anna, name='Apollo')
    client.force_login(anna)

    html = client.get('/projects/').content.decode()

    assert f'<a href="/projects/{project.pk}/">Apollo</a>' in html
    assert f'<code class="copy-link__url" id="share-link-{project.pk}">http://testserver/p/{project.share_token}/</code>' in html
    assert f'data-copy-target="share-link-{project.pk}"' in html
    assert 'class="project-list__item"' in html
    assert 'pulse/js/copy-link.js' in html
    assert '<script>' not in html


def test_share_link_uses_scheme_and_host_of_request(client, anna, settings):
    settings.ALLOWED_HOSTS = ['pulse.example.org']
    project = Project.objects.create(owner=anna, name='Apollo')
    client.force_login(anna)

    html = client.get('/projects/', secure=True, headers={'host': 'pulse.example.org'}).content.decode()

    assert f'https://pulse.example.org/p/{project.share_token}/' in html


@pytest.mark.parametrize('count, text', [
    (0, 'No responses yet this week'),
    (1, '1 response this week'),
    (2, '2 responses this week'),
])
def test_count_wording(client, anna, monkeypatch, count, text):
    freeze(monkeypatch, 2026, 9, 29, 9)
    project = Project.objects.create(owner=anna, name='Apollo')
    for _ in range(count):
        submit(project, '2026-W40')
    client.force_login(anna)

    html = client.get('/projects/').content.decode()

    assert f'<p class="project-list__count">{text}</p>' in html


def test_count_covers_current_week_of_own_project_on_sunday_and_monday(client, anna, ben, monkeypatch):
    project = Project.objects.create(owner=anna, name='Apollo')
    other = Project.objects.create(owner=ben, name='Other')
    submit(project, '2026-W40')
    submit(project, '2026-W40')
    submit(project, '2026-W41')
    submit(project, '2026-W39')
    submit(other, '2026-W40')
    client.force_login(anna)

    freeze(monkeypatch, 2026, 10, 4, 12)  # Sunday, 2026-W40
    assert '2 responses this week' in client.get('/projects/').content.decode()

    freeze(monkeypatch, 2026, 10, 5, 12)  # Monday, 2026-W41
    assert '1 response this week' in client.get('/projects/').content.decode()


def test_page_shows_no_individual_ratings(client, anna, monkeypatch):
    freeze(monkeypatch, 2026, 9, 29, 9)
    project = Project.objects.create(owner=anna, name='Apollo')
    Submission.objects.create(project=project, week_key='2026-W40', workload=1, clarity=2, collaboration=4, progress=5)
    client.force_login(anna)

    html = client.get('/projects/').content.decode()

    assert '1 response this week' in html
    for dimension in ('My workload', 'Our goals', 'We work well', 'I am confident'):
        assert dimension not in html


def test_query_count_is_the_same_for_one_and_ten_projects(client, anna, monkeypatch):
    freeze(monkeypatch, 2026, 9, 29, 9)
    client.force_login(anna)
    first = Project.objects.create(owner=anna, name='P0')
    submit(first, '2026-W40')
    client.get('/projects/')  # warm up session and message storage

    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as one:
        client.get('/projects/')
    for i in range(1, 10):
        submit(Project.objects.create(owner=anna, name=f'P{i}'), '2026-W40')
    with CaptureQueriesContext(connection) as ten:
        client.get('/projects/')

    assert len(ten) == len(one)


def test_empty_list_shows_empty_state_and_form(client, anna):
    client.force_login(anna)

    html = client.get('/projects/').content.decode()

    assert '<div class="empty-state">' in html
    assert 'You have no projects yet.' in html
    assert html.index('You have no projects yet.') < html.index('Create project')
    assert 'project-list__item' not in html


# Copy button script

def test_copy_link_script_is_served(client, anna):
    client.force_login(anna)
    Project.objects.create(owner=anna, name='Apollo')
    html = client.get('/projects/').content.decode()

    src = re.search(r'<script src="([^"]*copy-link\.js)"', html).group(1)

    assert client.get(src).status_code == 200


# Create form

def test_form_has_labelled_name_field_and_primary_button(client, anna):
    client.force_login(anna)

    html = client.get('/projects/').content.decode()

    assert '<label class="field__label" for="id_name">Project name</label>' in html
    assert 'class="button button--primary" type="submit">Create project</button>' in html


def test_valid_name_creates_project_and_redirects(client, anna):
    client.force_login(anna)

    response = client.post('/projects/', {'name': 'Apollo'})

    assert response.status_code == 302
    assert response['Location'] == '/projects/'
    project = Project.objects.get()
    assert project.owner == anna
    html = client.get('/projects/').content.decode()
    assert 'Project Apollo created.' in html
    assert 'message--success' in html
    assert f'/projects/{project.pk}/' in html
    assert 'Project Apollo created.' not in client.get('/projects/').content.decode()


def test_new_project_is_first_in_list(client, anna):
    Project.objects.create(owner=anna, name='Older')
    client.force_login(anna)

    client.post('/projects/', {'name': 'Newest'})

    html = client.get('/projects/').content.decode()
    assert html.index('Newest</a>') < html.index('Older</a>')


def test_name_is_stripped(client, anna):
    client.force_login(anna)

    client.post('/projects/', {'name': '  Apollo  '})

    assert Project.objects.get().name == 'Apollo'


@pytest.mark.parametrize('name', ['', '   ', '\t \n'])
def test_blank_name_shows_error_and_creates_nothing(client, anna, name):
    client.force_login(anna)

    response = client.post('/projects/', {'name': name})

    assert response.status_code == 200
    assert 'Enter a project name.' in response.content.decode()
    assert Project.objects.count() == 0


def test_missing_name_shows_error(client, anna):
    client.force_login(anna)

    response = client.post('/projects/', {})

    assert response.status_code == 200
    assert 'Enter a project name.' in response.content.decode()


def test_100_characters_are_accepted(client, anna):
    client.force_login(anna)

    response = client.post('/projects/', {'name': 'a' * 100})

    assert response.status_code == 302
    assert Project.objects.get().name == 'a' * 100


def test_101_characters_are_rejected(client, anna):
    client.force_login(anna)

    response = client.post('/projects/', {'name': 'a' * 101})

    assert response.status_code == 200
    assert 'Use at most 100 characters.' in response.content.decode()
    assert Project.objects.count() == 0


def test_error_page_marks_field_keeps_text_and_shows_list(client, anna):
    Project.objects.create(owner=anna, name='Existing')
    client.force_login(anna)

    response = client.post('/projects/', {'name': 'b' * 101})
    html = response.content.decode()

    assert response.status_code == 200
    assert 'field field--invalid' in html
    assert 'aria-invalid="true"' in html
    assert 'aria-describedby="id_name_error"' in html
    assert '<p class="field__error" id="id_name_error">Use at most 100 characters.</p>' in html
    assert 'value="' + 'b' * 101 + '"' in html
    assert 'Existing' in html


def test_html_in_name_is_escaped_in_list_and_message(client, anna):
    client.force_login(anna)
    name = '<script>alert(1)</script>'

    client.post('/projects/', {'name': name})
    html = client.get('/projects/').content.decode()

    assert name not in html
    assert html.count('&lt;script&gt;alert(1)&lt;/script&gt;') >= 2  # message and list


def test_same_name_is_allowed_with_different_tokens(client, anna, ben):
    for user in (anna, ben, anna):
        client.force_login(user)
        assert client.post('/projects/', {'name': 'Apollo'}).status_code == 302

    tokens = set(Project.objects.values_list('share_token', flat=True))
    assert Project.objects.count() == 3
    assert len(tokens) == 3


def test_share_token_only_appears_in_the_share_link(client, anna):
    client.force_login(anna)

    response = client.post('/projects/', {'name': 'Apollo'})
    token = Project.objects.get().share_token
    html = client.get('/projects/').content.decode()

    assert token not in response['Location']
    assert html.count(token) == 1
    assert f'/p/{token}/' in html


def test_post_without_csrf_token_is_rejected(anna):
    client = Client(enforce_csrf_checks=True)
    client.force_login(anna)

    response = client.post('/projects/', {'name': 'Apollo'})

    assert response.status_code == 403
    assert Project.objects.count() == 0


def test_form_contains_csrf_token(client, anna):
    client.force_login(anna)

    assert 'name="csrfmiddlewaretoken"' in client.get('/projects/').content.decode()
