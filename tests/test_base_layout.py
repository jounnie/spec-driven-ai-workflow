import hashlib
import json
import re
from html.parser import HTMLParser
from pathlib import Path

from django.contrib.auth import get_user_model
from django.contrib.messages import constants
from django.contrib.messages.storage.base import Message
from django.template import engines
from django.template.loader import render_to_string
from django.test import Client

ROOT = Path(__file__).resolve().parent.parent
DESIGN_SYSTEM = ROOT / '_docs' / 'design-system.md'
STATIC_DIR = ROOT / 'pulse' / 'static' / 'pulse'
SITE_CSS = STATIC_DIR / 'css' / 'site.css'
VENDOR_DIR = STATIC_DIR / 'vendor'


class Page(HTMLParser):
    """Collects every start tag with its attributes, and inline script bodies."""

    def __init__(self, html):
        super().__init__()
        self.tags = []
        self.inline_scripts = 0
        self.title = None
        self._in_title = False
        self.feed(html)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        self.tags.append((tag, attrs))
        if tag == 'script' and 'src' not in attrs:
            self.inline_scripts += 1
        if tag == 'title':
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == 'title':
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title = (self.title or '') + data

    def find(self, tag):
        return [attrs for name, attrs in self.tags if name == tag]


def render_base(messages=(), template_string=None, request=None):
    context = {'messages': list(messages)}
    if template_string:
        return engines['django'].from_string(template_string).render(context, request)
    return render_to_string('pulse/base.html', context, request)


def class_index():
    text = DESIGN_SYSTEM.read_text()
    section = text.split('## Class index', 1)[1]
    names = set()
    for line in section.splitlines():
        if line.startswith('|') and not line.startswith('|---') and not line.startswith('| Class'):
            first_cell = line.split('|')[1]
            names.update(re.findall(r'`([^`]+)`', first_cell))
    return names


def design_tokens():
    """Return {name: value} for every custom property in the design system's css blocks."""
    text = DESIGN_SYSTEM.read_text()
    tokens = {}
    for block in re.findall(r'```css\n(.*?)```', text, re.S):
        for name, value in re.findall(r'(--[a-z0-9-]+):\s*([^;]+);', block):
            tokens[name] = value.strip()
    return tokens


def css_without_root_blocks():
    css = SITE_CSS.read_text()
    return re.sub(r':root\s*\{[^}]*\}', '', css)


def sample_messages():
    return [
        Message(constants.ERROR, 'Something failed'),
        Message(constants.SUCCESS, 'Saved'),
    ]


# Base template

def test_base_template_has_title_content_and_scripts_blocks():
    html = render_base(template_string=(
        "{% extends 'pulse/base.html' %}"
        "{% block title %}Dash · {{ block.super }}{% endblock %}"
        "{% block content %}<p>BODY</p>{% endblock %}"
        "{% block scripts %}<script src=\"/x.js\"></script>{% endblock %}"
    ))

    assert '<p>BODY</p>' in html
    assert '/x.js' in html
    assert Page(html).title == 'Dash · Pulse Check'


def test_base_template_title_is_just_the_app_name_without_page_title():
    assert Page(render_base()).title == 'Pulse Check'


def test_base_template_has_lang_viewport_and_one_main():
    page = Page(render_base())

    assert [a['lang'] for a in page.find('html')] == ['en']
    viewports = [a for a in page.find('meta') if a.get('name') == 'viewport']
    assert viewports[0]['content'] == 'width=device-width, initial-scale=1'
    assert len(page.find('main')) == 1


def test_base_template_header_links_app_name_and_has_main_nav():
    page = Page(render_base())

    brand = [a for name, a in page.tags if name == 'a' and 'site-header__brand' in a.get('class', '')]
    assert brand[0]['href'] == '/'
    navs = page.find('nav')
    assert len(navs) == 1
    assert navs[0]['aria-label'] == 'Main'


def test_base_template_messages_use_class_prefix_and_role_per_level():
    levels = [
        (constants.DEBUG, 'message--info', 'Info:', 'status'),
        (constants.INFO, 'message--info', 'Info:', 'status'),
        (constants.SUCCESS, 'message--success', 'Success:', 'status'),
        (constants.WARNING, 'message--warning', 'Warning:', 'status'),
        (constants.ERROR, 'message--error', 'Error:', 'alert'),
    ]
    for level, css_class, prefix, role in levels:
        html = render_base([Message(level, 'Hello')])

        assert f'class="message {css_class}" role="{role}"' in html
        assert f'<strong class="message__prefix">{prefix}</strong> Hello' in html


def test_base_template_messages_region_is_inside_main_and_before_content():
    html = render_base(
        sample_messages(),
        template_string="{% extends 'pulse/base.html' %}{% block content %}<p>BODY</p>{% endblock %}",
    )

    main = html.split('<main', 1)[1].split('</main>', 1)[0]
    assert main.count('class="messages"') == 1
    assert main.index('class="messages"') < main.index('<p>BODY</p>')


def test_base_template_without_messages_renders_no_messages_region():
    assert 'messages' not in render_base()


def test_base_template_escapes_message_text():
    html = render_base([Message(constants.INFO, '<b>x</b>')])

    assert '<b>x</b>' not in html
    assert '&lt;b&gt;x&lt;/b&gt;' in html


def test_404_page_extends_base_and_shows_error_page(client, settings):
    settings.DEBUG = False

    response = client.get('/no/such/page/')

    assert response.status_code == 404
    html = response.content.decode()
    assert '<div class="error-page">' in html
    assert '<h1>Page not found</h1>' in html
    assert '<p>This page does not exist.</p>' in html
    assert Page(html).title == 'Page not found · Pulse Check'
    assert 'site-header__brand' in html
    assert 'no/such/page' not in html


def test_base_template_renders_for_anonymous_visitor(client):
    response = client.get('/no/such/page/')

    assert response.status_code == 404
    assert 'Pulse Check' in response.content.decode()


def test_base_template_renders_for_logged_in_user(client, db):
    user = get_user_model().objects.create_user('anna', password='pw-for-tests-1')
    client.force_login(user)

    response = client.get('/no/such/page/')

    assert response.status_code == 404
    html = response.content.decode()
    assert 'site-header__brand' in html
    assert '<li class="site-nav__user">anna</li>' in html


# Stylesheet

def test_site_css_is_the_only_stylesheet_and_is_linked_with_static():
    page = Page(render_base())

    links = [a for a in page.find('link') if a.get('rel') == 'stylesheet']
    assert [a['href'] for a in links] == ['/static/pulse/css/site.css']
    assert [p.name for p in (STATIC_DIR / 'css').iterdir()] == ['site.css']


def test_site_css_defines_every_design_system_token_with_its_value():
    tokens = design_tokens()
    css = SITE_CSS.read_text()

    assert '--color-accent' in tokens and '--space-4' in tokens and '--font-sans' in tokens
    for name, value in tokens.items():
        normalised = re.sub(r'\s+', ' ', value)
        pattern = re.escape(name) + r':\s*' + r'\s+'.join(re.escape(part) for part in normalised.split(' ')) + r'\s*;'
        assert re.search(pattern, css), f'{name}: {value} missing from site.css'


def test_site_css_defines_chart_colours():
    css = SITE_CSS.read_text()

    for name, value in [
        ('--chart-1', '#0072b2'),
        ('--chart-2', '#c05000'),
        ('--chart-3', '#00805c'),
        ('--chart-4', '#1b1f24'),
    ]:
        assert f'{name}: {value};' in css


def test_site_css_has_a_rule_for_every_class_in_the_class_index():
    names = class_index()
    css = css_without_root_blocks()

    assert {'container', 'button--danger', 'visually-hidden', 'error-page'} <= names
    for name in names:
        assert re.search(r'\.' + re.escape(name) + r'(?![\w-])', css), f'.{name} has no rule'


def test_site_css_component_rules_use_no_raw_hex_values():
    assert not re.search(r'#[0-9a-fA-F]{3,8}\b', css_without_root_blocks())


def test_site_css_focus_ring_is_defined_and_outline_is_never_removed():
    css = SITE_CSS.read_text()

    assert re.search(
        r':focus-visible\s*\{[^}]*outline:\s*3px solid var\(--color-focus\);[^}]*outline-offset:\s*2px;',
        css,
    )
    assert 'outline: none' not in css
    assert 'outline:none' not in css
    assert 'outline: 0' not in css


def rule_body(selector):
    css = SITE_CSS.read_text()
    match = re.search(re.escape(selector) + r'\s*\{([^}]*)\}', css)
    assert match, f'{selector} rule missing'
    return match.group(1)


def test_site_css_layout_rules_from_design_system():
    container = rule_body('.container')
    assert 'max-width: var(--content-max-width)' in container
    assert 'margin-left: auto' in container and 'margin-right: auto' in container
    assert 'padding-left: var(--page-gutter)' in container
    assert 'padding-right: var(--page-gutter)' in container

    copy_url = rule_body('.copy-link__url')
    assert 'overflow-wrap: anywhere' in copy_url
    assert 'user-select: all' in copy_url

    options = rule_body('.rating__options')
    assert 'display: flex' in options and 'flex-wrap: wrap' in options
    assert 'gap: var(--space-2)' in options

    assert 'min-height: 2.75rem' in rule_body('.button')
    option = rule_body('.rating__option')
    assert 'min-height: 2.75rem' in option and 'min-width: 2.75rem' in option


def test_site_css_only_table_scroll_scrolls_sideways():
    css = re.sub(r'/\*.*?\*/', '', SITE_CSS.read_text(), flags=re.S)
    scrolling = re.findall(r'([^{}]+)\{[^}]*overflow(?:-x)?:\s*(?:auto|scroll)', css)

    assert [s.strip() for s in scrolling] == ['.table-scroll']


# Vendored assets

def readme_hashes():
    hashes = {}
    for line in (VENDOR_DIR / 'README.md').read_text().splitlines():
        cells = [c.strip() for c in line.split('|')]
        if len(cells) > 5 and cells[1].startswith('`') and re.fullmatch(r'`[0-9a-f]{64}`', cells[5]):
            hashes[cells[1].strip('`')] = cells[5].strip('`')
    return hashes


def test_vendored_files_match_the_hashes_in_the_vendor_readme():
    hashes = readme_hashes()

    assert set(hashes) == {
        'htmx.min.js', 'chart.umd.js', 'chart.umd.js.map', 'LICENSE-htmx.txt', 'LICENSE-chartjs.txt',
    }
    for name, expected in hashes.items():
        assert hashlib.sha256((VENDOR_DIR / name).read_bytes()).hexdigest() == expected, name


def test_vendored_files_match_the_hashes_named_in_the_issue():
    expected = {
        'htmx.min.js': 'd6fdc75f204e6bdefa99b69bf1e6d4ac69b8a364f77929f45c13476b4000f717',
        'chart.umd.js': 'ecc3cd1eeb8c34d2178e3f59fd63ec5a3d84358c11730af0b9958dc886d7652a',
        'chart.umd.js.map': '50f788499bc584696c2344c77e91af0f80a518eca93e312ddbb8008d7525d7fa',
    }

    assert {n: h for n, h in readme_hashes().items() if n in expected} == expected


# Loading scripts

def test_htmx_is_loaded_on_every_page_and_chart_js_is_not():
    html = render_base()

    assert '<script src="/static/pulse/vendor/htmx.min.js" defer></script>' in html
    assert 'chart.umd.js' not in html


def test_chart_js_is_loaded_only_by_pages_that_put_it_in_the_scripts_block():
    html = render_base(template_string=(
        "{% extends 'pulse/base.html' %}{% load static %}"
        "{% block scripts %}<script src=\"{% static 'pulse/vendor/chart.umd.js' %}\"></script>{% endblock %}"
    ))

    assert '/static/pulse/vendor/chart.umd.js' in html


def test_htmx_config_meta_disables_indicator_styles_and_eval():
    page = Page(render_base())

    metas = [a for a in page.find('meta') if a.get('name') == 'htmx-config']
    config = json.loads(metas[0]['content'])
    assert config['includeIndicatorStyles'] is False
    assert config['allowEval'] is False
    assert 'selfRequestsOnly' not in config


def test_base_template_uses_no_htmx_attribute_other_than_hx_headers_on_body():
    page = Page(render_base(sample_messages()))

    hx = [(name, key) for name, attrs in page.tags for key in attrs if key.startswith(('hx-', 'data-hx-'))]
    assert hx == [('body', 'hx-headers')]


def test_hx_headers_token_is_accepted_in_a_post_and_a_post_without_it_is_rejected():
    client = Client(enforce_csrf_checks=True)
    html = client.get('/no/such/page/').content.decode()
    body = [a for a in Page(html).find('body')][0]
    token = json.loads(body['hx-headers'])['X-CSRFToken']

    assert len(token) >= 32
    assert client.post('/health/', headers={'X-CSRFToken': token}).status_code == 200
    assert client.post('/health/').status_code == 403


# No third-party requests, nothing inline

def all_rendered_pages(settings):
    settings.DEBUG = False
    not_found = Client().get('/no/such/page/').content.decode()
    return [render_base(sample_messages()), not_found]


def test_pages_have_no_src_href_or_action_pointing_to_another_server(settings):
    for html in all_rendered_pages(settings):
        for name, attrs in Page(html).tags:
            for key in ('src', 'href', 'action'):
                value = attrs.get(key)
                if value is not None:
                    assert not re.match(r'(https?:|//)', value.strip(), re.I), f'{name} {key}={value}'


def test_pages_have_nothing_inline(settings):
    for html in all_rendered_pages(settings):
        page = Page(html)
        assert not page.find('style')
        assert page.inline_scripts == 0
        for name, attrs in page.tags:
            assert 'style' not in attrs, name
            assert not [k for k in attrs if k.startswith('on')], name


def test_pages_use_only_classes_from_the_class_index(settings):
    allowed = class_index()
    for html in all_rendered_pages(settings):
        used = set()
        for _, attrs in Page(html).tags:
            used.update(attrs.get('class', '').split())
        assert used, 'expected some classes'
        assert used <= allowed, used - allowed
