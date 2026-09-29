from datetime import datetime, timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

import pytest
from django.http import HttpRequest, HttpResponse
from django.test import Client
from django.utils import timezone

from pulse.conf import current_week_key
from pulse.models import Project, Submission

FIELDS = ('workload', 'clarity', 'collaboration', 'progress')
ZURICH = ZoneInfo('Europe/Zurich')
ALREADY = 'You have already responded this week.'


@pytest.fixture
def project(django_user_model):
    owner = django_user_model.objects.create_user('owner', password='secret-pw')
    return Project.objects.create(owner=owner, name='Apollo')


@pytest.fixture
def other_project(django_user_model):
    owner = django_user_model.objects.get(username='owner')
    return Project.objects.create(owner=owner, name='Zeus')


def url(project):
    return f'/p/{project.share_token}/'


def valid():
    return {name: '3' for name in FIELDS}


def salt(project):
    return f'pulse.submitted.{project.share_token}'


def signed(project, value):
    response = HttpResponse()
    response.set_signed_cookie('pulse_submitted', value, salt=salt(project))
    return response.cookies['pulse_submitted'].value


def set_cookie(client, project, value):
    client.cookies['pulse_submitted'] = signed(project, value)


def now_is(monkeypatch, settings, moment):
    settings.TIME_ZONE = 'Europe/Zurich'
    monkeypatch.setattr(timezone, 'now', lambda: moment)


def unsigned(project, response):
    request = HttpRequest()
    request.COOKIES['pulse_submitted'] = response.cookies['pulse_submitted'].value
    return request.get_signed_cookie('pulse_submitted', salt=salt(project))


# The cookie

def test_valid_post_sets_signed_cookie_with_attributes(client, project):
    response = client.post(url(project), valid())

    assert response.status_code == 302
    assert response['Location'] == f'/p/{project.share_token}/thanks/'
    morsel = response.cookies['pulse_submitted']
    assert morsel['path'] == f'/p/{project.share_token}/'
    assert morsel['httponly']
    assert morsel['samesite'] == 'Lax'
    assert morsel['domain'] == ''
    assert morsel['max-age'] == 691200
    assert morsel['secure'] == ''
    assert unsigned(project, response) == current_week_key()


def test_cookie_is_secure_on_secure_requests(client, project):
    response = client.post(url(project), valid(), secure=True)

    assert response.cookies['pulse_submitted']['secure'] is True


def test_cookie_holds_only_the_week_key(client, project):
    response = client.post(url(project), valid())

    payload = response.cookies['pulse_submitted'].value
    assert payload.startswith(f'{current_week_key()}:')
    assert str(Submission.objects.get().pk) not in payload.split(':')[0]


def test_cookie_is_not_set_without_a_saved_submission(client, project):
    assert 'pulse_submitted' not in client.get(url(project)).cookies
    assert 'pulse_submitted' not in client.get(url(project) + 'thanks/').cookies
    invalid = client.post(url(project), {'workload': '3'})
    assert invalid.status_code == 200
    assert 'pulse_submitted' not in invalid.cookies


def test_blocked_post_does_not_refresh_cookie(client, project):
    client.post(url(project), valid())

    response = client.post(url(project), valid())

    assert response.status_code == 200
    assert 'pulse_submitted' not in response.cookies


def test_nothing_is_stored_on_the_server(client, project):
    from django.contrib.sessions.models import Session

    client.post(url(project), valid())

    assert Session.objects.count() == 0
    assert Submission.objects.count() == 1


@pytest.mark.django_db
def test_no_pending_migrations():
    from django.core.management import call_command

    call_command('makemigrations', check=True, dry_run=True, verbosity=0)


def test_respondent_pages_set_only_the_two_cookies(client, project):
    get = client.get(url(project))
    post = client.post(url(project), valid())

    assert set(get.cookies) <= {'csrftoken'}
    assert set(post.cookies) <= {'csrftoken', 'pulse_submitted'}


# Second visit in the same week

def test_second_visit_shows_already_responded_page(client, project, monkeypatch, settings):
    now_is(monkeypatch, settings, datetime(2026, 9, 29, 10, 0, tzinfo=ZURICH))
    client.post(url(project), valid())

    response = client.get(url(project))
    html = response.content.decode()

    assert response.status_code == 200
    assert '<h1>Apollo</h1>' in html
    assert f'<p>{ALREADY} You can respond again from Monday, 5 October 2026.</p>' in html
    assert '<meta name="robots" content="noindex">' in html
    assert 'class="error-page"' in html
    for absent in ('<form class="rating', '<fieldset', 'type="radio"', 'Limited anonymity', 'response'):
        assert absent not in html.replace(ALREADY, '')
    assert '<form method="post" action="/p/' not in html
    assert '<script' not in html.replace('</script>', '').split('<main')[1]
    assert ' style=' not in html


def test_blocked_post_saves_nothing_and_shows_the_same_page(client, project):
    client.post(url(project), valid())

    for data in (valid(), {}):
        response = client.post(url(project), data)
        assert response.status_code == 200
        assert ALREADY in response.content.decode()
        assert 'field__error' not in response.content.decode()
    assert Submission.objects.count() == 1


def test_stale_second_tab_is_blocked(project):
    tab = Client(enforce_csrf_checks=True)
    token = tab.get(url(project)).cookies['csrftoken'].value
    tab.post(url(project), {**valid(), 'csrfmiddlewaretoken': token})
    assert Submission.objects.count() == 1

    response = tab.post(url(project), {**valid(), 'csrfmiddlewaretoken': token})

    assert response.status_code == 200
    assert ALREADY in response.content.decode()
    assert Submission.objects.count() == 1


def test_thanks_page_ignores_the_cookie(client, project):
    without = Client().get(url(project) + 'thanks/')
    client.post(url(project), valid())
    with_cookie = client.get(url(project) + 'thanks/')

    assert with_cookie.status_code == 200
    assert with_cookie.content == without.content
    assert Submission.objects.count() == 1


def test_logged_in_lead_is_treated_like_everyone_else(client, project, django_user_model):
    client.force_login(django_user_model.objects.get(username='owner'))
    client.post(url(project), valid())

    assert ALREADY in client.get(url(project)).content.decode()


def test_unknown_token_is_404_with_or_without_cookie(client, project):
    client.cookies['pulse_submitted'] = signed(project, current_week_key())

    assert client.get('/p/nope/').status_code == 404
    assert client.post('/p/nope/', valid()).status_code == 404


# Week changes

def test_cookie_from_an_earlier_week_is_replaced(client, project):
    set_cookie(client, project, '2000-W01')

    assert '<fieldset' in client.get(url(project)).content.decode()
    response = client.post(url(project), valid())

    assert response.status_code == 302
    assert unsigned(project, response) == current_week_key()
    assert Submission.objects.count() == 1


def test_cookie_from_a_future_week_is_ignored(client, project):
    set_cookie(client, project, '2999-W01')

    assert '<fieldset' in client.get(url(project)).content.decode()
    assert client.post(url(project), valid()).status_code == 302


def test_block_ends_at_monday_midnight_in_the_instance_time_zone(client, project, monkeypatch, settings):
    set_cookie(client, project, '2026-W40')

    now_is(monkeypatch, settings, datetime(2026, 10, 4, 23, 59, 59, tzinfo=ZURICH))
    assert ALREADY in client.get(url(project)).content.decode()

    now_is(monkeypatch, settings, datetime(2026, 10, 5, 0, 0, 0, tzinfo=ZURICH))
    assert '<fieldset' in client.get(url(project)).content.decode()
    assert client.post(url(project), valid()).status_code == 302
    assert Submission.objects.get().week_key == '2026-W41'


def test_block_works_across_the_year_change(client, project, monkeypatch, settings):
    set_cookie(client, project, '2026-W53')

    now_is(monkeypatch, settings, datetime(2027, 1, 3, 23, 59, 59, tzinfo=ZURICH))
    html = client.get(url(project)).content.decode()
    assert ALREADY in html
    assert 'Monday, 4 January 2027.' in html

    now_is(monkeypatch, settings, datetime(2027, 1, 4, 0, 0, 0, tzinfo=ZURICH))
    assert '<fieldset' in client.get(url(project)).content.decode()
    assert client.post(url(project), valid()).status_code == 302
    assert Submission.objects.get().week_key == '2027-W01'


# Tampered, foreign or unusable cookies

@pytest.mark.parametrize('value', ['', 'garbage', 'x:y:z', 'truncated'])
def test_unusable_cookies_are_ignored(client, project, value):
    client.cookies['pulse_submitted'] = value

    assert '<fieldset' in client.get(url(project)).content.decode()
    assert client.post(url(project), valid()).status_code == 302


def test_wrong_signature_and_truncated_cookie_are_ignored(client, project):
    good = signed(project, current_week_key())
    for value in (good[:-3], good[:-1] + ('a' if good[-1] != 'a' else 'b'), good.split(':')[0]):
        client.cookies['pulse_submitted'] = value
        assert '<fieldset' in client.get(url(project)).content.decode()


def test_cookie_for_project_a_does_not_block_project_b(client, project, other_project):
    response = client.post(url(project), valid())
    assert response.status_code == 302

    assert '<fieldset' in client.get(url(other_project)).content.decode()
    assert client.post(url(other_project), valid()).status_code == 302
    assert Submission.objects.filter(project=other_project).count() == 1


def test_cookie_of_a_is_rejected_when_sent_by_hand_to_b(client, project, other_project):
    client.cookies['pulse_submitted'] = signed(project, current_week_key())

    assert '<fieldset' in client.get(url(other_project)).content.decode()
    assert client.post(url(other_project), valid()).status_code == 302


# Cookie-blocking browsers and anonymity

def test_browser_without_cookies_cannot_submit(project):
    response = Client(enforce_csrf_checks=True).post(url(project), valid())

    assert response.status_code == 403
    assert Submission.objects.count() == 0
    assert 'pulse_submitted' not in response.cookies


def test_blocked_posts_do_not_change_the_week_count(client, project):
    client.post(url(project), valid())
    for _ in range(3):
        client.post(url(project), valid())

    assert Submission.objects.filter(project=project).count() == 1
    other = Client().get(url(project)).content.decode()
    assert 'fewer than 5 people' in other
