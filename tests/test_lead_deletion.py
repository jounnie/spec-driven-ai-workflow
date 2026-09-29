import pytest
from django.contrib.auth import get_user_model
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from pulse.models import Invitation, Project

from .test_password_reset import PASSWORD, create_link

User = get_user_model()


@pytest.fixture
def root(db):
    return User.objects.create_user('root', password=PASSWORD, is_staff=True, is_superuser=True)


@pytest.fixture
def staff(client, root):
    client.force_login(root)
    return client


@pytest.fixture
def anna(db):
    return User.objects.create_user('anna', password=PASSWORD)


def assert_link_invalid(path):
    client = Client()
    response = client.get(path)
    if response.status_code == 302:
        response = client.get(response['Location'])
    assert response.status_code == 404


def delete_url(user):
    return reverse('admin:auth_user_delete', args=[user.pk])


def change_url(user):
    return reverse('admin:auth_user_change', args=[user.pk])


def confirm_delete(client, user):
    return client.post(delete_url(user), {'post': 'yes'})


def bulk_delete(client, users, confirm=False):
    data = {'action': 'delete_selected', '_selected_action': [u.pk for u in users]}
    if confirm:
        data['post'] = 'yes'
    return client.post(reverse('admin:auth_user_changelist'), data, follow=True)


def change_active(client, user, active):
    data = {
        'username': user.username,
        'date_joined_0': user.date_joined.strftime('%Y-%m-%d'),
        'date_joined_1': user.date_joined.strftime('%H:%M:%S'),
    }
    for flag in ('is_staff', 'is_superuser'):
        if getattr(user, flag):
            data[flag] = 'on'
    if active:
        data['is_active'] = 'on'
    return client.post(change_url(user), data)


def test_user_without_projects_can_be_deleted(staff, anna):
    response = confirm_delete(staff, anna)

    assert response.status_code == 302
    assert not User.objects.filter(pk=anna.pk).exists()


def test_deleting_user_keeps_invitations_with_null_references(staff, root, anna):
    created = Invitation.objects.create(created_by=anna, expires_at=timezone.now())
    used = Invitation.objects.create(created_by=root, used_by=anna, used_at=timezone.now(), expires_at=timezone.now())

    confirm_delete(staff, anna)

    created.refresh_from_db()
    used.refresh_from_db()
    assert created.created_by is None
    assert used.used_by is None and used.created_by == root


def test_user_with_projects_is_refused_and_projects_are_named(staff, anna):
    Project.objects.create(name='Apollo', owner=anna)
    Project.objects.create(name='Gemini', owner=anna)

    page = staff.get(delete_url(anna))
    html = page.content.decode()

    assert 'Apollo' in html and 'Gemini' in html
    assert 'protected' in html
    assert confirm_delete(staff, anna).status_code == 200
    assert User.objects.filter(pk=anna.pk).exists()
    assert Project.objects.count() == 2


def test_bulk_delete_refuses_when_any_selected_user_owns_projects(staff, anna):
    ben = User.objects.create_user('ben', password=PASSWORD)
    Project.objects.create(name='Apollo', owner=anna)

    response = bulk_delete(staff, [anna, ben], confirm=True)

    assert 'Apollo' in response.content.decode()
    assert User.objects.filter(pk__in=[anna.pk, ben.pk]).count() == 2


def test_bulk_delete_removes_users_without_projects(staff, anna):
    bulk_delete(staff, [anna], confirm=True)

    assert not User.objects.filter(pk=anna.pk).exists()


def test_last_active_superuser_cannot_be_deleted(staff, root):
    response = staff.get(delete_url(root), follow=True)

    assert 'last active superuser' in response.content.decode()
    assert staff.post(delete_url(root), {'post': 'yes'}).status_code == 302
    assert User.objects.filter(pk=root.pk).exists()


def test_last_active_superuser_cannot_be_bulk_deleted(staff, root, anna):
    response = bulk_delete(staff, [root, anna], confirm=True)

    assert 'last active superuser' in response.content.decode()
    assert User.objects.filter(pk__in=[root.pk, anna.pk]).count() == 2


def test_last_active_superuser_cannot_be_deactivated(staff, root):
    response = change_active(staff, root, False)

    assert response.status_code == 200
    assert 'last active superuser' in response.content.decode()
    root.refresh_from_db()
    assert root.is_active


def test_inactive_superuser_does_not_count_as_another_superuser(staff, root):
    User.objects.create_user('old', password=PASSWORD, is_staff=True, is_superuser=True, is_active=False)

    assert staff.get(delete_url(root), follow=True).redirect_chain
    assert User.objects.filter(pk=root.pk).exists()


def test_superuser_can_be_deleted_and_deactivated_with_another_active_one(staff, root):
    second = User.objects.create_user('second', password=PASSWORD, is_staff=True, is_superuser=True)
    third = User.objects.create_user('third', password=PASSWORD, is_staff=True, is_superuser=True)

    assert change_active(staff, second, False).status_code == 302
    second.refresh_from_db()
    assert not second.is_active
    assert confirm_delete(staff, third).status_code == 302
    assert not User.objects.filter(pk=third.pk).exists()


def test_deactivated_lead_cannot_log_in_and_reactivating_restores_access(client, staff, anna):
    change_active(staff, anna, False)
    anna.refresh_from_db()
    assert not anna.is_active

    other = type(client)()
    assert not other.login(username='anna', password=PASSWORD)

    change_active(staff, anna, True)
    assert other.login(username='anna', password=PASSWORD)


def test_deactivating_invalidates_sessions(client, root, anna):
    lead_client = type(client)()
    lead_client.force_login(anna)
    assert lead_client.get(reverse('projects')).status_code == 200

    client.force_login(root)
    change_active(client, anna, False)

    response = lead_client.get(reverse('projects'))
    assert response.status_code == 302 and response['Location'].startswith('/login/')


def test_deleting_invalidates_sessions(client, root, anna):
    lead_client = type(client)()
    lead_client.force_login(anna)
    client.force_login(root)

    confirm_delete(client, anna)

    response = lead_client.get(reverse('projects'))
    assert response.status_code == 302 and response['Location'].startswith('/login/')


def test_deactivated_leads_projects_and_share_links_keep_working(client, staff, anna):
    project = Project.objects.create(name='Apollo', owner=anna)

    change_active(staff, anna, False)

    assert client.get(reverse('respond', args=[project.share_token])).status_code == 200
    assert Project.objects.filter(pk=project.pk, owner=anna).exists()


def test_deactivating_invalidates_reset_links(client, root, anna):
    path = create_link(root, anna)
    client.force_login(root)

    change_active(client, anna, False)

    assert_link_invalid(path)


def test_deleting_invalidates_reset_links(client, root, anna):
    path = create_link(root, anna)
    client.force_login(root)

    confirm_delete(client, anna)

    assert_link_invalid(path)
