from django.apps import AppConfig
from django.core import checks


class PulseConfig(AppConfig):
    name = 'pulse'

    def ready(self):
        from pulse.checks import check_rating_scale

        # No database tag: a tagged check is skipped by a plain `manage.py check`.
        checks.register(check_rating_scale)
