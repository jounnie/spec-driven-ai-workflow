# Design system

How Pulse Check pages look and behave. Every UI task (#5 onwards) follows
this document, so the app has one consistent, accessible interface without
a designer involved.

## Ground rules

- **No CSS framework, no CDN, no web fonts, no third-party assets.** A
  self-hosted instance makes no requests to other servers (#5).
- **All CSS lives in one file:** `pulse/static/pulse/css/site.css`, built
  in #5. Pages do not add their own stylesheets.
- **No inline styles or scripts.** No `style` attribute, no `<style>`
  element, no inline `<script>` body and no `on…=` event attribute, so the
  Content Security Policy in #17 can forbid everything inline. JavaScript
  lives in static files under `pulse/static/pulse/js/`; data for scripts is
  passed with Django's `json_script`.
- **Only the classes listed in [Class index](#class-index)** are used in
  templates, together with plain semantic HTML (`<header>`, `<nav>`,
  `<main>`, `<h1>`, `<table>`, `<fieldset>`, …). #5 implements exactly these
  classes; a task that needs a new one adds it here first.
- **Pages work without JavaScript.** JavaScript only adds conveniences such
  as the copy button (#10) and draws the chart (#14).
- Light theme only in v1.

## Tokens

Tokens are CSS custom properties on `:root` in `site.css`. Components use
the tokens, never raw hex values.

### Colours

```css
:root {
  --color-background: #ffffff;    /* page background, chart background */
  --color-surface: #f4f5f7;       /* header, table header, cards */
  --color-text: #1b1f24;          /* body text */
  --color-text-muted: #525a66;    /* help text, secondary information */
  --color-border: #6b7280;        /* input borders, table and card borders */
  --color-accent: #1d4ed8;        /* links, primary buttons, focus ring */
  --color-accent-hover: #1e3a8a;  /* hover state of links and primary buttons */
  --color-success: #15703a;
  --color-warning: #8a4b00;
  --color-danger: #b42318;        /* danger buttons, field errors */
  --color-danger-hover: #8c1b12;
  --color-on-accent: #ffffff;     /* text on accent and danger buttons */

  /* Tinted backgrounds of flash messages and the anonymity warning */
  --color-success-soft: #e7f4ec;
  --color-info-soft: #e8effc;
  --color-warning-soft: #fdf1dc;
  --color-danger-soft: #fbe9e7;

  --color-focus: var(--color-accent);
}
```

### Text contrast

Every text/background pair the components use, with its WCAG 2.x contrast
ratio. All are at least 4.5:1 (WCAG AA for normal text). If a token
changes, recompute its rows.

| Text | Background | Used for | Ratio |
|---|---|---|---|
| text `#1b1f24` | background `#ffffff` | body text | 16.56:1 |
| text `#1b1f24` | surface `#f4f5f7` | header, table header, project list item | 15.18:1 |
| muted `#525a66` | background `#ffffff` | help text, counts | 6.97:1 |
| muted `#525a66` | surface `#f4f5f7` | secondary text in the header or on cards | 6.39:1 |
| accent `#1d4ed8` | background `#ffffff` | links, secondary button text | 6.70:1 |
| accent `#1d4ed8` | surface `#f4f5f7` | links in the header and on cards, secondary button on hover | 6.14:1 |
| accent-hover `#1e3a8a` | background `#ffffff` | hovered link | 10.36:1 |
| accent-hover `#1e3a8a` | surface `#f4f5f7` | hovered link in the header | 9.50:1 |
| on-accent `#ffffff` | accent `#1d4ed8` | primary button | 6.70:1 |
| on-accent `#ffffff` | accent-hover `#1e3a8a` | primary button on hover | 10.36:1 |
| on-accent `#ffffff` | danger `#b42318` | danger button | 6.57:1 |
| on-accent `#ffffff` | danger-hover `#8c1b12` | danger button on hover | 9.21:1 |
| danger `#b42318` | background `#ffffff` | field error text | 6.57:1 |
| danger `#b42318` | surface `#f4f5f7` | field error text on a card | 6.03:1 |
| text `#1b1f24` | success-soft `#e7f4ec` | success message | 14.63:1 |
| text `#1b1f24` | info-soft `#e8effc` | info (and debug) message | 14.34:1 |
| text `#1b1f24` | warning-soft `#fdf1dc` | warning message, anonymity warning | 14.82:1 |
| text `#1b1f24` | danger-soft `#fbe9e7` | error message | 14.12:1 |
| accent `#1d4ed8` | success-soft `#e7f4ec` | link inside a success message | 5.92:1 |
| accent `#1d4ed8` | info-soft `#e8effc` | link inside an info message | 5.80:1 |
| accent `#1d4ed8` | warning-soft `#fdf1dc` | link inside a warning message or the anonymity warning | 6.00:1 |
| accent `#1d4ed8` | danger-soft `#fbe9e7` | link inside an error message | 5.72:1 |

Flash messages and the anonymity warning use `--color-text` for their text,
including the bold prefix; the status colour only appears in the left
border (see below).

### Non-text contrast

Non-text elements that carry meaning have at least 3:1 against the colour
next to them (WCAG 1.4.11).

| Element | Colour | Against | Ratio |
|---|---|---|---|
| Input, select and textarea border | border `#6b7280` | background `#ffffff` | 4.83:1 |
| Input border on a card | border `#6b7280` | surface `#f4f5f7` | 4.43:1 |
| Keyboard focus ring | focus `#1d4ed8` | background `#ffffff` | 6.70:1 |
| Keyboard focus ring | focus `#1d4ed8` | surface `#f4f5f7` | 6.14:1 |
| Keyboard focus ring inside a message | focus `#1d4ed8` | the tint with the lowest ratio (danger-soft `#fbe9e7`) | 5.72:1 |
| Success message left border | success `#15703a` | success-soft `#e7f4ec` | 5.44:1 |
| Info message left border | accent `#1d4ed8` | info-soft `#e8effc` | 5.80:1 |
| Warning message / anonymity warning left border | warning `#8a4b00` | warning-soft `#fdf1dc` | 6.09:1 |
| Error message left border | danger `#b42318` | danger-soft `#fbe9e7` | 5.61:1 |
| Chart line "My workload is manageable" | `#0072b2` | chart background `#ffffff` | 5.19:1 |
| Chart line "Our goals and priorities are clear" | `#c05000` | chart background `#ffffff` | 4.78:1 |
| Chart line "We work well together" | `#00805c` | chart background `#ffffff` | 4.95:1 |
| Chart line "I am confident we will deliver" | `#1b1f24` | chart background `#ffffff` | 16.56:1 |

The focus ring is drawn with `outline-offset: 2px`, so it sits on the page
or card background, never on the button colour itself. Radio buttons are
the browser's native control with `accent-color: var(--color-accent)`; they
are not redrawn in CSS.

### Typography

System fonts only; nothing is downloaded.

```css
:root {
  --font-sans: system-ui, -apple-system, "Segoe UI", Roboto,
    "Helvetica Neue", Arial, "Noto Sans", sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, Consolas,
    "Liberation Mono", monospace;

  --font-size-small: 0.875rem;  /* 14px: help text, table notes, counts */
  --font-size-body: 1rem;       /* 16px: body text, form controls, buttons */
  --font-size-h2: 1.375rem;     /* 22px */
  --font-size-h1: 1.75rem;      /* 28px */

  --line-height-body: 1.5;
  --line-height-heading: 1.25;
}
```

- One `<h1>` per page, the page title. `<h2>` for sections. No lower levels
  are needed in v1.
- Headings use weight 600, body text 400, the prefixes of messages and
  warnings 700 (`<strong>`).
- URLs shown as text (`.copy-link__url`) use `--font-mono`; everything
  else uses `--font-sans`.
- Sizes are in `rem`, so the page follows the user's browser font size.

### Spacing and width

```css
:root {
  --space-1: 0.25rem;  /*  4px */
  --space-2: 0.5rem;   /*  8px */
  --space-3: 0.75rem;  /* 12px */
  --space-4: 1rem;     /* 16px */
  --space-5: 1.5rem;   /* 24px */
  --space-6: 2rem;     /* 32px */
  --space-7: 3rem;     /* 48px */

  --content-max-width: 45rem;  /* 720px */
  --page-gutter: var(--space-4);
  --radius: 0.25rem;
}
```

- Margins, paddings and gaps use only these steps.
- Page content sits in `.container`: `max-width: var(--content-max-width)`,
  centred, with `--page-gutter` on the left and right.
- Vertical rhythm: `--space-4` between paragraphs and form fields,
  `--space-6` between sections.

## Layout and accessibility

These rules apply to every page.

- **320 px wide without horizontal scrolling.** Nothing has a fixed width
  larger than the viewport; long words and URLs wrap
  (`overflow-wrap: anywhere` on `body`, inherited by every text element,
  so a 100-character project name without spaces wraps too). The only thing allowed
  to scroll sideways is a data table, inside its own `.table-scroll`
  container.
- **Visible keyboard focus on every interactive element** (links, buttons,
  inputs, radio buttons, summary elements): `outline: 3px solid
  var(--color-focus); outline-offset: 2px` on `:focus-visible`. The outline
  is never removed without this replacement.
- **Every input has a `<label>`** whose `for` matches the input's `id`, or
  that wraps the input. Placeholders are never a replacement for a label.
- **Groups of radio buttons use `<fieldset>` and `<legend>`.**
- **Colour is never the only signal.** Flash messages and the anonymity
  warning start with a text prefix ("Success:", "Info:", "Warning:",
  "Error:", "Limited anonymity:"). Field errors are text. Chart lines also
  differ by point shape, and below-threshold weeks are hollow points plus a
  text note in the table.
- Tap targets (buttons, radio options) are at least 2.75rem (44 px) high.
- Every page has `<html lang="en">`, the viewport meta tag and one `<main>`.
- Tables have a `<caption>` (it may be visually hidden) and `<th scope>`.

## Wording

Fixed texts used by several tasks. Templates, models and scripts use them
exactly as written here.

### Dimensions

The four dimensions from `_docs/plan.md`, each phrased as a statement so
that **a higher rating is always better**. The same text is used as the
`verbose_name` in #4, as the `<legend>` in the form (#11), and as the chart
legend and table column heading (#14).

| Field (#4) | Dimension in `_docs/plan.md` | Wording |
|---|---|---|
| `workload` | workload/stress | My workload is manageable |
| `clarity` | clarity of goals and priorities | Our goals and priorities are clear |
| `collaboration` | collaboration/team atmosphere | We work well together |
| `progress` | progress/confidence in delivery | I am confident we will deliver |

End labels of the scale, the same for every scale (#3 allows 1–5, 0–10 and
anything up to 11 values):

- Lowest value: **Strongly disagree**
- Highest value: **Strongly agree**

The values in between have no words, only their number.

### Limited anonymity warning

Shown in two places: above the submit button on the respondent form (#11),
and for every week below the threshold on the trend page (#14). `{threshold}`
is replaced by the configured threshold (#3, default 5).

> **Limited anonymity:** fewer than {threshold} people have responded for
> this week, so individual answers may be recognisable.

The bold part is the prefix and is always shown. In the #14 table the same
sentence is used in the note cell of the week's row.

### Texts from other issues

These are set in their own issues and repeated here only so the components
below show them; they are not changed here.

- Copy button feedback (#10): "Copied" and "Copy failed – select the link
  and copy it manually"
- Empty dashboard (#10): "You have no projects yet."
- Empty trend page (#14): "No responses yet. Share the link with your team."
- Invalid invitation (#8): "This invitation link is not valid. Ask your
  administrator for a new one."
- Invalid reset link (#9): "This reset link is not valid. Ask your
  administrator for a new one."

## Components

Each component has a markup example and a rule for when to use it. The
examples show rendered HTML; `{% csrf_token %}` stands for Django's hidden
CSRF input.

### Header with navigation

Use on every page; it lives in `base.html` (#5). The app name always links
to `/`. The current page's link has `aria-current="page"`. Links for leads
are added in #7, #8, #9 and #10; logging out is a POST form, not a link.

```html
<header class="site-header">
  <div class="container site-header__inner">
    <a class="site-header__brand" href="/">Pulse Check</a>
    <nav class="site-nav" aria-label="Main">
      <ul class="site-nav__list">
        <li><a href="/projects/" aria-current="page">Projects</a></li>
        <li><a href="/invitations/">Invitations</a></li>
        <li><a href="/leads/">Leads</a></li>
        <li class="site-nav__user">anna</li>
        <li>
          <form class="inline-form" method="post" action="/logout/">
            {% csrf_token %}
            <button class="button button--secondary" type="submit">Log out</button>
          </form>
        </li>
      </ul>
    </nav>
  </div>
</header>
```

The header has the surface background and a bottom border. At narrow widths
`.site-nav__list` wraps below the brand; it never scrolls.

### Flash messages

Use for feedback after an action (Django's messages framework), never for
permanent page content and never on respondent pages (#11). All messages
appear in one region at the top of `<main>`, rendered by `base.html` (#5).

| Django level | Class | Prefix | `role` |
|---|---|---|---|
| `debug` | `message message--info` | Info: | `status` |
| `info` | `message message--info` | Info: | `status` |
| `success` | `message message--success` | Success: | `status` |
| `warning` | `message message--warning` | Warning: | `status` |
| `error` | `message message--error` | Error: | `alert` |

```html
<div class="messages">
  <div class="message message--success" role="status">
    <strong class="message__prefix">Success:</strong> Project Apollo created.
  </div>
  <div class="message message--info" role="status">
    <strong class="message__prefix">Info:</strong> You have been logged out.
  </div>
  <div class="message message--warning" role="status">
    <strong class="message__prefix">Warning:</strong> Something needs your attention.
  </div>
  <div class="message message--error" role="alert">
    <strong class="message__prefix">Error:</strong> Something went wrong.
  </div>
</div>
```

The `.messages` region is only rendered when there are messages. Each
message has its tinted background (`--color-*-soft`), text in
`--color-text`, and a 4px left border in its status colour.

### Buttons

Use `<button>` for actions and `<a>` for navigation; never style a link as
a button to do a POST. Every button has a `type`.

- **Primary** (`button button--primary`): the main action of a form or
  page, at most one per form ("Create project", "Submit").
- **Secondary** (`button button--secondary`): other actions ("Copy link",
  "Log out", "Create reset link").
- **Danger** (`button button--danger`): actions that delete data or break
  links ("Delete project", "Revoke", "Create new share link" on its
  confirmation page). A danger button that destroys data leads to a
  confirmation page first, unless the issue says otherwise (e.g. "Revoke" in
  #8 acts at once).

```html
<button class="button button--primary" type="submit">Create project</button>
<button class="button button--secondary" type="button">Copy link</button>
<a class="button button--danger" href="/projects/7/delete/">Delete project</a>
```

The last line is allowed because it only opens the confirmation page (GET).

**A button that submits a POST form** on its own, e.g. "Log out" (#7) or
"Revoke" (#8), is a small form with `.inline-form`, so it sits in a line of
text or a table cell:

```html
<form class="inline-form" method="post" action="/invitations/12/revoke/">
  {% csrf_token %}
  <button class="button button--danger" type="submit">Revoke</button>
</form>
```

Buttons of one form sit in `.form-actions`, primary first:

```html
<div class="form-actions">
  <button class="button button--primary" type="submit">Save</button>
  <a href="/projects/">Cancel</a>
</div>
```

### Form field

Use for every text, password and select input. The label comes first, then
the input, then help text, then the error. The input points to its help text
and error with `aria-describedby`; an invalid input has
`aria-invalid="true"`. Errors say what to do ("Enter a project name."), and
the field keeps the value the user typed.

Valid field with help text:

```html
<div class="field">
  <label class="field__label" for="id_name">Project name</label>
  <input class="field__input" type="text" id="id_name" name="name"
         maxlength="100" required aria-describedby="id_name_help">
  <p class="field__help" id="id_name_help">At most 100 characters.</p>
</div>
```

Invalid field:

```html
<div class="field field--invalid">
  <label class="field__label" for="id_name">Project name</label>
  <input class="field__input" type="text" id="id_name" name="name"
         maxlength="100" required aria-invalid="true"
         aria-describedby="id_name_help id_name_error">
  <p class="field__help" id="id_name_help">At most 100 characters.</p>
  <p class="field__error" id="id_name_error">Enter a project name.</p>
</div>
```

Errors that do not belong to one field (e.g. wrong login, #7) go above the
fields in `<div class="form-errors" role="alert">`, as a `<p>` per error.

### Rating row

Use for each dimension on the respondent form (#11). One `<fieldset>` per
dimension, the dimension wording as `<legend>`, one radio button per value
of the configured scale (#3), **no value preselected**. Above the options, a
line names both ends of the scale with their numbers; it is linked to the
fieldset with `aria-describedby`. The end-label words never change with the
scale; only the numbers in front of them do.

```html
<fieldset class="rating" aria-describedby="workload_ends">
  <legend class="rating__legend">My workload is manageable</legend>
  <p class="rating__ends" id="workload_ends">
    <span>1 = Strongly disagree</span>
    <span>5 = Strongly agree</span>
  </p>
  <div class="rating__options">
    <label class="rating__option"><input type="radio" name="workload" value="1" required> 1</label>
    <label class="rating__option"><input type="radio" name="workload" value="2"> 2</label>
    <label class="rating__option"><input type="radio" name="workload" value="3"> 3</label>
    <label class="rating__option"><input type="radio" name="workload" value="4"> 4</label>
    <label class="rating__option"><input type="radio" name="workload" value="5"> 5</label>
  </div>
</fieldset>
```

With an error (#11, missing dimension), the fieldset gets
`rating--invalid`, the error comes right after the legend, and the
fieldset's `aria-describedby` lists it:

```html
<fieldset class="rating rating--invalid" aria-describedby="workload_error workload_ends">
  <legend class="rating__legend">My workload is manageable</legend>
  <p class="field__error" id="workload_error">Choose a rating.</p>
  …
</fieldset>
```

Rules for every scale from 2 to 11 values (e.g. 1–5, 0–10):

- Each option is at least 2.75rem wide and high, with the number next to its
  radio button, and the whole option is the click target.
- `.rating__options` is a flex row with `flex-wrap: wrap` and a gap of
  `--space-2`. At 320 px (288 px of content), 5 options fit on one line; 11
  options wrap onto three lines. The row never scrolls sideways and
  the options never shrink below the minimum size.
- `.rating__ends` shows both end labels, left and right, and wraps onto two
  lines if needed. Because each end label carries its number, it stays
  correct when the options wrap.

### Limited anonymity warning

Use wherever results come from fewer people than the threshold: on the
respondent form (#11) above the submit button, and on the trend page (#14)
for each week below the threshold. The wording is fixed in
[Wording](#limited-anonymity-warning).

```html
<div class="anonymity-warning">
  <p>
    <strong class="anonymity-warning__prefix">Limited anonymity:</strong>
    fewer than 5 people have responded for this week, so individual answers
    may be recognisable.
  </p>
</div>
```

It uses the warning tint and left border, like `.message--warning`, but it
is page content, not a flash message, and has no `role`. In the #14 table the
same text sits in the note cell of the row, without the box:

```html
<td><span class="anonymity-note"><strong>Limited anonymity:</strong> fewer than 5 people have responded for this week, so individual answers may be recognisable.</span></td>
```

### Empty state

Use when a list or chart has nothing to show yet. One short sentence that
says what is missing and, where possible, what to do next; the next step
(form, share link) follows directly below.

```html
<div class="empty-state">
  <p>You have no projects yet.</p>
</div>
```

```html
<div class="empty-state">
  <p>No responses yet. Share the link with your team.</p>
  <!-- copy-link component follows -->
</div>
```

### Project list

Use on the dashboard (#10). A list, newest project first. Each item has the
name as a link to the trend page, this week's count and the share link
with its copy button.

```html
<ul class="project-list">
  <li class="project-list__item">
    <h2 class="project-list__name"><a href="/projects/7/">Apollo</a></h2>
    <p class="project-list__count">3 responses this week</p>
    <div class="copy-link">…</div>
  </li>
</ul>
```

The count reads "No responses yet this week", "1 response this week" or "N
responses this week" (#10). Items have the surface background, a border and
`--space-4` padding.

### Copy-link button

Use wherever a link has to be handed to someone: share links (#10, #14,
#22), invitation links (#8) and reset links (#9). The link is always shown
as selectable text next to the button, so it can be copied by hand when
JavaScript or the clipboard is not available. The button is added by the
static script (`pulse/static/pulse/js/copy-link.js`, #10), which writes one
of the two feedback texts into the `aria-live` region.

```html
<div class="copy-link">
  <code class="copy-link__url" id="share-link-7">https://pulse.example.org/p/Xy3…/</code>
  <button class="button button--secondary" type="button"
          data-copy-target="share-link-7">Copy link</button>
  <span class="copy-link__feedback" aria-live="polite"></span>
</div>
```

Feedback texts, written into `.copy-link__feedback`:

- On success: **Copied**
- When the browser blocks the clipboard (e.g. plain HTTP): **Copy failed –
  select the link and copy it manually**

`.copy-link__url` has `user-select: all` and wraps anywhere, so a long link
never makes the page scroll sideways.

### Data table

Use for tabular data such as the weekly figures under the chart (#14) and
the invitation and lead lists (#8, #9). The table is always wrapped in
`.table-scroll`, which scrolls sideways inside itself at 320 px so the page
does not. The wrapper is focusable and labelled, so keyboard users can
scroll it.

```html
<div class="table-scroll" tabindex="0" role="region" aria-labelledby="weeks-caption">
  <table class="data-table">
    <caption id="weeks-caption" class="visually-hidden">Weekly results</caption>
    <thead>
      <tr>
        <th scope="col">Week</th>
        <th scope="col" class="data-table__number">Responses</th>
        <th scope="col" class="data-table__number">My workload is manageable</th>
        <th scope="col" class="data-table__number">Our goals and priorities are clear</th>
        <th scope="col" class="data-table__number">We work well together</th>
        <th scope="col" class="data-table__number">I am confident we will deliver</th>
        <th scope="col">Note</th>
      </tr>
    </thead>
    <tbody>
      <tr>
        <th scope="row">2026-W40</th>
        <td class="data-table__number">3</td>
        <td class="data-table__number">3.7</td>
        <td class="data-table__number">4.0</td>
        <td class="data-table__number">4.3</td>
        <td class="data-table__number">3.3</td>
        <td><span class="anonymity-note">…</span></td>
      </tr>
    </tbody>
  </table>
</div>
```

Numbers are right-aligned (`.data-table__number`) with tabular figures. The
header row has the surface background.

### Confirmation page for destructive actions

Use before an action that cannot be undone or breaks existing links:
deleting a project (#15) and creating a new share link (#22). The page has
a heading naming the action, the consequence in plain words, an optional
"type the name to confirm" field, a danger button and a cancel link back to
where the user came from. The GET shows the page and changes nothing; only
the POST acts.

```html
<h1>Delete project</h1>
<form class="confirm" method="post" action="/projects/7/delete/">
  {% csrf_token %}
  <p class="confirm__consequence">This permanently deletes Apollo and all 42 responses. This cannot be undone.</p>
  <div class="field">
    <label class="field__label" for="id_confirm_name">Type the project name to confirm</label>
    <input class="field__input" type="text" id="id_confirm_name" name="confirm_name"
           autocomplete="off" required>
  </div>
  <div class="form-actions">
    <button class="button button--danger" type="submit">Delete project</button>
    <a href="/projects/7/">Cancel</a>
  </div>
</form>
```

For #22, which has no name field, the field is left out. A wrong name shows
a field error as in [Form field](#form-field).

### Error page

Use for 404 and for every "link not valid" case (#8, #9, #11, #14). A
heading and one sentence, nothing else: no project names, no user names,
no hint about *why* the link is invalid.

```html
<div class="error-page">
  <h1>Page not found</h1>
  <p>This page does not exist.</p>
</div>
```

```html
<div class="error-page">
  <h1>Link not valid</h1>
  <p>This invitation link is not valid. Ask your administrator for a new one.</p>
</div>
```

## Chart (#14)

The trend chart is drawn by Chart.js 4 (bundled in #5) from a static
script. It has one line per dimension, a legend with the point shapes
(`plugins.legend.labels.usePointStyle: true`) and the chart background
`--color-background` (`#ffffff`).

| Dimension | Colour | `pointStyle` |
|---|---|---|
| My workload is manageable | `#0072b2` (blue) | `circle` |
| Our goals and priorities are clear | `#c05000` (dark orange) | `rect` |
| We work well together | `#00805c` (bluish green) | `triangle` |
| I am confident we will deliver | `#1b1f24` (near black) | `rectRot` |

The colours are also defined in `site.css` as `--chart-1` … `--chart-4`, in
this order; the chart script may read them with `getComputedStyle` or use
the hex values above. Axis labels and ticks use `--color-text-muted`; grid
lines are decorative and may be lighter.

- Lines are 2px wide, points have radius 4 (6 on hover), so a single week
  of data is visible as points (#14).
- The y-axis runs from the scale minimum to the scale maximum (#3), with
  integer ticks.
- **Weeks without responses are a gap.** Their value is `null` and
  `spanGaps` is `false`, so the line breaks there; it does not drop to 0 and
  does not join the neighbouring weeks.
- **Weeks below the anonymity threshold are hollow points:** the point
  keeps its shape and border colour, but its fill
  (`pointBackgroundColor`) is the chart background `#ffffff`; weeks at or
  above the threshold are filled with the line colour. The tooltip of such
  a week adds the line "Limited anonymity", and the table below the chart
  carries the full warning, so the marking does not rely on colour.
- Week labels read `2026-W40`; the tooltip shows the date range and the
  number of responses (#14).

### Colour-blindness check

The four colours were checked with a deuteranopia and a protanopia
simulator (Machado, Oliveira and Fernandes 2009, severity 1.0, applied to
linear RGB). The table gives the smallest colour difference (CIE ΔE76)
between any two of the four lines; values above about 20 are clearly
distinguishable.

| Vision | Smallest ΔE between two lines | Pair |
|---|---|---|
| Normal | 51 | blue / near black |
| Deuteranopia | 36 | bluish green / near black |
| Protanopia | 33 | dark orange / bluish green |

Even where two colours come close, the point shapes differ.

## Class index

The complete list of classes. #5 implements all of them in `site.css`;
templates use no others.

| Class | Component |
|---|---|
| `container` | Centred content column with max width and gutters |
| `site-header`, `site-header__inner`, `site-header__brand` | Header |
| `site-nav`, `site-nav__list`, `site-nav__user` | Header navigation |
| `messages`, `message`, `message--success`, `message--info`, `message--warning`, `message--error`, `message__prefix` | Flash messages |
| `button`, `button--primary`, `button--secondary`, `button--danger` | Buttons |
| `inline-form` | A form that is only a button (Log out, Revoke) |
| `form-actions` | Row of buttons at the end of a form |
| `form-errors` | Errors that belong to the whole form |
| `field`, `field--invalid`, `field__label`, `field__input`, `field__help`, `field__error` | Form field |
| `rating`, `rating--invalid`, `rating__legend`, `rating__ends`, `rating__options`, `rating__option` | Rating row |
| `anonymity-warning`, `anonymity-warning__prefix`, `anonymity-note` | Limited anonymity warning |
| `empty-state` | Empty state |
| `project-list`, `project-list__item`, `project-list__name`, `project-list__count` | Project list |
| `copy-link`, `copy-link__url`, `copy-link__feedback` | Copy-link button |
| `table-scroll`, `data-table`, `data-table__number` | Data table |
| `confirm`, `confirm__consequence` | Confirmation page |
| `error-page` | Error page |
| `visually-hidden` | Text for screen readers only (e.g. a table caption) |
