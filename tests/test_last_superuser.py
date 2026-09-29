import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.urls import reverse

from pulse.admin import ADMIN_RIGHTS_MESSAGE

from .test_password_reset import PASSWORD

User = get_user_model()


@pytest.fixture
def root(db):
    return User.objects.create_user('root', password=PASSWORD, is_staff=True, is_superuser=True)


def edit(client, user, **flags):
    flags = {'is_active': True, 'is_staff': user.is_staff, 'is_superuser': user.is_superuser, **flags}
    data = {
        'username': user.username,
        'date_joined_0': user.date_joined.strftime('%Y-%m-%d'),
        'date_joined_1': user.date_joined.strftime('%H:%M:%S'),
    }
    data.update({name: 'on' for name, value in flags.items() if value})
    return client.post(reverse('admin:auth_user_change', args=[user.pk]), data)


def refused(response, user, **expected):
    assert response.status_code == 200
    assert ADMIN_RIGHTS_MESSAGE in response.content.decode()
    user.refresh_from_db()
    for name, value in expected.items():
        assert getattr(user, name) is value


@pytest.mark.parametrize('flag', ['is_superuser', 'is_staff'])
def test_last_superuser_cannot_lose_flag_on_own_account(client, root, flag):
    client.force_login(root)

    refused(edit(client, root, **{flag: False}), root, is_staff=True, is_superuser=True)


@pytest.mark.parametrize('flag', ['is_superuser', 'is_staff'])
def test_last_superuser_cannot_lose_flag_when_edited_by_another_admin(client, root, flag):
    # the editor is a staff user who is not a superuser but has change permission
    editor = User.objects.create_user('editor', password=PASSWORD, is_staff=True)
    editor.user_permissions.add(Permission.objects.get(codename='change_user'))
    client.force_login(editor)

    refused(edit(client, root, **{flag: False}), root, is_staff=True, is_superuser=True)


def test_last_superuser_cannot_lose_both_flags(client, root):
    client.force_login(root)

    refused(edit(client, root, is_staff=False, is_superuser=False), root, is_staff=True, is_superuser=True)


@pytest.mark.parametrize('flag', ['is_superuser', 'is_staff'])
def test_flag_can_be_removed_when_another_active_superuser_exists(client, root, flag):
    other = User.objects.create_user('other', password=PASSWORD, is_staff=True, is_superuser=True)
    client.force_login(root)

    response = edit(client, other, **{flag: False})

    assert response.status_code == 302
    other.refresh_from_db()
    assert getattr(other, flag) is False


def test_inactive_superuser_does_not_count_as_another_active_superuser(client, root):
    # an inactive superuser does not count as another active superuser
    User.objects.create_user('gone', password=PASSWORD, is_staff=True, is_superuser=True, is_active=False)
    client.force_login(root)

    refused(edit(client, root, is_superuser=False), root, is_superuser=True)


def test_editing_other_fields_of_last_superuser_is_allowed(client, root):
    client.force_login(root)

    response = edit(client, root)

    assert response.status_code == 302
