import re
import threading

import pytest
from django.core.management import call_command
from django.db import connection, connections
from django.test import Client

from pulse import services, views
from pulse.models import Project, Submission

RATINGS = {name: '3' for name in ('workload', 'clarity', 'collaboration', 'progress')}
UNKNOWN_TOKEN = 'A' * 43


@pytest.fixture
def file_database(tmp_path, transactional_db):
    """Point `default` at a real, migrated SQLite file, for every thread.

    Other threads open their own connections from the settings, so the name
    is changed there, not only on this thread's connection.
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


def make_project(django_user_model):
    owner = django_user_model.objects.create_user('owner', password='secret-pw')
    return Project.objects.create(owner=owner, name='Apollo')


def delete_in_thread(project_id):
    def run():
        try:
            services.delete_project(Project.objects.get(pk=project_id))
        finally:
            connection.close()

    thread = threading.Thread(target=run)
    thread.start()
    thread.join(timeout=30)
    assert not thread.is_alive()


def without_csrf_token(response):
    # The masked token in the page differs on every request.
    return re.sub(r'"X-CSRFToken": "[^"]*"', '', response.content.decode())


def assert_not_found(response):
    assert response.status_code == 404
    assert 'Page not found' in response.content.decode()
    assert 'This page does not exist.' in response.content.decode()
    assert 'csrftoken' not in response.cookies


@pytest.mark.django_db
def test_deleted_project_pages_are_not_found(client, django_user_model):
    project = make_project(django_user_model)
    token = project.share_token
    services.delete_project(project)

    assert_not_found(client.get(f'/p/{token}/'))
    thanks = client.get(f'/p/{token}/thanks/')
    assert thanks.status_code == 404
    assert 'Page not found' in thanks.content.decode()
    assert_not_found(client.post(f'/p/{token}/', RATINGS))
    assert Submission.objects.count() == 0


@pytest.mark.django_db
def test_unknown_and_deleted_project_return_the_same_page(client, django_user_model):
    project = make_project(django_user_model)
    token = project.share_token
    services.delete_project(project)

    unknown = client.post(f'/p/{UNKNOWN_TOKEN}/', RATINGS)
    deleted = client.post(f'/p/{token}/', RATINGS)

    assert_not_found(unknown)
    assert without_csrf_token(unknown) == without_csrf_token(deleted)


@pytest.mark.django_db(transaction=True)
def test_post_after_deletion_in_other_thread_is_not_found(file_database, django_user_model):
    project = make_project(django_user_model)
    client = Client(enforce_csrf_checks=True)
    page = client.get(f'/p/{project.share_token}/')
    csrf = page.cookies['csrftoken'].value
    delete_in_thread(project.pk)

    response = client.post(f'/p/{project.share_token}/', {**RATINGS, 'csrfmiddlewaretoken': csrf})

    assert_not_found(response)
    assert Submission.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_deletion_between_lookup_and_transaction_is_not_found(file_database, django_user_model, monkeypatch):
    """The project exists at the first lookup and is gone when the write lock is taken."""
    project = make_project(django_user_model)
    original = views.project_for_token

    def lookup_then_delete(token):
        found = original(token)
        delete_in_thread(found.pk)
        return found

    monkeypatch.setattr(views, 'project_for_token', lookup_then_delete)

    response = Client().post(f'/p/{project.share_token}/', RATINGS)

    assert_not_found(response)
    assert Submission.objects.count() == 0
