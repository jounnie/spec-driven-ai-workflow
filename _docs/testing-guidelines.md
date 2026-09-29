# Testing guidelines

How tests are written in this repo. Run them with `uv run pytest`.

## Tools

pytest with pytest-django. Tests are plain functions using pytest-django
fixtures such as `client`, as in `tests/test_health.py`. No
`unittest.TestCase` classes, no factory or time-freezing libraries.

```python
def test_health_returns_ok(client):
    response = client.get(reverse('health'))

    assert response.status_code == 200
```

## Where tests live and how they are named

- One file per feature: `tests/test_<feature>.py` (e.g. `tests/test_database.py`)
- Fixtures shared by several files go in `tests/conftest.py`
- Name tests `test_<subject>_<expected result>`

```python
# tests/test_invitations.py
def test_invitation_link_expires_after_three_days(): ...
```

## Database access

A test that touches the database needs `@pytest.mark.django_db`
(or the `db` fixture). Each test runs inside a transaction that is rolled back.

Use `@pytest.mark.django_db(transaction=True)` when that wrapping
transaction gets in the way:

- Concurrency tests (#6, #8): other threads use their own connections and
  cannot see data that is not committed
- SQLite pragma tests (#2): some pragmas (e.g. `foreign_keys`) are ignored inside a
  transaction, and a connection cannot be closed and reopened in the middle of one

```python
@pytest.mark.django_db(transaction=True)
def test_first_of_two_concurrent_registrations_becomes_admin(): ...
```

## Temporary database files

The test database is in-memory SQLite. Anything that needs a real file,
such as WAL mode in #2 (in-memory databases always report `memory`) or
checking file contents in #15, opens its own connection to a file in
pytest's `tmp_path`, with the same settings as `default`:

```python
from django.db.utils import ConnectionHandler


@pytest.mark.django_db
def test_file_database_uses_wal(tmp_path, settings):
    databases = ConnectionHandler({
        'default': {**settings.DATABASES['default'], 'NAME': tmp_path / 'test.sqlite3'},
    })
    connection = databases['default']
    try:
        with connection.cursor() as cursor:
            cursor.execute('PRAGMA journal_mode')
            assert cursor.fetchone()[0] == 'wal'
    finally:
        connection.close()
```

## Settings and environment variables

Change a setting for one test with the pytest-django `settings`
fixture; it is restored afterwards.

```python
def test_rating_scale_can_be_changed(settings):
    settings.PULSE_RATING_MAX = 10
    ...
```

Settings that are read from environment variables are computed once, when
`config/settings.py` is imported, so `settings` cannot test them. Instead
either put the parsing in a function in `config/settings.py` and call it
with `monkeypatch.setenv`:

```python
def test_db_path_is_read_from_environment(monkeypatch):
    monkeypatch.setenv('PULSE_DB_PATH', '/data/pulse.sqlite3')

    assert database_path() == Path('/data/pulse.sqlite3')
```

or, to check real startup behaviour, run Django in a subprocess:

```python
def test_relative_db_path_fails_at_startup():
    result = subprocess.run(
        [sys.executable, 'manage.py', 'check'],
        env={**os.environ, 'PULSE_DB_PATH': 'pulse.sqlite3'},
        capture_output=True, text=True,
    )

    assert result.returncode != 0
    assert 'PULSE_DB_PATH' in result.stderr
```

## Time

Code that depends on the current time (week keys, link expiry) is tested
without sleeping. Pass explicit timezone-aware datetimes to the function,
or patch `django.utils.timezone.now`:

```python
def test_invitation_link_expires_after_three_days(monkeypatch):
    created = datetime(2026, 1, 5, 9, 0, tzinfo=UTC)
    monkeypatch.setattr(timezone, 'now', lambda: created + timedelta(days=3, seconds=1))

    assert invitation.is_expired()
```

Patching works when the code calls `timezone.now()` after
`from django.utils import timezone`. It does not work if the code does
`from django.utils.timezone import now`.

## Test data

Create test data with the ORM, in small fixtures or helper functions.
Put them in `tests/conftest.py` once more than one file needs them.

```python
@pytest.fixture
def lead(django_user_model):
    return django_user_model.objects.create_user(username='lead', password='secret-pw')
```

## Password hashing

`tests/conftest.py` switches every test to the fast `MD5PasswordHasher`.
The one test that checks Argon2 (#7) puts the real hashers back:

```python
def test_passwords_are_hashed_with_argon2(settings, django_user_model):
    settings.PASSWORD_HASHERS = ['django.contrib.auth.hashers.Argon2PasswordHasher']
    ...
```

## Query counts

To make sure a page or query does not do N+1 queries (#10, #13), use
`django_assert_num_queries`:

```python
def test_dashboard_uses_two_queries(client, lead, django_assert_num_queries):
    client.force_login(lead)

    with django_assert_num_queries(2):
        client.get(reverse('dashboard'))
```
