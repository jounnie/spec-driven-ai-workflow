import os
import subprocess
import sys
from datetime import UTC, datetime

import pytest
from django.core.exceptions import ImproperlyConfigured
from django.utils import timezone

from config.settings import BASE_DIR, anonymity_threshold, scale_bounds, time_zone
from pulse.conf import anonymity_limited, current_week_key, rating_scale, week_key

PULSE_VARIABLES = ('PULSE_SCALE_MIN', 'PULSE_SCALE_MAX', 'PULSE_ANONYMITY_THRESHOLD', 'PULSE_TIME_ZONE')


@pytest.fixture(autouse=True)
def clean_pulse_environment(monkeypatch):
    for name in PULSE_VARIABLES:
        monkeypatch.delenv(name, raising=False)


def run_check(env_overrides):
    env = {key: value for key, value in os.environ.items() if key not in PULSE_VARIABLES}
    return subprocess.run(
        [sys.executable, 'manage.py', 'check'],
        cwd=BASE_DIR,
        env={**env, **env_overrides},
        capture_output=True,
        text=True,
    )


def print_setting(name, env_overrides):
    env = {key: value for key, value in os.environ.items() if key not in PULSE_VARIABLES}
    return subprocess.run(
        [sys.executable, '-c', f'import django; django.setup(); from django.conf import settings; print(settings.{name})'],
        cwd=BASE_DIR,
        env={**env, 'DJANGO_SETTINGS_MODULE': 'config.settings', **env_overrides},
        capture_output=True,
        text=True,
    )


# Rating scale


def test_scale_defaults_to_one_to_five():
    assert scale_bounds() == (1, 5)


def test_scale_zero_to_ten_is_accepted(monkeypatch):
    monkeypatch.setenv('PULSE_SCALE_MIN', '0')
    monkeypatch.setenv('PULSE_SCALE_MAX', '10')

    assert scale_bounds() == (0, 10)


def test_scale_with_only_max_set_keeps_default_min(monkeypatch):
    monkeypatch.setenv('PULSE_SCALE_MAX', '7')

    assert scale_bounds() == (1, 7)


def test_scale_with_only_min_set_keeps_default_max(monkeypatch):
    monkeypatch.setenv('PULSE_SCALE_MIN', '0')

    assert scale_bounds() == (0, 5)


def test_scale_ignores_surrounding_whitespace(monkeypatch):
    monkeypatch.setenv('PULSE_SCALE_MAX', ' 7 ')

    assert scale_bounds() == (1, 7)


@pytest.mark.parametrize('name', ['PULSE_SCALE_MIN', 'PULSE_SCALE_MAX'])
@pytest.mark.parametrize('value', ['abc', '2.5', '', '  '])
def test_scale_non_integer_is_rejected(monkeypatch, name, value):
    monkeypatch.setenv(name, value)

    with pytest.raises(ImproperlyConfigured, match=name):
        scale_bounds()


@pytest.mark.parametrize(('minimum', 'maximum'), [('5', '5'), ('6', '5'), ('3', '2')])
def test_scale_min_not_below_max_is_rejected(monkeypatch, minimum, maximum):
    monkeypatch.setenv('PULSE_SCALE_MIN', minimum)
    monkeypatch.setenv('PULSE_SCALE_MAX', maximum)

    with pytest.raises(ImproperlyConfigured, match='PULSE_SCALE_MIN'):
        scale_bounds()


def test_scale_negative_min_is_rejected(monkeypatch):
    monkeypatch.setenv('PULSE_SCALE_MIN', '-1')

    with pytest.raises(ImproperlyConfigured, match='PULSE_SCALE_MIN'):
        scale_bounds()


@pytest.mark.parametrize(('minimum', 'maximum'), [('1', '20'), ('0', '11')])
def test_scale_with_more_than_eleven_values_is_rejected(monkeypatch, minimum, maximum):
    monkeypatch.setenv('PULSE_SCALE_MIN', minimum)
    monkeypatch.setenv('PULSE_SCALE_MAX', maximum)

    with pytest.raises(ImproperlyConfigured, match='PULSE_SCALE_MAX'):
        scale_bounds()


@pytest.mark.parametrize(
    ('env', 'name'),
    [
        ({'PULSE_SCALE_MAX': 'abc'}, 'PULSE_SCALE_MAX'),
        ({'PULSE_SCALE_MIN': '2.5'}, 'PULSE_SCALE_MIN'),
        ({'PULSE_SCALE_MAX': ''}, 'PULSE_SCALE_MAX'),
        ({'PULSE_SCALE_MIN': '5', 'PULSE_SCALE_MAX': '5'}, 'PULSE_SCALE_MIN'),
        ({'PULSE_SCALE_MIN': '-1'}, 'PULSE_SCALE_MIN'),
        ({'PULSE_SCALE_MIN': '0', 'PULSE_SCALE_MAX': '11'}, 'PULSE_SCALE_MAX'),
    ],
)
def test_invalid_scale_fails_at_startup(env, name):
    result = run_check(env)

    assert result.returncode != 0
    assert 'ImproperlyConfigured' in result.stderr
    assert name in result.stderr


def test_scale_from_environment_becomes_django_settings():
    result = print_setting('PULSE_SCALE_MIN, settings.PULSE_SCALE_MAX', {'PULSE_SCALE_MIN': '0', 'PULSE_SCALE_MAX': '10'})

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == '0 10'


def test_rating_scale_defaults_to_one_to_five():
    assert rating_scale() == range(1, 6)
    assert list(rating_scale()) == [1, 2, 3, 4, 5]


def test_rating_scale_reads_settings_when_called(settings):
    settings.PULSE_SCALE_MAX = 10

    assert list(rating_scale())[-1] == 10


# Anonymity threshold


def test_anonymity_threshold_defaults_to_five():
    assert anonymity_threshold() == 5


@pytest.mark.parametrize('count', [0, 1, 2, 3, 4])
def test_anonymity_is_limited_below_default_threshold(count):
    assert anonymity_limited(count) is True


@pytest.mark.parametrize('count', [5, 6, 100])
def test_anonymity_is_not_limited_from_default_threshold(count):
    assert anonymity_limited(count) is False


def test_anonymity_threshold_is_read_from_environment(monkeypatch):
    monkeypatch.setenv('PULSE_ANONYMITY_THRESHOLD', '3')

    assert anonymity_threshold() == 3


def test_anonymity_threshold_of_three_moves_boundary(settings):
    settings.PULSE_ANONYMITY_THRESHOLD = 3

    assert anonymity_limited(2) is True
    assert anonymity_limited(3) is False


def test_anonymity_threshold_of_one_is_accepted(monkeypatch, settings):
    monkeypatch.setenv('PULSE_ANONYMITY_THRESHOLD', '1')
    settings.PULSE_ANONYMITY_THRESHOLD = anonymity_threshold()

    assert anonymity_limited(0) is True
    assert anonymity_limited(1) is False


@pytest.mark.parametrize('value', ['0', '-1', 'abc', '2.5', ''])
def test_invalid_anonymity_threshold_is_rejected(monkeypatch, value):
    monkeypatch.setenv('PULSE_ANONYMITY_THRESHOLD', value)

    with pytest.raises(ImproperlyConfigured, match='PULSE_ANONYMITY_THRESHOLD'):
        anonymity_threshold()


@pytest.mark.parametrize('value', ['0', '-1', 'abc', ''])
def test_invalid_anonymity_threshold_fails_at_startup(value):
    result = run_check({'PULSE_ANONYMITY_THRESHOLD': value})

    assert result.returncode != 0
    assert 'ImproperlyConfigured' in result.stderr
    assert 'PULSE_ANONYMITY_THRESHOLD' in result.stderr


def test_anonymity_threshold_from_environment_becomes_django_setting():
    result = print_setting('PULSE_ANONYMITY_THRESHOLD', {'PULSE_ANONYMITY_THRESHOLD': '3'})

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == '3'


# Time zone


def test_time_zone_defaults_to_utc():
    assert time_zone() == 'UTC'


def test_time_zone_is_read_from_environment(monkeypatch):
    monkeypatch.setenv('PULSE_TIME_ZONE', 'Europe/Zurich')

    assert time_zone() == 'Europe/Zurich'


def test_time_zone_from_environment_sets_django_time_zone():
    result = print_setting('TIME_ZONE', {'PULSE_TIME_ZONE': 'Europe/Zurich'})

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == 'Europe/Zurich'


@pytest.mark.parametrize('value', ['Mars/Olympus', '', '   '])
def test_invalid_time_zone_is_rejected(monkeypatch, value):
    monkeypatch.setenv('PULSE_TIME_ZONE', value)

    with pytest.raises(ImproperlyConfigured, match='PULSE_TIME_ZONE'):
        time_zone()


@pytest.mark.parametrize('value', ['Mars/Olympus', ''])
def test_invalid_time_zone_fails_at_startup(value):
    result = run_check({'PULSE_TIME_ZONE': value})

    assert result.returncode != 0
    assert 'ImproperlyConfigured' in result.stderr
    assert 'PULSE_TIME_ZONE' in result.stderr


# Week key


def test_week_key_uses_iso_year_and_week():
    assert week_key(datetime(2026, 9, 29, 12, 0, tzinfo=UTC)) == '2026-W40'


@pytest.mark.parametrize(
    ('dt', 'expected'),
    [
        (datetime(2024, 12, 30, 12, 0, tzinfo=UTC), '2025-W01'),
        (datetime(2027, 1, 1, 12, 0, tzinfo=UTC), '2026-W53'),
    ],
)
def test_week_key_uses_iso_year_not_calendar_year(dt, expected):
    assert week_key(dt) == expected


def test_week_key_changes_at_monday_midnight():
    sunday = datetime(2026, 10, 4, 23, 59, 59, tzinfo=UTC)
    monday = datetime(2026, 10, 5, 0, 0, 0, tzinfo=UTC)

    assert week_key(sunday) == '2026-W40'
    assert week_key(monday) == '2026-W41'


def test_week_key_converts_to_instance_time_zone(settings):
    settings.TIME_ZONE = 'Europe/Zurich'
    sunday_evening_utc = datetime(2026, 10, 4, 23, 30, tzinfo=UTC)

    assert week_key(sunday_evening_utc) == '2026-W41'


def test_week_key_rejects_naive_datetime():
    with pytest.raises(ValueError):
        week_key(datetime(2026, 9, 29, 12, 0))


def test_week_key_zero_pads_week_number():
    assert week_key(datetime(2026, 1, 28, 12, 0, tzinfo=UTC)) == '2026-W05'


def test_week_keys_sort_as_strings_in_time_order():
    dates = [datetime(2026, month, 15, tzinfo=UTC) for month in range(1, 13)]
    keys = [week_key(dt) for dt in dates]

    assert sorted(keys) == keys


def test_current_week_key_uses_now(monkeypatch):
    monkeypatch.setattr(timezone, 'now', lambda: datetime(2026, 9, 29, 9, 0, tzinfo=UTC))

    assert current_week_key() == '2026-W40'
