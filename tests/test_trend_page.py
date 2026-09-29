import json
import re
from datetime import datetime, timezone as dt_timezone
from html.parser import HTMLParser

import pytest
from django.conf import settings
from django.contrib.auth import get_user_model
from django.utils import timezone

from pulse import views
from pulse.models import Project, Submission

User = get_user_model()
PASSWORD = 'correct-horse-battery-1'
UTC = dt_timezone.utc
DIMENSIONS = ('workload', 'clarity', 'collaboration', 'progress')
LABELS = [
    'My workload is manageable',
    'Our goals and priorities are clear',
    'We work well together',
    'I am confident we will deliver',
]


@pytest.fixture
def admin(db):
    return User.objects.create_user('admin', password=PASSWORD, is_superuser=True, is_staff=True)


@pytest.fixture
def anna(db):
    return User.objects.create_user('anna', password=PASSWORD)


@pytest.fixture
def ben(db):
    return User.objects.create_user('ben', password=PASSWORD)


@pytest.fixture
def project(anna):
    return Project.objects.create(name='Apollo', owner=anna)


def submit(project, week_key, ratings=(3, 3, 3, 3), times=1):
    for _ in range(times):
        Submission.objects.create(
            project=project, week_key=week_key, **dict(zip(DIMENSIONS, ratings))
        )


def freeze(monkeypatch, *args):
    monkeypatch.setattr(timezone, 'now', lambda: datetime(*args, tzinfo=UTC))


def page(client, project, user):
    client.force_login(user)
    response = client.get(f'/projects/{project.pk}/')
    assert response.status_code == 200
    return response.content.decode()


def payload(html):
    match = re.search(r'<script id="trend-data" type="application/json">(.*?)</script>', html, re.S)
    return json.loads(match.group(1))


def table_rows(html):
    body = re.search(r'<tbody>(.*?)</tbody>', html, re.S).group(1)
    rows = []
    for row in re.findall(r'<tr>(.*?)</tr>', body, re.S):
        header = re.search(r'<th scope="row">(.*?)</th>', row).group(1)
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)
        rows.append((header, cells))
    return rows


def strip_tokens(html):
    return re.sub(r'(csrfmiddlewaretoken" value="|X-CSRFToken": ")[^"]*', r'\1', html)


# Access

def test_owner_sees_project_name_as_h1(client, project, anna):
    html = page(client, project, anna)

    assert '<h1>Apollo</h1>' in html
    assert '<title>Apollo · Pulse Check</title>' in html


@pytest.mark.parametrize('viewer', ['ben', 'admin'])
def test_other_user_gets_same_404_as_missing_project(client, project, request, viewer):
    client.force_login(request.getfixturevalue(viewer))

    other = client.get(f'/projects/{project.pk}/')
    missing = client.get('/projects/987654/')

    assert other.status_code == 404
    assert strip_tokens(other.content.decode()) == strip_tokens(missing.content.decode())
    assert 'Page not found' in other.content.decode()
    assert 'Apollo' not in other.content.decode()


def test_anonymous_is_redirected_to_login_and_back(client, project, anna):
    response = client.get(f'/projects/{project.pk}/')

    assert response.status_code == 302
    assert response['Location'] == f'/login/?next=/projects/{project.pk}/'

    login = client.post(response['Location'], {'username': 'anna', 'password': PASSWORD})
    assert login.status_code == 302
    assert client.get(f'/projects/{project.pk}/').status_code == 200


def test_anonymous_redirect_is_the_same_for_unknown_id(client, db):
    response = client.get('/projects/987654/')

    assert response.status_code == 302
    assert response['Location'] == '/login/?next=/projects/987654/'


@pytest.mark.parametrize('path', ['/projects/abc/', '/projects/99999999999999999999/'])
def test_bad_ids_return_404(client, anna, path):
    client.force_login(anna)

    assert client.get(path).status_code == 404


def test_head_is_allowed_and_other_methods_return_405(client, project, anna):
    client.force_login(anna)
    url = f'/projects/{project.pk}/'

    assert client.head(url).status_code == 200
    for method in ('post', 'put', 'patch', 'delete'):
        assert getattr(client, method)(url).status_code == 405


def test_project_name_is_escaped(client, anna):
    project = Project.objects.create(name='<b>x</b>', owner=anna)
    html = page(client, project, anna)

    assert '<h1>&lt;b&gt;x&lt;/b&gt;</h1>' in html
    assert '<title>&lt;b&gt;x&lt;/b&gt; · Pulse Check</title>' in html
    assert '<b>x</b>' not in html


# Page content

def test_page_order_and_share_link(client, project, anna, monkeypatch):
    freeze(monkeypatch, 2026, 9, 30, 12)
    submit(project, '2026-W40')
    html = page(client, project, anna)

    link = f'http://testserver/p/{project.share_token}/'
    positions = [
        html.index('<a href="/projects/">All projects</a>'),
        html.index('<h1>'),
        html.index(link),
        html.index('<h2 id="trend-heading">Trend by week</h2>'),
        html.index('<h2 id="table-heading">Weekly figures</h2>'),
    ]
    assert positions == sorted(positions)
    assert f'id="share-link-{project.pk}"' in html
    assert f'data-copy-target="share-link-{project.pk}"' in html
    assert 'Copy link' in html
    assert 'aria-live="polite"' in html
    assert 'js/copy-link.js' in html
    assert html.count('<main') == 1
    assert '<html lang="en">' in html


def test_page_has_no_submission_ids_or_individual_ratings(client, project, anna, monkeypatch):
    freeze(monkeypatch, 2026, 9, 30, 12)
    submit(project, '2026-W40', ratings=(1, 2, 4, 5))
    submit(project, '2026-W40', ratings=(3, 2, 4, 5))
    html = page(client, project, anna)
    data = payload(html)

    assert set(data) == {'scale_min', 'scale_max', 'threshold', 'weeks'}
    assert 'Apollo' not in json.dumps(data)
    assert project.share_token not in json.dumps(data)
    assert data['weeks'][0]['workload'] == 2.0


# Weeks and gaps

def test_axis_fills_gaps_up_to_current_week(client, project, anna, monkeypatch):
    freeze(monkeypatch, 2026, 9, 30, 12)  # 2026-W40
    submit(project, '2026-W37')
    submit(project, '2026-W39', ratings=(4, 4, 4, 4))
    data = payload(page(client, project, anna))

    assert [w['week_key'] for w in data['weeks']] == ['2026-W37', '2026-W38', '2026-W39', '2026-W40']
    gap = data['weeks'][1]
    assert gap == {
        'week_key': '2026-W38', 'range': '14 Sep – 20 Sep 2026', 'count': 0, 'limited': False,
        'workload': None, 'clarity': None, 'collaboration': None, 'progress': None,
    }
    assert data['weeks'][3]['count'] == 0
    assert data['weeks'][2]['workload'] == 4.0


def test_weeks_have_exactly_the_contract_keys(client, project, anna, monkeypatch):
    freeze(monkeypatch, 2026, 9, 30, 12)
    submit(project, '2026-W40')
    week = payload(page(client, project, anna))['weeks'][0]

    assert set(week) == {'week_key', 'range', 'count', 'limited', *DIMENSIONS}


def test_axis_crosses_year_change_with_week_53(client, project, anna, monkeypatch):
    freeze(monkeypatch, 2027, 1, 12, 12)  # 2027-W02
    submit(project, '2026-W52')
    keys = [w['week_key'] for w in payload(page(client, project, anna))['weeks']]

    assert keys == ['2026-W52', '2026-W53', '2027-W01', '2027-W02']


def test_axis_crosses_year_change_without_week_53(client, project, anna, monkeypatch):
    freeze(monkeypatch, 2026, 1, 6, 12)  # 2026-W02
    submit(project, '2025-W51')
    keys = [w['week_key'] for w in payload(page(client, project, anna))['weeks']]

    assert keys == ['2025-W51', '2025-W52', '2026-W01', '2026-W02']


def test_axis_ends_at_newest_week_when_clock_is_behind(client, project, anna, monkeypatch):
    freeze(monkeypatch, 2026, 9, 30, 12)  # 2026-W40
    submit(project, '2026-W39')
    submit(project, '2026-W42')
    keys = [w['week_key'] for w in payload(page(client, project, anna))['weeks']]

    assert keys == ['2026-W39', '2026-W40', '2026-W41', '2026-W42']


def test_single_week_axis_has_one_entry(client, project, anna, monkeypatch):
    freeze(monkeypatch, 2026, 9, 30, 12)
    submit(project, '2026-W40')
    data = payload(page(client, project, anna))

    assert [w['week_key'] for w in data['weeks']] == ['2026-W40']


def test_old_data_axis_runs_to_current_week(client, project, anna, monkeypatch):
    freeze(monkeypatch, 2026, 9, 30, 12)
    submit(project, '2026-W36')
    weeks = payload(page(client, project, anna))['weeks']

    assert [w['week_key'] for w in weeks] == ['2026-W36', '2026-W37', '2026-W38', '2026-W39', '2026-W40']
    assert [w['count'] for w in weeks] == [1, 0, 0, 0, 0]


def test_date_ranges(client, project, anna, monkeypatch):
    freeze(monkeypatch, 2027, 1, 6, 12)
    submit(project, '2026-W40')
    submit(project, '2026-W53')
    ranges = {w['week_key']: w['range'] for w in payload(page(client, project, anna))['weeks']}

    assert ranges['2026-W40'] == '28 Sep – 4 Oct 2026'
    assert ranges['2026-W53'] == '28 Dec 2026 – 3 Jan 2027'
    assert ranges['2027-W01'] == '4 Jan – 10 Jan 2027'


def test_scale_and_threshold_come_from_settings(client, project, anna, settings, monkeypatch):
    freeze(monkeypatch, 2026, 9, 30, 12)
    settings.PULSE_SCALE_MIN = 0
    settings.PULSE_SCALE_MAX = 10
    settings.PULSE_ANONYMITY_THRESHOLD = 3
    submit(project, '2026-W40', ratings=(0, 5, 10, 7))
    data = payload(page(client, project, anna))

    assert (data['scale_min'], data['scale_max'], data['threshold']) == (0, 10, 3)


def test_limited_flag_uses_threshold_and_ignores_gaps(client, project, anna, settings, monkeypatch):
    freeze(monkeypatch, 2026, 10, 14, 12)  # 2026-W42
    settings.PULSE_ANONYMITY_THRESHOLD = 2
    submit(project, '2026-W40', times=1)
    submit(project, '2026-W42', times=2)
    weeks = payload(page(client, project, anna))['weeks']

    assert [(w['week_key'], w['limited']) for w in weeks] == [
        ('2026-W40', True), ('2026-W41', False), ('2026-W42', False),
    ]


# Table

def test_table_structure_and_rows(client, project, anna, monkeypatch):
    freeze(monkeypatch, 2026, 10, 7, 12)  # 2026-W41
    submit(project, '2026-W39', ratings=(4, 4, 4, 5))
    submit(project, '2026-W39', ratings=(3, 4, 4, 5))
    submit(project, '2026-W39', ratings=(4, 4, 4, 4))
    html = page(client, project, anna)

    assert 'role="region"' in html and 'tabindex="0"' in html
    assert 'aria-labelledby="weeks-caption"' in html
    assert re.search(r'<caption id="weeks-caption"[^>]*>Weekly results</caption>', html)
    headers = re.findall(r'<th scope="col"[^>]*>(.*?)</th>', html)
    assert headers == ['Week', 'Responses', *LABELS, 'Note']
    rows = table_rows(html)
    assert [r[0] for r in rows] == ['2026-W39', '2026-W40', '2026-W41']
    assert rows[0][1][:5] == ['3', '3.7', '4.0', '4.0', '4.7']
    assert rows[1][1] == ['0', '–', '–', '–', '–', '']
    assert html.count('<td class="data-table__number">') == 3 * 5


def test_table_rounds_half_up_with_a_dot(client, project, anna, monkeypatch):
    freeze(monkeypatch, 2026, 9, 30, 12)
    submit(project, '2026-W40', ratings=(3, 4, 3, 3))
    submit(project, '2026-W40', ratings=(4, 4, 3, 3))
    submit(project, '2026-W40', ratings=(4, 4, 3, 3))
    submit(project, '2026-W40', ratings=(4, 4, 3, 3))

    assert table_rows(page(client, project, anna))[0][1][1] == '3.8'


@pytest.mark.parametrize('threshold', [2, 5])
def test_note_appears_only_below_threshold(client, project, anna, settings, monkeypatch, threshold):
    freeze(monkeypatch, 2026, 10, 14, 12)  # 2026-W42
    settings.PULSE_ANONYMITY_THRESHOLD = threshold
    submit(project, '2026-W40', times=threshold - 1)
    submit(project, '2026-W41', times=threshold)
    rows = table_rows(page(client, project, anna))

    expected = (
        '<span class="anonymity-note"><strong>Limited anonymity:</strong> fewer than '
        f'{threshold} people have responded for this week, so individual answers may be recognisable.</span>'
    )
    assert rows[0][1][-1] == expected
    assert rows[1][1][-1] == ''
    assert rows[2][1][-1] == ''  # gap week: no note


# Empty state and scripts

def test_empty_state_has_no_chart_table_or_scripts(client, project, anna):
    html = page(client, project, anna)

    assert 'No responses yet. Share the link with your team.' in html
    assert f'http://testserver/p/{project.share_token}/' in html
    assert html.count('class="copy-link"') == 1
    assert '<canvas' not in html and '<table' not in html
    assert 'chart.umd.js' not in html and 'trend-chart.js' not in html
    assert 'trend-data' not in html
    assert 'js/copy-link.js' in html


def test_scripts_are_loaded_in_order_with_defer(client, project, anna, monkeypatch):
    freeze(monkeypatch, 2026, 9, 30, 12)
    submit(project, '2026-W40')
    html = page(client, project, anna)

    srcs = re.findall(r'<script src="([^"]+)" defer></script>', html)
    chart = [i for i, s in enumerate(srcs) if s.endswith('vendor/chart.umd.js')]
    trend = [i for i, s in enumerate(srcs) if s.endswith('js/trend-chart.js')]
    assert len(chart) == len(trend) == 1
    assert chart[0] < trend[0]
    assert html.count('id="trend-data"') == 1


def test_canvas_is_described_and_fallback_message_is_in_html(client, project, anna, monkeypatch):
    freeze(monkeypatch, 2026, 9, 30, 12)
    submit(project, '2026-W40')
    html = page(client, project, anna)

    assert re.search(r'<canvas id="trend-chart" role="img" aria-label="Line chart of the weekly averages[^"]*table below[^"]*">', html)
    assert '<p id="chart-fallback">The chart could not be shown. The table below has the same figures.</p>' in html


class _Inline(HTMLParser):
    def __init__(self):
        super().__init__()
        self.problems = []
        self.classes = set()

    def handle_starttag(self, tag, attrs):
        if tag == 'style':
            self.problems.append('style element')
        if tag == 'script' and not any(name == 'src' for name, _ in attrs) \
                and ('type', 'application/json') not in attrs:
            self.problems.append('inline script')
        for name, value in attrs:
            if name == 'style' or name.startswith('on'):
                self.problems.append(name)
            if name == 'class':
                self.classes.update(value.split())


def test_page_has_no_inline_script_or_style(client, project, anna, monkeypatch):
    freeze(monkeypatch, 2026, 9, 30, 12)
    submit(project, '2026-W40', times=1)
    parser = _Inline()
    parser.feed(page(client, project, anna))

    assert parser.problems == []
    assert 'chart' in parser.classes


def test_chart_script_has_no_eval_or_network_access():
    source = open('pulse/static/pulse/js/trend-chart.js').read()

    for forbidden in ('eval(', 'new Function', 'fetch(', 'XMLHttpRequest', 'setTimeout("', "setTimeout('", 'sendBeacon'):
        assert forbidden not in source


def test_view_uses_weekly_aggregates_only(client, project, anna, monkeypatch):
    freeze(monkeypatch, 2026, 9, 30, 12)
    monkeypatch.setattr(views, 'weekly_aggregates', lambda p: [
        {'week_key': '2026-W40', 'count': 1, 'workload': 1.5, 'clarity': 2.0, 'collaboration': 3.0, 'progress': 4.0},
    ])
    data = payload(page(client, project, anna))

    assert data['weeks'][0]['workload'] == 1.5


def test_table_cells_do_not_break_words():
    css = (settings.BASE_DIR / 'pulse/static/pulse/css/site.css').read_text()
    rule = re.search(r'\.data-table th,\s*\.data-table td\s*\{([^}]*)\}', css).group(1)

    assert 'overflow-wrap: normal' in rule
    assert 'word-break: normal' in rule
