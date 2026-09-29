from datetime import timedelta

import pytest
from django.contrib import admin as django_admin
from django.contrib.admin.models import LogEntry
from django.contrib.auth import get_user_model
from django.utils import timezone

from pulse import services
from pulse.models import Invitation, Project, Submission

from .test_trend_page import PASSWORD, submit

User = get_user_model()
WEEK = '1987-W42'
# a rating pattern that cannot be confused with ids or dates in the HTML
RATINGS = (5, 5, 5, 5)


@pytest.fixture
def admin_user(db):
    return User.objects.create_user('root', password=PASSWORD, is_staff=True, is_superuser=True)


@pytest.fixture
def anna(db):
    return User.objects.create_user('anna', password=PASSWORD)


@pytest.fixture
def ben(db):
    return User.objects.create_user('ben', password=PASSWORD)


@pytest.fixture
def project(anna):
    project = Project.objects.create(name='Apollo', owner=anna)
    submit(project, WEEK, RATINGS, times=3)
    return project


@pytest.fixture
def staff(client, admin_user):
    client.force_login(admin_user)
    return client


def get_html(client, url):
    response = client.get(url)
    return response.status_code, response.content.decode()


def assert_no_ratings(html):
    assert WEEK not in html
    assert 'Submission' not in html
    assert 'workload' not in html.lower()


def bulk_delete(client, projects, confirm=False):
    data = {'action': 'delete_selected', '_selected_action': [p.pk for p in projects]}
    if confirm:
        data['post'] = 'yes'
    return client.post('/admin/pulse/project/', data)


def test_submission_is_not_registered_in_the_admin():
    for model, model_admin in django_admin.site._registry.items():
        assert model is not Submission
        for inline in model_admin.inlines:
            assert inline.model is not Submission


def test_submission_admin_urls_return_404(staff, project):
    submission = Submission.objects.first()
    for url in (
        '/admin/pulse/submission/',
        '/admin/pulse/submission/add/',
        f'/admin/pulse/submission/{submission.pk}/change/',
        f'/admin/pulse/submission/{submission.pk}/delete/',
        f'/admin/pulse/submission/{submission.pk}/history/',
        '/admin/pulse/submission/export/',
    ):
        assert staff.get(url).status_code == 404


def test_submission_autocomplete_exposes_only_project_names(staff, project):
    response = staff.get(
        '/admin/autocomplete/?app_label=pulse&model_name=submission&field_name=project&term='
    )

    if response.status_code == 200:
        assert response.json()['results'] == [{'id': str(project.pk), 'text': 'Apollo'}]
    else:
        assert response.status_code in (403, 404)


def test_admin_index_lists_no_submissions(staff, project):
    status, html = get_html(staff, '/admin/')

    assert status == 200
    assert 'Submission' not in html


def test_project_list_shows_no_ratings(staff, project):
    status, html = get_html(staff, '/admin/pulse/project/')

    assert status == 200
    assert 'Apollo' in html
    assert_no_ratings(html)


def test_project_list_shows_owner_and_creation_date_columns(staff, project):
    _, html = get_html(staff, '/admin/pulse/project/')

    assert 'column-name' in html
    assert 'column-owner' in html
    assert 'column-created_at' in html
    assert 'anna' in html
    assert 'sortable' in html


def test_project_list_can_be_sorted_by_owner(staff, anna, ben):
    Project.objects.create(name='A', owner=ben)
    Project.objects.create(name='B', owner=anna)

    response = staff.get('/admin/pulse/project/?o=2')

    assert [p.owner.username for p in response.context['cl'].result_list] == ['anna', 'ben']


def test_project_list_search_is_a_case_insensitive_substring_match(staff, anna):
    Project.objects.create(name='Apollo', owner=anna)
    Project.objects.create(name='Gemini', owner=anna)

    response = staff.get('/admin/pulse/project/?q=POLL')

    assert [p.name for p in response.context['cl'].result_list] == ['Apollo']


def test_project_change_page_shows_no_ratings_or_share_token(staff, project):
    status, html = get_html(staff, f'/admin/pulse/project/{project.pk}/change/')

    assert status == 200
    assert_no_ratings(html)
    assert project.share_token not in html
    assert 'share_token' not in html


def test_project_add_page_shows_no_ratings(staff, project):
    status, html = get_html(staff, '/admin/pulse/project/add/')

    assert status == 200
    assert_no_ratings(html)


def test_project_history_page_shows_no_ratings(staff, project):
    status, html = get_html(staff, f'/admin/pulse/project/{project.pk}/history/')

    assert status == 200
    assert_no_ratings(html)


def test_project_autocomplete_never_exposes_ratings(staff, project):
    response = staff.get('/admin/autocomplete/?app_label=pulse&model_name=project&field_name=owner&term=')

    assert WEEK not in response.content.decode()


def test_share_token_is_not_editable(staff, project):
    assert Project._meta.get_field('share_token').editable is False
    old = project.share_token

    staff.post(
        f'/admin/pulse/project/{project.pk}/change/',
        {'name': 'Apollo', 'owner': project.owner_id, 'share_token': 'hacked'},
    )

    project.refresh_from_db()
    assert project.share_token == old


def test_project_owner_can_be_changed_and_appears_in_history(staff, project, ben):
    response = staff.post(
        f'/admin/pulse/project/{project.pk}/change/', {'name': 'Apollo', 'owner': ben.pk}
    )

    assert response.status_code == 302
    project.refresh_from_db()
    assert project.owner == ben
    assert 'Owner' in LogEntry.objects.get(object_id=str(project.pk)).get_change_message()
    _, html = get_html(staff, f'/admin/pulse/project/{project.pk}/history/')
    assert 'Changed' in html


def test_inactive_users_are_not_offered_as_owner(staff, project, ben):
    ben.is_active = False
    ben.save()

    _, html = get_html(staff, f'/admin/pulse/project/{project.pk}/change/')

    assert '>anna<' in html
    assert '>ben<' not in html


def test_project_cannot_be_assigned_to_an_inactive_user(staff, project, ben):
    ben.is_active = False
    ben.save()

    response = staff.post(
        f'/admin/pulse/project/{project.pk}/change/', {'name': 'Apollo', 'owner': ben.pk}
    )

    assert response.status_code == 200
    project.refresh_from_db()
    assert project.owner.username == 'anna'


def test_project_of_a_deactivated_lead_can_still_be_managed(staff, project, anna, ben):
    anna.is_active = False
    anna.save()

    _, html = get_html(staff, f'/admin/pulse/project/{project.pk}/change/')
    assert '>anna<' in html
    renamed = staff.post(
        f'/admin/pulse/project/{project.pk}/change/', {'name': 'Apollo 2', 'owner': anna.pk}
    )
    reassigned = staff.post(
        f'/admin/pulse/project/{project.pk}/change/', {'name': 'Apollo 2', 'owner': ben.pk}
    )

    assert renamed.status_code == 302
    assert reassigned.status_code == 302
    project.refresh_from_db()
    assert (project.name, project.owner) == ('Apollo 2', ben)


def test_single_delete_confirmation_shows_no_ratings(staff, project):
    status, html = get_html(staff, f'/admin/pulse/project/{project.pk}/delete/')

    assert status == 200
    assert 'Apollo' in html
    assert_no_ratings(html)
    assert '5, 5, 5, 5' not in html


def test_bulk_delete_confirmation_shows_only_a_count(staff, anna):
    projects = [Project.objects.create(name=f'Secret{i}', owner=anna) for i in range(3)]
    for p in projects:
        submit(p, WEEK, RATINGS)

    response = bulk_delete(staff, projects)
    html = response.content.decode()

    assert response.status_code == 200
    assert 'Are you sure you want to delete 3 projects?' in html
    assert 'Secret' not in html
    assert_no_ratings(html)
    assert Project.objects.count() == 3


def test_admin_delete_uses_delete_project(staff, project, monkeypatch):
    calls = []
    monkeypatch.setattr(services, 'delete_project', lambda p: (calls.append(p.pk), p.delete()))

    staff.post(f'/admin/pulse/project/{project.pk}/delete/', {'post': 'yes'})

    assert calls == [project.pk]
    assert not Project.objects.exists()
    assert not Submission.objects.exists()


def test_admin_bulk_delete_uses_delete_project(staff, anna, monkeypatch):
    projects = [Project.objects.create(name=f'P{i}', owner=anna) for i in range(3)]
    submit(projects[0], WEEK, RATINGS)
    calls = []
    monkeypatch.setattr(services, 'delete_project', lambda p: (calls.append(p.pk), p.delete()))

    response = bulk_delete(staff, projects, confirm=True)

    assert response.status_code == 302
    assert sorted(calls) == sorted(p.pk for p in projects)
    assert not Project.objects.exists()
    assert not Submission.objects.exists()


@pytest.mark.django_db(transaction=True)
def test_admin_delete_purges_the_database_file(client, admin_user, anna, monkeypatch):
    purged = []
    monkeypatch.setattr(services, 'purge_database_file', purged.append)
    project = Project.objects.create(name='Apollo', owner=anna)
    client.force_login(admin_user)

    client.post(f'/admin/pulse/project/{project.pk}/delete/', {'post': 'yes'})

    assert purged == [project.pk]


def test_deactivated_lead_cannot_log_in_but_share_link_works(client, project, anna):
    anna.is_active = False
    anna.save()

    login = client.post('/login/', {'username': 'anna', 'password': PASSWORD})
    share = client.get(f'/p/{project.share_token}/')

    assert '_auth_user_id' not in client.session
    assert login.status_code == 200
    assert share.status_code == 200


def test_user_admin_can_deactivate_a_lead(staff, anna):
    assert django_admin.site.is_registered(User)

    response = staff.get(f'/admin/auth/user/{anna.pk}/change/')

    assert response.status_code == 200
    assert 'name="is_active"' in response.content.decode()


def test_invitation_list_shows_columns_and_status(staff, admin_user):
    now = timezone.now()
    Invitation.objects.create(created_by=admin_user)
    Invitation.objects.create(created_by=admin_user, expires_at=now - timedelta(days=1))
    Invitation.objects.create(created_by=admin_user, used_at=now)
    Invitation.objects.create(created_by=admin_user, revoked_at=now)

    response = staff.get('/admin/pulse/invitation/')
    html = response.content.decode()

    for column in ('created_by', 'created_at', 'expires_at', 'status'):
        assert f'column-{column}' in html
    rows = {row.pk: row for row in response.context['cl'].result_list}
    statuses = [
        django_admin.site._registry[Invitation].status(i) for i in Invitation.objects.order_by('pk')
    ]
    assert statuses == ['open', 'expired', 'used', 'revoked']
    assert len(rows) == 4


@pytest.mark.parametrize('status', ['open', 'expired', 'used', 'revoked'])
def test_invitation_list_filters_by_status(staff, admin_user, status):
    now = timezone.now()
    Invitation.objects.create(created_by=admin_user)
    Invitation.objects.create(created_by=admin_user, expires_at=now - timedelta(days=1))
    Invitation.objects.create(created_by=admin_user, used_at=now)
    Invitation.objects.create(created_by=admin_user, revoked_at=now)

    response = staff.get(f'/admin/pulse/invitation/?status={status}')
    model_admin = django_admin.site._registry[Invitation]

    result = list(response.context['cl'].result_list)
    assert [model_admin.status(i) for i in result] == [status]


def test_invitation_list_is_filterable_by_date(staff, admin_user):
    old = Invitation.objects.create(created_by=admin_user, created_at=timezone.now() - timedelta(days=60))
    recent = Invitation.objects.create(created_by=admin_user)

    response = staff.get('/admin/pulse/invitation/')
    date_filter = next(f for f in response.context['cl'].filter_specs if getattr(f, 'field_path', None) == 'created_at')
    past_7_days = next(c for c in date_filter.choices(response.context['cl']) if c['display'] == 'Past 7 days')
    filtered = staff.get('/admin/pulse/invitation/' + past_7_days['query_string'])

    assert list(filtered.context['cl'].result_list) == [recent]
    assert old.pk


def test_non_staff_lead_cannot_use_the_admin(client, anna, project):
    login = client.post(
        '/admin/login/?next=/admin/',
        {'username': 'anna', 'password': PASSWORD, 'next': '/admin/'},
    )
    assert login.status_code == 200
    assert '_auth_user_id' not in client.session

    client.force_login(anna)
    for url in ('/admin/', '/admin/pulse/project/', f'/admin/pulse/project/{project.pk}/change/'):
        response = client.get(url)
        assert response.status_code in (302, 403, 404)
        if response.status_code == 302:
            assert response['Location'].startswith('/admin/login/')
