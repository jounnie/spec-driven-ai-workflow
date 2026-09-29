import threading

import pytest
from django.db import connection
from django.test import Client

from pulse.models import Project, Submission

from .test_invitations import file_database  # noqa: F401 - fixture
from .test_trend_page import PASSWORD, User, submit

FIELDS = ('workload', 'clarity', 'collaboration', 'progress')
PARAGRAPH = (
    'The current link will stop working immediately. Everyone on your team will need '
    'the new link. People who already responded this week may be able to respond again.'
)


@pytest.fixture
def admin(db):
    return User.objects.create_user('admin', password=PASSWORD, is_superuser=True, is_staff=True)


@pytest.fixture
def anna(db):
    return User.objects.create_user('anna', password=PASSWORD)


@pytest.fixture
def ben(db):
    return User.objects.create_user('ben', password=PASSWORD)


@pytest.fixture
def project(anna):
    return Project.objects.create(name='Apollo', owner=anna)


def url(project):
    return f'/projects/{project.pk}/regenerate-link/'


def valid():
    return {name: '3' for name in FIELDS}


def test_confirmation_page_shows_form_and_changes_nothing(client, anna, project):
    token = project.share_token
    client.force_login(anna)

    response = client.get(url(project) + '?foo=bar')
    html = response.content.decode()

    assert response.status_code == 200
    assert '<h1>Regenerate share link</h1>' in html
    assert PARAGRAPH in html
    assert 'method="post"' in html
    assert f'action="{url(project)}"' in html
    assert 'csrfmiddlewaretoken' in html
    assert 'button--danger' in html and 'Regenerate share link</button>' in html
    assert f'href="/projects/{project.pk}/">Cancel' in html
    assert 'name="confirm_name"' not in html
    project.refresh_from_db()
    assert project.share_token == token


def test_anonymous_visitor_is_redirected_to_login(client, project):
    for method in (client.get, client.post):
        response = method(url(project))
        assert response.status_code == 302
        assert response['Location'].startswith('/login/')
    token = project.share_token
    project.refresh_from_db()
    assert project.share_token == token


@pytest.mark.parametrize('who', ['ben', 'admin'])
def test_non_owner_gets_404_and_nothing_changes(client, project, who, ben, admin):
    token = project.share_token
    client.force_login({'ben': ben, 'admin': admin}[who])

    assert client.get(url(project)).status_code == 404
    assert client.post(url(project)).status_code == 404
    project.refresh_from_db()
    assert project.share_token == token


def test_missing_project_gives_404(client, anna, project):
    client.force_login(anna)

    assert client.get('/projects/9999/regenerate-link/').status_code == 404
    assert client.post('/projects/9999/regenerate-link/').status_code == 404


def test_trend_page_links_to_confirmation_page(client, anna, project):
    client.force_login(anna)

    html = client.get(f'/projects/{project.pk}/').content.decode()

    assert f'href="{url(project)}"' in html
    assert 'Create new share link' in html


def test_post_replaces_token_and_old_link_gives_404(client, anna, project):
    old = project.share_token
    client.force_login(anna)

    response = client.post(url(project))

    assert response.status_code == 302
    assert response['Location'] == f'/projects/{project.pk}/'
    project.refresh_from_db()
    assert project.share_token != old
    assert len(project.share_token) >= 43
    assert Client().get(f'/p/{old}/').status_code == 404
    assert Client().get(f'/p/{project.share_token}/').status_code == 200


def test_trend_page_shows_new_link_and_flash(client, anna, project):
    client.force_login(anna)

    response = client.post(url(project), follow=True)
    html = response.content.decode()
    project.refresh_from_db()

    assert 'New share link created.' in html
    assert f'/p/{project.share_token}/</code>' in html
    assert 'data-copy-target' in html and 'aria-live="polite"' in html


def test_dashboard_shows_new_link(client, anna, project):
    client.force_login(anna)
    client.post(url(project))
    project.refresh_from_db()

    html = client.get('/projects/').content.decode()

    assert f'/p/{project.share_token}/' in html


def test_submissions_and_trend_are_unchanged(client, anna, project):
    submit(project, '2026-W38', (1, 2, 3, 4), times=2)
    submit(project, '2026-W39', (5, 5, 4, 4), times=3)
    rows = list(Submission.objects.order_by('pk').values())
    client.force_login(anna)
    before = client.get(f'/projects/{project.pk}/').content.decode()

    client.post(url(project))
    after = client.get(f'/projects/{project.pk}/').content.decode()
    project.refresh_from_db()

    assert list(Submission.objects.order_by('pk').values()) == rows
    strip = lambda html, token: html.replace(token, 'TOKEN')  # noqa: E731
    old = Project.objects.get(pk=project.pk)
    assert 'TOKEN' in strip(after, project.share_token)
    assert strip(after, project.share_token).split('<tbody>')[1].split('</tbody>')[0] == (
        before.split('<tbody>')[1].split('</tbody>')[0]
    )
    assert old.share_token == project.share_token


def test_cookie_of_old_link_does_not_block_new_link(anna, project):
    respondent = Client()
    old_url = f'/p/{project.share_token}/'
    assert respondent.post(old_url, valid()).status_code == 302
    assert 'already responded' in respondent.get(old_url).content.decode()

    owner = Client()
    owner.force_login(anna)
    owner.post(url(project))
    project.refresh_from_db()
    new_url = f'/p/{project.share_token}/'

    assert respondent.get(old_url).status_code == 404
    page = respondent.get(new_url)
    assert page.status_code == 200
    assert 'already responded' not in page.content.decode()
    assert respondent.post(new_url, valid()).status_code == 302
    assert Submission.objects.filter(project=project).count() == 2


def test_submission_to_old_link_before_regeneration_is_kept(anna, project):
    old_url = f'/p/{project.share_token}/'
    assert Client().post(old_url, valid()).status_code == 302
    owner = Client()
    owner.force_login(anna)

    owner.post(url(project))

    assert Submission.objects.filter(project=project).count() == 1
    assert Client().post(old_url, valid()).status_code == 404
    assert Submission.objects.filter(project=project).count() == 1


def test_regenerate_skips_a_token_that_is_already_taken(monkeypatch, project, anna):
    other = Project.objects.create(name='Zeus', owner=anna)
    tokens = iter([other.share_token, 'fresh-token-value'])
    monkeypatch.setattr('pulse.models.generate_share_token', lambda: next(tokens))

    project.regenerate_share_token()

    project.refresh_from_db()
    assert project.share_token == 'fresh-token-value'


def test_regenerate_saves_only_the_token(project):
    project.name = 'Changed in memory'

    project.regenerate_share_token()

    assert Project.objects.get(pk=project.pk).name == 'Apollo'


def test_submission_and_regeneration_at_the_same_time_both_succeed(file_database):  # noqa: F811
    anna = User.objects.create_user('anna', password=PASSWORD)
    project = Project.objects.create(name='Apollo', owner=anna)
    old_url = f'/p/{project.share_token}/'
    results = {}
    errors = []

    def submit_form():
        try:
            results['submit'] = Client().post(old_url, valid()).status_code
        except Exception as exc:  # noqa: BLE001 - reported below
            errors.append(exc)
        finally:
            connection.close()

    def regenerate():
        try:
            client = Client()
            client.force_login(anna)
            results['regenerate'] = client.post(url(project)).status_code
        except Exception as exc:  # noqa: BLE001 - reported below
            errors.append(exc)
        finally:
            connection.close()

    threads = [threading.Thread(target=submit_form), threading.Thread(target=regenerate)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30)

    assert not errors
    assert results['regenerate'] == 302
    assert results['submit'] in (302, 404)
    assert Submission.objects.filter(project=project).count() == (1 if results['submit'] == 302 else 0)
    assert Project.objects.get(pk=project.pk).share_token not in old_url
