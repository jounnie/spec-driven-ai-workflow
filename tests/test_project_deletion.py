import logging
import sqlite3

import pytest
from django.core.management import call_command
from django.db import IntegrityError, connections
from django.db.utils import ConnectionHandler
from django.test import Client

from pulse import services
from pulse.models import Project, Submission

from .test_trend_page import DIMENSIONS, PASSWORD, User, submit

NAME_MARKER = 'purge-marker-7f3a91c2'
WEEK_MARKER = '1987-W42'


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
    return f'/projects/{project.pk}/delete/'


def snapshot(project):
    return (
        list(Project.objects.filter(pk=project.pk).values()),
        list(Submission.objects.filter(project=project).order_by('pk').values()),
    )


def counts():
    return Project.objects.count(), Submission.objects.count()


def test_owner_sees_confirmation_page(client, anna, project):
    submit(project, '2026-W40', times=2)
    client.force_login(anna)

    response = client.get(url(project))

    body = response.content.decode()
    assert response.status_code == 200
    assert '<h1>Delete project</h1>' in body
    assert 'This permanently deletes Apollo and all 2 responses. This cannot be undone.' in body
    assert 'Type the project name to confirm' in body
    assert 'button button--danger' in body
    assert f'href="/projects/{project.pk}/">Cancel</a>' in body


@pytest.mark.parametrize('count, text', [(0, '0 responses'), (1, '1 response.')])
def test_confirmation_page_uses_singular_and_zero(client, anna, project, count, text):
    submit(project, '2026-W40', times=count)
    client.force_login(anna)

    response = client.get(url(project))

    assert f'all {text[0]} response' in response.content.decode()
    assert text in response.content.decode()


def test_confirmation_page_escapes_project_name(client, anna):
    project = Project.objects.create(name='<b>x</b>', owner=anna)
    client.force_login(anna)

    body = client.get(url(project)).content.decode()

    assert '&lt;b&gt;x&lt;/b&gt;' in body
    assert '<b>x</b>' not in body


def test_trend_page_links_to_delete_page(client, anna, project):
    client.force_login(anna)

    body = client.get(f'/projects/{project.pk}/').content.decode()

    assert f'class="button button--danger" href="/projects/{project.pk}/delete/">Delete project</a>' in body


@pytest.mark.parametrize('user_fixture', ['ben', 'admin'])
@pytest.mark.parametrize('method', ['get', 'post'])
def test_non_owner_gets_404_and_nothing_is_deleted(client, request, project, user_fixture, method):
    submit(project, '2026-W40')
    client.force_login(request.getfixturevalue(user_fixture))
    before = counts()

    response = getattr(client, method)(url(project), {'confirm_name': 'Apollo'})

    assert response.status_code == 404
    assert 'Apollo' not in response.content.decode()
    assert counts() == before


@pytest.mark.parametrize('method', ['get', 'post'])
def test_unknown_project_returns_404(client, anna, method):
    client.force_login(anna)

    response = getattr(client, method)('/projects/9999/delete/', {'confirm_name': 'x'})

    assert response.status_code == 404


@pytest.mark.parametrize('method', ['get', 'post'])
def test_anonymous_is_redirected_to_login(client, project, method):
    submit(project, '2026-W40')
    before = counts()

    response = getattr(client, method)(url(project), {'confirm_name': 'Apollo'})

    assert response.status_code == 302
    assert response['Location'].startswith('/login/')
    assert counts() == before


@pytest.mark.parametrize('method', ['put', 'delete', 'patch'])
def test_other_methods_return_405(client, anna, project, method):
    client.force_login(anna)
    before = counts()

    response = getattr(client, method)(url(project))

    assert response.status_code == 405
    assert counts() == before


def test_post_without_csrf_token_is_rejected(anna, project):
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(anna)

    response = csrf_client.post(url(project), {'confirm_name': 'Apollo'})

    assert response.status_code == 403
    assert Project.objects.filter(pk=project.pk).exists()


def test_get_deletes_nothing(client, anna, project):
    submit(project, '2026-W40', times=3)
    client.force_login(anna)
    before = counts()

    client.get(url(project))

    assert counts() == before


@pytest.mark.parametrize('typed', ['', 'apollo', 'Apol', 'Apollo x'])
def test_wrong_name_shows_field_error_and_deletes_nothing(client, anna, project, typed):
    submit(project, '2026-W40')
    client.force_login(anna)
    before = counts()

    response = client.post(url(project), {'confirm_name': typed})

    body = response.content.decode()
    assert response.status_code == 200
    assert 'field__error' in body
    assert 'aria-invalid="true"' in body
    assert counts() == before


def test_missing_name_field_shows_field_error(client, anna, project):
    client.force_login(anna)

    response = client.post(url(project), {})

    assert response.status_code == 200
    assert 'field__error' in response.content.decode()
    assert Project.objects.filter(pk=project.pk).exists()


def test_inner_spaces_count(client, anna):
    project = Project.objects.create(name='Big  Apollo', owner=anna)
    client.force_login(anna)

    response = client.post(url(project), {'confirm_name': 'Big Apollo'})

    assert response.status_code == 200
    assert Project.objects.filter(pk=project.pk).exists()


def test_matching_post_deletes_and_redirects_with_message(client, anna, project):
    submit(project, '2026-W40')
    submit(project, '2026-W41')
    client.force_login(anna)

    response = client.post(url(project), {'confirm_name': '  Apollo  '})

    assert response.status_code == 302
    assert response['Location'] == '/projects/'
    assert counts() == (0, 0)
    page = client.get('/projects/')
    assert 'Project Apollo deleted.' in page.content.decode()
    assert '/projects/%d/' % project.pk not in page.content.decode()


def test_deleted_project_urls_return_404(client, anna, project):
    token, pk = project.share_token, project.pk
    client.force_login(anna)
    client.post(url(project), {'confirm_name': 'Apollo'})

    assert client.get(f'/p/{token}/').status_code == 404
    assert client.post(f'/p/{token}/', {name: 3 for name in DIMENSIONS}).status_code == 404
    assert client.get(f'/projects/{pk}/').status_code == 404
    assert client.get(f'/projects/{pk}/delete/').status_code == 404
    assert client.post(f'/projects/{pk}/delete/', {'confirm_name': 'Apollo'}).status_code == 404


def test_other_projects_are_untouched(client, anna, ben, project):
    submit(project, '2026-W40')
    sibling = Project.objects.create(name='Sibling', owner=anna)
    foreign = Project.objects.create(name='Foreign', owner=ben)
    for other in (sibling, foreign):
        submit(other, '2026-W40', (1, 2, 3, 4), times=2)
        submit(other, '2026-W41', (5, 4, 3, 2))
    before = [snapshot(sibling), snapshot(foreign)]
    client.force_login(anna)

    client.post(url(project), {'confirm_name': 'Apollo'})

    assert [snapshot(sibling), snapshot(foreign)] == before
    assert Submission.objects.filter(project=project).count() == 0


def test_respondent_cookie_of_deleted_project_is_harmless(client, anna, project):
    token = project.share_token
    client.post(f'/p/{token}/', {name: 3 for name in DIMENSIONS})
    assert client.cookies['pulse_submitted'].value
    client.force_login(anna)
    client.post(url(project), {'confirm_name': 'Apollo'})

    assert client.get(f'/p/{token}/').status_code == 404
    new = Project.objects.create(name='Apollo', owner=anna)
    assert new.pk != project.pk and new.share_token != token
    assert client.get(f'/p/{new.share_token}/').status_code == 200


def test_failure_during_delete_rolls_back(client, anna, project, monkeypatch):
    submit(project, '2026-W40')
    client.force_login(anna)
    client.raise_request_exception = False
    original = Project.delete

    def failing_delete(self, *args, **kwargs):
        Submission.objects.filter(project=self).delete()
        raise RuntimeError('boom')

    monkeypatch.setattr(Project, 'delete', failing_delete)

    response = client.post(url(project), {'confirm_name': 'Apollo'})
    monkeypatch.setattr(Project, 'delete', original)

    assert response.status_code == 500
    assert counts() == (1, 1)
    assert 'deleted.' not in client.get('/projects/').content.decode()


@pytest.mark.django_db(transaction=True)
def test_stale_project_cannot_get_new_submission(anna, project):
    stale = Project.objects.get(pk=project.pk)
    services.delete_project(project)

    with pytest.raises(IntegrityError):
        Submission.objects.create(project=stale, week_key='2026-W40', **dict.fromkeys(DIMENSIONS, 3))


class FailingConnection:
    def cursor(self):
        raise sqlite3.OperationalError('database is locked')


@pytest.mark.django_db(transaction=True)
def test_purge_failure_is_logged_and_deletion_stays(client, anna, project, monkeypatch, caplog):
    submit(project, '2026-W40')
    client.force_login(anna)
    monkeypatch.setattr(services, 'connection', FailingConnection())

    with caplog.at_level(logging.WARNING, logger='pulse.services'):
        response = client.post(url(project), {'confirm_name': 'Apollo'})
    monkeypatch.undo()

    assert response.status_code == 302
    assert counts() == (0, 0)
    assert any(str(project.pk) in r.getMessage() and r.levelno >= logging.WARNING for r in caplog.records)
    assert all('Apollo' not in r.getMessage() for r in caplog.records)
    assert 'Project Apollo deleted.' in client.get('/projects/').content.decode()


@pytest.fixture
def file_database(tmp_path, settings, transactional_db):
    """Make ``default`` a real, migrated database file for the test."""
    path = tmp_path / 'purge.sqlite3'
    databases = ConnectionHandler({'default': {**settings.DATABASES['default'], 'NAME': path}})
    original = connections['default']
    connections['default'] = databases['default']
    try:
        call_command('migrate', verbosity=0)
        yield path
    finally:
        connections['default'].close()
        connections['default'] = original


def files_bytes(path):
    wal = path.with_name(path.name + '-wal')
    return path.read_bytes() + (wal.read_bytes() if wal.exists() else b'')


@pytest.mark.django_db(transaction=True)
def test_deleted_project_is_purged_from_database_file(file_database, client):
    anna = User.objects.create_user('anna', password=PASSWORD)
    doomed = Project.objects.create(name=NAME_MARKER, owner=anna)
    survivor = Project.objects.create(name='survivor-marker-51c0de77', owner=anna)
    submit(doomed, WEEK_MARKER, times=3)
    submit(survivor, '1988-W17', times=2)
    with connections['default'].cursor() as cursor:
        cursor.execute('PRAGMA wal_checkpoint(PASSIVE)')
    before = files_bytes(file_database)
    assert NAME_MARKER.encode() in before
    assert WEEK_MARKER.encode() in before

    client.force_login(anna)
    response = client.post(url(doomed), {'confirm_name': NAME_MARKER})
    assert response.status_code == 302
    with connections['default'].cursor() as cursor:
        cursor.execute('PRAGMA integrity_check')
        assert cursor.fetchone()[0] == 'ok'
    connections['default'].close()

    after = files_bytes(file_database)
    assert NAME_MARKER.encode() not in after
    assert WEEK_MARKER.encode() not in after
    assert b'survivor-marker-51c0de77' in after
    assert b'1988-W17' in after
    assert Submission.objects.filter(project=survivor).count() == 2
