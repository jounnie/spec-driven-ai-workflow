"""System check: stored ratings must lie inside the configured scale (#23).

The scale is one global setting (#3). When a host narrows it while ratings
exist, nothing is rescaled, deleted or hidden; this check reports an Error.
The check is read-only and touches the database only when it runs.
"""

from django.conf import settings
from django.core import checks
from django.db import DEFAULT_DB_ALIAS, DatabaseError, connections
from django.db.models import Count, Max, Min, Q
from django.db.models.functions import Greatest, Least

RATING_FIELDS = ('workload', 'clarity', 'collaboration', 'progress')


def check_rating_scale(app_configs, **kwargs):
    from pulse.models import Submission

    scale_min = settings.PULSE_SCALE_MIN
    scale_max = settings.PULSE_SCALE_MAX
    outside = Q()
    for field in RATING_FIELDS:
        outside |= Q(**{f'{field}__lt': scale_min}) | Q(**{f'{field}__gt': scale_max})

    try:
        # A single aggregate query; the tables may not exist before the first migrate.
        found = Submission.objects.using(DEFAULT_DB_ALIAS).aggregate(
            lowest=Min(Least(*RATING_FIELDS)),
            highest=Max(Greatest(*RATING_FIELDS)),
            affected=Count('pk', filter=outside),
        )
    except DatabaseError:
        return []
    finally:
        connections[DEFAULT_DB_ALIAS].close_if_unusable_or_obsolete()

    if not found['affected']:
        return []
    return [
        checks.Error(
            f'Ratings out of range. Configured scale: {scale_min}–{scale_max} '
            f'(PULSE_SCALE_MIN={scale_min}, PULSE_SCALE_MAX={scale_max}). '
            f'Found ratings: min={found["lowest"]}, max={found["highest"]}. '
            f'Affected submissions: {found["affected"]}. '
            'Fix: restore the previous PULSE_SCALE_MIN and PULSE_SCALE_MAX, '
            'or manually delete the affected projects.',
            id='pulse.E001',
        )
    ]
