from django.db.models import Avg, Count

from pulse.models import Submission

DIMENSIONS = ('workload', 'clarity', 'collaboration', 'progress')


def weekly_aggregates(project):
    """Response count and average of each dimension per week, oldest week first.

    One SQL query. Only weeks with at least one submission are returned. The
    ratings are averaged in the database, so individual values never leave it.
    """
    rows = (
        Submission.objects.filter(project=project)
        .values('week_key')
        .annotate(
            count=Count('id'),
            **{f'avg_{name}': Avg(name) for name in DIMENSIONS},
        )
        .order_by('week_key')
    )
    return [
        {
            'week_key': row['week_key'],
            'count': int(row['count']),
            **{name: round(float(row[f'avg_{name}']), 2) for name in DIMENSIONS},
        }
        for row in rows
    ]
