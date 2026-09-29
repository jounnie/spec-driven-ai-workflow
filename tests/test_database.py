import os
import subprocess
import sys

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.db import IntegrityError, connection
from django.db.utils import ConnectionHandler

from config.settings import BASE_DIR, database_path


def run_django(*args, env_overrides):
    return subprocess.run(
        [sys.executable, *args],
        cwd=BASE_DIR,
        env={**os.environ, **env_overrides},
        capture_output=True,
        text=True,
    )


@pytest.fixture
def file_database(tmp_path, settings):
    databases = ConnectionHandler({
        'default': {**settings.DATABASES['default'], 'NAME': tmp_path / 'test.sqlite3'},
    })
    file_connection = databases['default']
    yield file_connection
    file_connection.close()


def fetch_pragmas(conn):
    with conn.cursor() as cursor:
        values = {}
        for pragma in ('journal_mode', 'foreign_keys', 'secure_delete'):
            cursor.execute(f'PRAGMA {pragma}')
            values[pragma] = cursor.fetchone()[0]
        return values


# Database path


def test_db_path_defaults_to_project_root(monkeypatch):
    monkeypatch.delenv('PULSE_DB_PATH', raising=False)

    assert database_path() == BASE_DIR / 'db.sqlite3'


def test_db_path_is_read_from_environment(tmp_path):
    db_file = tmp_path / 'pulse.sqlite3'

    result = run_django(
        '-c',
        'import django; django.setup(); from django.conf import settings; '
        "print(settings.DATABASES['default']['NAME'])",
        env_overrides={'PULSE_DB_PATH': str(db_file), 'DJANGO_SETTINGS_MODULE': 'config.settings'},
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == str(db_file)


@pytest.mark.parametrize('value', ['pulse.sqlite3', './data/pulse.sqlite3', '~/pulse.sqlite3'])
def test_relative_db_path_is_rejected(monkeypatch, value):
    monkeypatch.setenv('PULSE_DB_PATH', value)

    with pytest.raises(ImproperlyConfigured, match='PULSE_DB_PATH'):
        database_path()


@pytest.mark.parametrize('value', ['', '   '])
def test_empty_db_path_is_rejected(monkeypatch, value):
    monkeypatch.setenv('PULSE_DB_PATH', value)

    with pytest.raises(ImproperlyConfigured, match='PULSE_DB_PATH'):
        database_path()


@pytest.mark.parametrize('value', ['pulse.sqlite3', ''])
def test_relative_or_empty_db_path_fails_at_startup(value):
    result = run_django('manage.py', 'check', env_overrides={'PULSE_DB_PATH': value})

    assert result.returncode != 0
    assert 'ImproperlyConfigured' in result.stderr
    assert 'PULSE_DB_PATH' in result.stderr


def test_migrate_fails_when_db_directory_is_missing(tmp_path):
    db_file = tmp_path / 'missing' / 'pulse.sqlite3'

    result = run_django('manage.py', 'migrate', env_overrides={'PULSE_DB_PATH': str(db_file)})

    assert result.returncode != 0
    assert str(db_file) in result.stderr
    assert list(tmp_path.iterdir()) == []


def test_migrate_fails_when_db_path_is_a_directory(tmp_path):
    result = run_django('manage.py', 'migrate', env_overrides={'PULSE_DB_PATH': str(tmp_path)})

    assert result.returncode != 0
    assert str(tmp_path) in result.stderr


# Pragmas


@pytest.mark.django_db(transaction=True)
def test_file_database_uses_wal(file_database):
    assert fetch_pragmas(file_database)['journal_mode'] == 'wal'


@pytest.mark.django_db(transaction=True)
def test_connection_enables_foreign_keys():
    assert fetch_pragmas(connection)['foreign_keys'] == 1


@pytest.mark.django_db(transaction=True)
def test_connection_enables_secure_delete():
    assert fetch_pragmas(connection)['secure_delete'] == 1


@pytest.mark.django_db(transaction=True)
def test_pragmas_are_set_again_on_new_connection(file_database):
    fetch_pragmas(file_database)
    file_database.close()

    assert file_database.connection is None
    assert fetch_pragmas(file_database) == {'journal_mode': 'wal', 'foreign_keys': 1, 'secure_delete': 1}


@pytest.mark.django_db(transaction=True)
def test_insert_with_missing_parent_raises_integrity_error(file_database):
    with file_database.cursor() as cursor:
        cursor.execute('CREATE TABLE parent (id INTEGER PRIMARY KEY)')
        cursor.execute('CREATE TABLE child (id INTEGER PRIMARY KEY, parent_id INTEGER REFERENCES parent(id))')

        with pytest.raises(IntegrityError):
            cursor.execute('INSERT INTO child (id, parent_id) VALUES (1, 42)')
