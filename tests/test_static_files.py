import pytest
from django.conf import settings as django_settings

from config import settings as project_settings


@pytest.mark.parametrize('path, content_types', [
    ('pulse/css/site.css', {'text/css'}),
    ('pulse/vendor/htmx.min.js', {'text/javascript', 'application/javascript'}),
    ('pulse/vendor/chart.umd.js', {'text/javascript', 'application/javascript'}),
])
def test_static_file_is_served_with_debug_off(client, settings, path, content_types):
    assert settings.DEBUG is False

    response = client.get(f'{settings.STATIC_URL}{path}')

    assert response.status_code == 200
    assert response['Content-Type'].split(';')[0] in content_types


def test_whitenoise_middleware_comes_directly_after_security_middleware():
    middleware = project_settings.MIDDLEWARE

    assert middleware.index('whitenoise.middleware.WhiteNoiseMiddleware') == (
        middleware.index('django.middleware.security.SecurityMiddleware') + 1
    )


def test_static_root_is_staticfiles_in_the_project_root():
    assert project_settings.STATIC_ROOT == project_settings.BASE_DIR / 'staticfiles'
    assert (project_settings.BASE_DIR / 'manage.py').exists()
    assert 'staticfiles/' in (project_settings.BASE_DIR / '.gitignore').read_text().splitlines()


def test_production_uses_compressed_manifest_storage():
    backend = project_settings.STORAGES['staticfiles']['BACKEND']

    assert backend == 'whitenoise.storage.CompressedManifestStaticFilesStorage'


def test_static_tag_works_without_collectstatic():
    from django.templatetags.static import static

    assert static('pulse/css/site.css') == '/static/pulse/css/site.css'
    assert django_settings.STORAGES['staticfiles']['BACKEND'] != project_settings.STORAGES['staticfiles']['BACKEND']
