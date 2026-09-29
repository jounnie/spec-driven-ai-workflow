import pytest


@pytest.fixture(autouse=True)
def fast_password_hasher(settings):
    settings.PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']


@pytest.fixture(autouse=True)
def plain_static_files(settings, tmp_path):
    """Serve static files from the app directories with plain storage.

    Production uses the manifest storage, which needs `collectstatic`. Tests
    must pass on a fresh clone, so they use plain storage and let WhiteNoise
    find files in the app directories. Must run before the `client` fixture
    builds its middleware.
    """
    settings.STORAGES = {
        **settings.STORAGES,
        'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
    }
    settings.WHITENOISE_USE_FINDERS = True
    settings.STATIC_ROOT = tmp_path
