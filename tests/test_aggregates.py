import pytest

from pulse.aggregates import weekly_aggregates
from pulse.models import Project, Submission

KEYS = {'week_key', 'count', 'workload', 'clarity', 'collaboration', 'progress'}


@pytest.fixture
def project(django_user_model):
    owner = django_user_model.objects.create_user(username='lead', password='secret-pw')
    return Project.objects.create(owner=owner, name='Alpha')


@pytest.fixture
def other_project(project):
    return Project.objects.create(owner=project.owner, name='Beta')


def add(project, week, workload=3, clarity=3, collaboration=3, progress=3):
    return Submission.objects.create(
        project=project, week_key=week, workload=workload, clarity=clarity,
        collaboration=collaboration, progress=progress,
    )


@pytest.mark.django_db
def test_entry_has_exactly_the_six_keys_with_types(project):
    add(project, '2026-W40')

    (entry,) = weekly_aggregates(project)

    assert set(entry) == KEYS
    assert type(entry['week_key']) is str
    assert type(entry['count']) is int
    for name in ('workload', 'clarity', 'collaboration', 'progress'):
        assert type(entry[name]) is float


@pytest.mark.django_db
def test_average_is_rounded_to_two_places(project):
    for value in (1, 2, 4):
        add(project, '2026-W40', workload=value)

    (entry,) = weekly_aggregates(project)

    assert entry['count'] == 3
    assert entry['workload'] == 2.33


@pytest.mark.django_db
def test_average_of_one_and_two_is_one_and_a_half(project):
    add(project, '2026-W40', workload=1)
    add(project, '2026-W40', workload=2)

    assert weekly_aggregates(project)[0]['workload'] == 1.5


@pytest.mark.django_db
def test_each_dimension_is_averaged_on_its_own(project):
    add(project, '2026-W40', workload=1, clarity=2, collaboration=3, progress=4)
    add(project, '2026-W40', workload=1, clarity=4, collaboration=5, progress=5)

    (entry,) = weekly_aggregates(project)

    assert entry['workload'] == 1.0
    assert entry['clarity'] == 3.0
    assert entry['collaboration'] == 4.0
    assert entry['progress'] == 4.5


@pytest.mark.django_db
def test_zero_is_a_rating_on_a_zero_based_scale(project, settings):
    settings.PULSE_SCALE_MIN = 0
    settings.PULSE_SCALE_MAX = 10
    add(project, '2026-W38', workload=0)
    add(project, '2026-W38', workload=0)
    add(project, '2026-W39', workload=0)
    add(project, '2026-W39', workload=10)

    first, second = weekly_aggregates(project)

    assert first['workload'] == 0.0
    assert second['workload'] == 5.0


@pytest.mark.django_db
def test_weeks_are_ordered_across_year_boundaries(project):
    for week in ('2027-W01', '2026-W01', '2026-W53', '2025-W52', '2026-W40'):
        add(project, week)

    weeks = [entry['week_key'] for entry in weekly_aggregates(project)]

    assert weeks == ['2025-W52', '2026-W01', '2026-W40', '2026-W53', '2027-W01']


@pytest.mark.django_db
def test_weeks_without_submissions_are_omitted(project):
    add(project, '2026-W40')
    add(project, '2026-W38')

    weeks = [entry['week_key'] for entry in weekly_aggregates(project)]

    assert weeks == ['2026-W38', '2026-W40']


@pytest.mark.django_db
def test_project_without_submissions_gives_empty_list(project):
    assert weekly_aggregates(project) == []


@pytest.mark.django_db
def test_future_weeks_and_small_counts_are_returned(project):
    add(project, '2099-W10')

    (entry,) = weekly_aggregates(project)

    assert entry['week_key'] == '2099-W10'
    assert entry['count'] == 1


@pytest.mark.django_db
def test_other_projects_are_not_included(project, other_project):
    add(project, '2026-W40', workload=1)
    add(other_project, '2026-W40', workload=5)
    add(other_project, '2026-W41', workload=5)

    (entry,) = weekly_aggregates(project)

    assert entry['count'] == 1
    assert entry['workload'] == 1.0
    assert len(weekly_aggregates(other_project)) == 2


@pytest.mark.django_db
def test_calling_it_does_not_change_submissions(project):
    add(project, '2026-W40', workload=2)
    before = list(Submission.objects.values())

    weekly_aggregates(project)

    assert list(Submission.objects.values()) == before


@pytest.mark.django_db
def test_many_submissions_use_one_query(project, django_assert_num_queries):
    weeks = [f'2026-W{n:02d}' for n in range(1, 53)]
    Submission.objects.bulk_create([
        Submission(project=project, week_key=weeks[i % 52], workload=1 + i % 5,
                   clarity=3, collaboration=3, progress=3)
        for i in range(500)
    ])

    with django_assert_num_queries(1):
        result = weekly_aggregates(project)

    assert len(result) == 52
    assert sum(entry['count'] for entry in result) == 500


@pytest.mark.django_db
def test_small_and_empty_projects_use_one_query(project, other_project, django_assert_num_queries):
    add(project, '2026-W40')
    add(project, '2026-W40')

    with django_assert_num_queries(1):
        weekly_aggregates(project)
    with django_assert_num_queries(1):
        weekly_aggregates(other_project)
