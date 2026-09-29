import os
import subprocess
import sys

import pytest

from pulse import checks

CREATE_DATA = '''
from django.contrib.auth import get_user_model
from pulse.models import Project, Submission
user = get_user_model().objects.create_user(username="lead", password="x")
project = Project.objects.create(owner=user, name="P")
for week, value in enumerate({values}, start=1):
    Submission.objects.create(project=project, week_key=f"2026-W{{week:02d}}",
        workload=value, clarity=value, collaboration=value, progress=value)
'''


@pytest.fixture
def db_env(tmp_path):
    return {**os.environ, 'PULSE_DB_PATH': str(tmp_path / 'scale.sqlite3')}


def manage(env, *args, scale=None):
    env = dict(env)
    if scale:
        env['PULSE_SCALE_MIN'], env['PULSE_SCALE_MAX'] = map(str, scale)
    return subprocess.run(
        [sys.executable, 'manage.py', *args], env=env, capture_output=True, text=True,
    )


def migrated_db_with(env, values, scale):
    assert manage(env, 'migrate', scale=scale).returncode == 0
    if values:
        result = manage(env, 'shell', '-c', CREATE_DATA.format(values=values), scale=scale)
        assert result.returncode == 0, result.stderr


def test_scale_widened_passes(db_env):
    migrated_db_with(db_env, [1, 3, 5], (1, 5))

    result = manage(db_env, 'check', scale=(1, 10))

    assert result.returncode == 0


def test_scale_narrowed_below_stored_data_fails_with_clear_error(db_env):
    migrated_db_with(db_env, [1, 6, 10], (1, 10))

    result = manage(db_env, 'check', scale=(1, 5))

    assert result.returncode != 0
    assert 'Configured scale: 1–5 (PULSE_SCALE_MIN=1, PULSE_SCALE_MAX=5)' in result.stderr
    assert 'min=1, max=10' in result.stderr
    assert 'Affected submissions: 2' in result.stderr
    assert 'restore the previous PULSE_SCALE_MIN and PULSE_SCALE_MAX' in result.stderr
    assert 'manually delete the affected projects' in result.stderr


def test_scale_narrowed_also_stops_migrate(db_env):
    migrated_db_with(db_env, [6], (1, 10))

    result = manage(db_env, 'migrate', scale=(1, 5))

    assert result.returncode != 0
    assert 'Affected submissions: 1' in result.stderr


def test_boundary_ratings_pass(db_env):
    migrated_db_with(db_env, [1, 5], (1, 5))

    result = manage(db_env, 'check', scale=(1, 5))

    assert result.returncode == 0


def test_rating_below_the_minimum_fails(db_env):
    migrated_db_with(db_env, [1, 2], (1, 5))

    result = manage(db_env, 'check', scale=(2, 5))

    assert result.returncode != 0
    assert 'min=1, max=2' in result.stderr
    assert 'Affected submissions: 1' in result.stderr


def test_empty_database_passes(db_env):
    migrated_db_with(db_env, [], (1, 5))

    assert manage(db_env, 'check', scale=(1, 5)).returncode == 0


def test_unmigrated_database_passes(db_env):
    result = manage(db_env, 'check', scale=(1, 5))

    assert result.returncode == 0
    assert 'no such table' not in result.stderr


def test_check_does_not_modify_data(db_env):
    migrated_db_with(db_env, [1, 6], (1, 10))
    count = 'from pulse.models import Submission; print(Submission.objects.count())'

    manage(db_env, 'check', scale=(1, 5))

    assert manage(db_env, 'shell', '-c', count, scale=(1, 10)).stdout.split()[-1] == '2'


@pytest.mark.django_db
def test_check_has_django_signature_and_passes_without_data():
    assert checks.check_rating_scale(None) == []
