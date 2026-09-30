import html
from datetime import datetime, timezone


def esc(value):
    return html.escape(str(value), quote=True)


def format_amount(minor, currency, minor_units):
    minor = int(minor)
    sign = "-" if minor < 0 else ""
    value = abs(minor)
    if minor_units <= 0:
        return f"{sign}{value} {currency}"
    digits = str(value).rjust(minor_units + 1, "0")
    whole, frac = digits[:-minor_units], digits[-minor_units:]
    return f"{sign}{whole}.{frac} {currency}"


def format_when(iso_text):
    try:
        moment = datetime.fromisoformat(iso_text.replace("Z", "+00:00"))
        return moment.strftime("%b %d, %Y %H:%M")
    except (ValueError, TypeError):
        return iso_text or ""


def minor_to_decimal(minor, minor_units):
    minor = int(minor)
    value = abs(minor)
    if minor_units <= 0:
        return str(value)
    digits = str(value).rjust(minor_units + 1, "0")
    return f"{digits[:-minor_units]}.{digits[-minor_units:]}"


class HtmlDocument:
    def __init__(self, html_text, status=200):
        self.status = status
        self.html_text = html_text


class StaticFile:
    def __init__(self, data, content_type):
        self.status = 200
        self.data = data
        self.content_type = content_type


NAV_ITEMS = (
    ("/", "home", "Home"),
    ("/requests", "requests", "Requests"),
    ("/split", "split", "Split"),
    ("/authorizations", "authorizations", "Authorizations"),
)


def page_shell(title, active, minor_units, currency, user, content_html):
    nav_links = "".join(
        f'<a class="nav__link{" nav__link--active" if key == active else ""}" '
        f'href="{href}">{esc(label)}</a>'
        for href, key, label in NAV_ITEMS
    )
    if user is not None:
        auth_area = (
            '<div class="authbox">'
            f'<span class="authbox__name" data-testid="current-user">{esc(user.display_name)}</span>'
            f'<span class="authbox__handle" data-testid="current-handle">{esc(user.handle)}</span>'
            '<button type="button" class="btn btn--ghost btn--small" '
            'data-testid="logout-button">Log out</button>'
            "</div>"
        )
    else:
        auth_area = (
            '<div class="authbox">'
            '<a class="nav__link" href="/signup">Sign up</a>'
            '<a class="nav__link" href="/login">Log in</a>'
            "</div>"
        )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(title)} — Pocketful</title>
<link rel="stylesheet" href="/static/styles.css">
<script src="/static/app.js" defer></script>
</head>
<body data-minor-units="{int(minor_units)}" data-currency="{esc(currency)}">
<a class="skip-link" href="#main">Skip to content</a>
<header class="topbar">
  <a class="brand" href="/"><span class="brand__mark" aria-hidden="true">◍</span>Pocketful</a>
  {auth_area}
</header>
<nav class="nav" aria-label="Primary">{nav_links}</nav>
<main class="main" id="main">
{content_html}
</main>
<footer class="footer">Pocketful — calm money for everyday people.</footer>
</body>
</html>"""


def amount_span(testid, minor, currency, minor_units, css_class="", extra_attrs=""):
    return (f'<span class="amount {css_class}" data-testid="{testid}" '
            f'data-amount="{int(minor)}"{extra_attrs}>'
            f"{esc(format_amount(minor, currency, minor_units))}</span>")


def label_for(for_id, text):
    return f'<label class="field__label" for="{for_id}">{esc(text)}</label>'