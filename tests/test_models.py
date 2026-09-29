import os
import string
import subprocess
import sys
from datetime import UTC, datetime

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection
from django.db.models import ProtectedError
from django.forms import modelform_factory

from config.settings import BASE_DIR
from pulse import conf
from pulse.models import Project, Submission

WEEK = '2026-W40'
RATINGS = ('workload', 'clarity', 'collaboration', 'progress')


@pytest.fixture
def lead(django_user_model):
    return django_user_model.objects.create_user(username='lead', password='secret-pw')


@pytest.fixture
def project(lead):
    return Project.objects.create(owner=lead, name='Apollo')


def make_submission(project, **overrides):
    values = {'week_key': WEEK, 'workload': 3, 'clarity': 3, 'collaboration': 3, 'progress': 3}
    values.update(overrides)
    return Submission(project=project, **values)


def errors_of(instance):
    with pytest.raises(ValidationError) as excinfo:
        instance.full_clean()
    return excinfo.value.message_dict


# Project


def test_project_has_expected_fields():
    names = {field.name for field in Project._meta.get_fields() if field.concrete}

    assert names == {'id', 'owner', 'name', 'share_token', 'created_at'}


@pytest.mark.django_db
def test_project_with_valid_name_passes_full_clean(lead):
    Project(owner=lead, name='x' * 100).full_clean()


@pytest.mark.django_db
@pytest.mark.parametrize('name', ['', '   ', '\t\n', 'x' * 101])
def test_project_name_empty_blank_or_too_long_fails_full_clean(lead, name):
    errors = errors_of(Project(owner=lead, name=name))

    assert 'name' in errors


@pytest.mark.django_db
def test_project_names_may_repeat_for_same_owner(lead):
    first = Project.objects.create(owner=lead, name='Apollo')
    second = Project(owner=lead, name='Apollo')
    second.full_clean()
    second.save()

    assert first.pk != second.pk


@pytest.mark.django_db
def test_project_share_token_is_generated_on_create(lead):
    project = Project.objects.create(owner=lead, name='Apollo')

    assert project.share_token
    assert Project.objects.get(pk=project.pk).share_token == project.share_token


@pytest.mark.django_db
def test_project_share_token_is_url_safe_with_at_least_128_bits(project):
    allowed = set(string.ascii_letters + string.digits + '-_')

    assert set(project.share_token) <= allowed
    # Each URL-safe base64 character carries 6 bits.
    assert len(project.share_token) * 6 >= 128


@pytest.mark.django_db
def test_project_share_token_is_unique_in_database(lead, project):
    duplicate = Project(owner=lead, name='Other')
    duplicate.share_token = project.share_token

    with pytest.raises(IntegrityError):
        duplicate.save()


@pytest.mark.django_db
def test_project_share_tokens_of_1000_projects_are_distinct(lead):
    Project.objects.bulk_create(Project(owner=lead, name=f'P{i}') for i in range(1000))

    tokens = set(Project.objects.values_list('share_token', flat=True))

    assert len(tokens) == 1000


def test_project_share_token_is_not_editable_in_forms():
    form_class = modelform_factory(Project, fields='__all__')

    assert Project._meta.get_field('share_token').editable is False
    assert 'share_token' not in form_class.base_fields


@pytest.mark.django_db
def test_project_share_token_and_created_at_do_not_change_on_save(project):
    token, created = project.share_token, project.created_at

    project.name = 'Renamed'
    project.save()
    project.refresh_from_db()

    assert project.share_token == token
    assert project.created_at == created


@pytest.mark.django_db
def test_project_created_at_is_set_on_create(lead):
    before = datetime.now(UTC)
    project = Project.objects.create(owner=lead, name='Apollo')

    assert project.created_at is not None
    assert before <= project.created_at <= datetime.now(UTC)


@pytest.mark.django_db
def test_deleting_owner_of_project_raises_protected_error(lead, project):
    make_submission(project).save()

    with pytest.raises(ProtectedError):
        lead.delete()

    assert Project.objects.filter(pk=project.pk).exists()
    assert Submission.objects.filter(project=project).count() == 1


@pytest.mark.django_db
def test_project_str_is_name(project):
    assert str(project) == 'Apollo'


# Submission fields


def test_submission_has_exactly_the_anonymous_fields():
    names = {field.name for field in Submission._meta.get_fields()}

    assert names == {'id', 'project', 'week_key', *RATINGS}


def test_submission_rating_fields_use_design_system_wording():
    verbose_names = {name: Submission._meta.get_field(name).verbose_name for name in RATINGS}

    assert verbose_names == {
        'workload': 'My workload is manageable',
        'clarity': 'Our goals and priorities are clear',
        'collaboration': 'We work well together',
        'progress': 'I am confident we will deliver',
    }


@pytest.mark.django_db
def test_submission_str_does_not_depend_on_ratings(project):
    low = make_submission(project, workload=1, clarity=2, collaboration=4, progress=5)
    high = make_submission(project, workload=5, clarity=4, collaboration=2, progress=1)

    assert str(low) == str(high) == f'Submission for {project.pk} in {WEEK}'
    for name in RATINGS:
        assert name not in str(low)


# Submission validation


@pytest.mark.django_db
def test_submission_with_valid_values_passes_full_clean(project):
    make_submission(project).full_clean()


@pytest.mark.django_db
@pytest.mark.parametrize('field', RATINGS)
def test_submission_missing_rating_fails_full_clean(project, field):
    errors = errors_of(make_submission(project, **{field: None}))

    assert set(errors) == {field}


@pytest.mark.django_db
@pytest.mark.parametrize('value', [1, 5])
@pytest.mark.parametrize('field', RATINGS)
def test_submission_rating_at_default_bounds_passes(project, field, value):
    make_submission(project, **{field: value}).full_clean()


@pytest.mark.django_db
@pytest.mark.parametrize('value', [0, 6, -1])
@pytest.mark.parametrize('field', RATINGS)
def test_submission_rating_outside_default_scale_fails(project, field, value):
    errors = errors_of(make_submission(project, **{field: value}))

    assert set(errors) == {field}


@pytest.mark.django_db
def test_submission_rating_follows_overridden_maximum(project, settings):
    settings.PULSE_SCALE_MAX = 10

    make_submission(project, workload=10).full_clean()
    assert set(errors_of(make_submission(project, workload=11))) == {'workload'}


@pytest.mark.django_db
def test_submission_rating_follows_overridden_minimum(project, settings):
    settings.PULSE_SCALE_MIN = 0
    settings.PULSE_SCALE_MAX = 10

    make_submission(project, clarity=0).full_clean()
    assert set(errors_of(make_submission(project, clarity=-1))) == {'clarity'}


@pytest.mark.django_db
@pytest.mark.parametrize('value', ['abc', 2.5, '2.5', True])
def test_submission_non_integer_rating_fails(project, value):
    errors = errors_of(make_submission(project, collaboration=value))

    assert set(errors) == {'collaboration'}


@pytest.mark.django_db
def test_submission_with_helper_week_key_is_saved(project):
    key = conf.week_key(datetime(2026, 9, 29, 12, 0, tzinfo=UTC))
    submission = make_submission(project, week_key=key)

    submission.full_clean()
    submission.save()

    assert Submission.objects.get(pk=submission.pk).week_key == key


@pytest.mark.django_db
@pytest.mark.parametrize('week_key', ['', '2026-40', '2026-W5', 'W40-2026', '2026-W00', '2026-W54', '2026-w40'])
def test_submission_malformed_week_key_fails(project, week_key):
    errors = errors_of(make_submission(project, week_key=week_key))

    assert set(errors) == {'week_key'}


@pytest.mark.django_db
def test_submission_has_index_on_project_and_week_key():
    with connection.cursor() as cursor:
        constraints = connection.introspection.get_constraints(cursor, Submission._meta.db_table)

    indexed = [c['columns'] for c in constraints.values() if c['index']]

    assert ['project_id', 'week_key'] in indexed


# Cascade


@pytest.mark.django_db
def test_deleting_project_deletes_its_submissions(project):
    make_submission(project).save()
    make_submission(project, week_key='2026-W41').save()

    project.delete()

    assert Submission.objects.filter(project_id=project.pk).count() == 0
    assert Submission.objects.count() == 0


@pytest.mark.django_db
def test_deleting_project_keeps_other_projects_submissions(lead, project):
    other = Project.objects.create(owner=lead, name='Other')
    make_submission(project).save()
    kept = make_submission(other)
    kept.save()

    project.delete()

    assert list(Submission.objects.all()) == [kept]


@pytest.mark.django_db(transaction=True)
def test_submission_for_missing_project_cannot_be_saved():
    submission = Submission(project_id=999_999, week_key=WEEK, workload=3, clarity=3, collaboration=3, progress=3)

    with pytest.raises(IntegrityError):
        submission.save()


# Migrations


@pytest.mark.parametrize('env', [{}, {'PULSE_SCALE_MIN': '0', 'PULSE_SCALE_MAX': '10'}])
def test_migrations_are_up_to_date(env):
    result = subprocess.run(
        [sys.executable, 'manage.py', 'makemigrations', '--check', '--dry-run'],
        cwd=BASE_DIR,
        env={**os.environ, **env},
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
