"""Pulse settings helpers.

Values are read from django.conf.settings on every call, so tests can
override them with the ``settings`` fixture.
"""

from django.conf import settings
from django.utils import timezone


def rating_scale():
    """Return the allowed ratings as an inclusive range."""
    return range(settings.PULSE_SCALE_MIN, settings.PULSE_SCALE_MAX + 1)


def anonymity_limited(count):
    """Return True when ``count`` responses are too few to keep a week anonymous."""
    return count < settings.PULSE_ANONYMITY_THRESHOLD


def week_key(dt):
    """Return the ISO week of ``dt`` in the instance time zone as ``YYYY-Www``."""
    if timezone.is_naive(dt):
        raise ValueError('week_key() needs a timezone-aware datetime.')
    year, week, _ = timezone.localtime(dt, timezone.get_default_timezone()).isocalendar()
    return f'{year}-W{week:02d}'


def current_week_key():
    """Return the week key for the current time."""
    return week_key(timezone.now())
