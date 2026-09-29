import re
from datetime import datetime, timezone as dt_timezone

import pytest
from django.contrib.sessions.models import Session
from django.test import Client
from django.utils import timezone

from pulse.conf import current_week_key
from pulse.models import Project, Submission

UTC = dt_timezone.utc
FIELDS = ('workload', 'clarity', 'collaboration', 'progress')
WARNING = 'Limited anonymity:'
ANON_TEXT = (
    'Your answers are anonymous. Only your four ratings and the week are stored – '
    'no name, email address or IP address. A cookie in your browser prevents '
    'submitting twice in the same week.'
)


@pytest.fixture
def project(django_user_model):
    owner = django_user_model.objects.create_user('owner', password='secret-pw')
    return Project.objects.create(owner=owner, name='Apollo')


def url(project):
    return f'/p/{project.share_token}/'


def valid(**extra):
    return {**{name: '3' for name in FIELDS}, **extra}


def add_submissions(project, count, week=None):
    for _ in range(count):
        Submission.objects.create(
            project=project, week_key=week or current_week_key(),
            workload=3, clarity=3, collaboration=3, progress=3,
        )


# Access and URLs

def test_form_shows_project_name_as_h1(client, project):
    response = client.get(url(project))

    assert response.status_code == 200
    assert f'<h1>{project.name}</h1>' in response.content.decode()


@pytest.mark.parametrize('token', ['nope', 'a' * 65, '%00', '..', '__'])
def test_bad_tokens_give_the_404_page(client, project, token):
    for path in (f'/p/{token}/', f'/p/{token}/thanks/'):
        response = client.get(path)
        assert response.status_code == 404
        assert 'Page not found' in response.content.decode()
        assert 'Apollo' not in response.content.decode()
    assert client.post(f'/p/{token}/', valid()).status_code == 404


def test_token_of_wrong_case_is_404(client, project):
    assert client.get(f'/p/{project.share_token.swapcase()}/').status_code == 404


def test_methods(client, project):
    assert client.head(url(project)).status_code == 200
    assert client.put(url(project)).status_code == 405
    assert client.delete(url(project)).status_code == 405
    thanks = url(project) + 'thanks/'
    assert client.head(thanks).status_code == 200
    assert client.post(thanks, valid()).status_code == 405
    assert Submission.objects.count() == 0


def test_logged_in_lead_submits_like_anyone_and_no_user_is_stored(client, project):
    client.force_login(project.owner)

    page = client.get(url(project)).content.decode()
    response = client.post(url(project), valid())

    assert 'Log out' in page
    assert response.status_code == 302
    assert not any(f.name in ('user', 'owner') for f in Submission._meta.get_fields())
    assert Submission.objects.count() == 1


def test_project_name_is_escaped(client, django_user_model):
    owner = django_user_model.objects.create_user('o', password='x-secret-1')
    project = Project.objects.create(owner=owner, name='<b>x</b>')

    html = client.get(url(project)).content.decode()

    assert '<h1>&lt;b&gt;x&lt;/b&gt;</h1>' in html


# Form

def test_form_texts_and_dimension_order(client, project):
    html = client.get(url(project)).content.decode()

    assert 'Rate the four statements for this week. It takes under a minute.' in html
    assert ANON_TEXT in html
    legends = re.findall(r'<legend class="rating__legend">(.*?)</legend>', html)
    assert legends == [
        'My workload is manageable',
        'Our goals and priorities are clear',
        'We work well together',
        'I am confident we will deliver',
    ]
    assert html.count('<fieldset class="rating"') == 4
    assert '1 = Strongly disagree' in html and '5 = Strongly agree' in html
    assert 'checked' not in html
    assert html.count('required') == 20
    assert '<button class="button button--primary" type="submit">Submit</button>' in html


def test_scale_zero_to_ten(client, project, settings):
    settings.PULSE_SCALE_MIN, settings.PULSE_SCALE_MAX = 0, 10
    html = client.get(url(project)).content.decode()

    assert html.count('name="workload"') == 11
    assert '0 = Strongly disagree' in html and '10 = Strongly agree' in html
    response = client.post(url(project), valid(**{n: '0' for n in FIELDS}))
    assert response.status_code == 302
    assert Submission.objects.get().workload == 0


def test_scale_one_to_two(client, project, settings):
    settings.PULSE_SCALE_MIN, settings.PULSE_SCALE_MAX = 1, 2
    html = client.get(url(project)).content.decode()

    assert html.count('name="clarity"') == 2


def test_noindex_no_script_no_htmx_no_inline_style(client, project):
    for path in (url(project), url(project) + 'thanks/'):
        html = client.get(path).content.decode()
        assert '<meta name="robots" content="noindex">' in html
        assert '<script' not in html
        assert 'htmx' not in html and 'hx-' not in html
        assert 'style=' not in html and '<style' not in html


# Anonymity warning

@pytest.mark.parametrize('count, shown', [(0, True), (4, True), (5, False), (6, False)])
def test_warning_threshold_boundary(client, project, count, shown):
    add_submissions(project, count)

    html = client.get(url(project)).content.decode()

    assert (WARNING in html) is shown
    if shown:
        assert 'fewer than 5 people have responded for this week, so individual answers may be recognisable.' in html


def test_warning_uses_configured_threshold(client, project, settings):
    settings.PULSE_ANONYMITY_THRESHOLD = 2
    add_submissions(project, 1)
    assert 'fewer than 2 people' in client.get(url(project)).content.decode()
    add_submissions(project, 1)
    assert WARNING not in client.get(url(project)).content.decode()


def test_other_project_and_earlier_week_do_not_count(client, project):
    other = Project.objects.create(owner=project.owner, name='Other')
    add_submissions(other, 5)
    add_submissions(project, 5, week='2020-W01')

    assert WARNING in client.get(url(project)).content.decode()


def test_warning_still_shown_after_rejected_post(client, project):
    response = client.post(url(project), {})

    assert response.status_code == 200
    assert WARNING in response.content.decode()


# Submitting

def test_valid_post_stores_one_submission_and_redirects(client, project):
    response = client.post(url(project), {'workload': '1', 'clarity': '2', 'collaboration': '4', 'progress': '5'})

    assert response.status_code == 302
    assert response['Location'] == url(project) + 'thanks/'
    s = Submission.objects.get()
    assert (s.project, s.week_key) == (project, current_week_key())
    assert (s.workload, s.clarity, s.collaboration, s.progress) == (1, 2, 4, 5)


def test_extra_fields_are_ignored(client, project):
    other = Project.objects.create(owner=project.owner, name='Other')

    client.post(url(project), valid(week_key='1999-W01', project=other.pk, project_id=other.pk, id=999))

    s = Submission.objects.get()
    assert s.project == project and s.week_key == current_week_key() and s.pk != 999


def test_week_is_taken_at_post_time_in_instance_time_zone(client, project, settings, monkeypatch):
    settings.TIME_ZONE = 'Europe/Zurich'
    monkeypatch.setattr(timezone, 'now', lambda: datetime(2026, 9, 27, 21, 0, tzinfo=UTC))  # Sunday 23:00
    client.get(url(project))
    monkeypatch.setattr(timezone, 'now', lambda: datetime(2026, 9, 27, 22, 30, tzinfo=UTC))  # Monday 00:30

    client.post(url(project), valid())

    assert Submission.objects.get().week_key == '2026-W40'


def test_thanks_page(client, project):
    html = client.get(url(project) + 'thanks/').content.decode()

    assert '<h1>Thank you</h1>' in html
    assert 'Your answers have been saved.' in html
    assert '/projects/' not in html
    assert client.get(url(project) + 'thanks/').content.decode() == html
    assert Submission.objects.count() == 0


def test_resubmitting_from_a_fresh_browser_is_accepted(project):
    # Without the pulse_submitted cookie (#12) a second submission is saved.
    Client().post(url(project), valid())
    Client().post(url(project), valid())

    assert Submission.objects.count() == 2


def test_missing_ratings_show_errors_and_keep_choices(client, project):
    response = client.post(url(project), {'workload': '2', 'clarity': ''})
    html = response.content.decode()

    assert response.status_code == 200
    assert html.count('rating--invalid') == 3
    assert html.count('Choose a rating.') == 3
    assert html.count('checked') == 1
    assert Submission.objects.count() == 0


def test_all_missing_shows_four_errors(client, project):
    html = client.post(url(project), {}).content.decode()

    assert html.count('Choose a rating.') == 4


@pytest.mark.parametrize('bad', ['6', '0', '-1', 'abc', '2.5', '1e1', '1_0', '٣', ' '])
def test_tampered_value_is_rejected_and_not_preselected(client, project, bad):
    response = client.post(url(project), valid(workload=bad))
    html = response.content.decode()

    assert response.status_code == 200
    assert html.count('Choose a rating.') == 1
    assert 'rating rating--invalid' in html
    assert html.count('checked') == 3
    assert Submission.objects.count() == 0


def test_last_value_wins(client, project):
    client.post(url(project), 'workload=1&workload=5&clarity=3&collaboration=3&progress=3',
                content_type='application/x-www-form-urlencoded')

    assert Submission.objects.get().workload == 5


def test_no_row_when_any_field_invalid(client, project):
    client.post(url(project), valid(progress='9'))

    assert Submission.objects.count() == 0


def test_no_session_and_only_csrf_cookie(client, project):
    get = client.get(url(project))
    post = client.post(url(project), valid())

    assert set(get.cookies) <= {'csrftoken'}
    assert set(post.cookies) <= {'csrftoken', 'pulse_submitted'}
    assert Session.objects.count() == 0


def test_csrf_is_enforced(project):
    strict = Client(enforce_csrf_checks=True)

    assert '<input type="hidden" name="csrfmiddlewaretoken"' in strict.get(url(project)).content.decode()
    assert strict.post(url(project), valid()).status_code == 403
    assert Submission.objects.count() == 0


def test_submission_has_only_expected_columns():
    names = {f.name for f in Submission._meta.get_fields()}

    assert names == {'id', 'project', 'week_key', *FIELDS}
