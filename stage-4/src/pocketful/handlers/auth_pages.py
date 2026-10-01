from .. import state as state_module
from ..ui.template import HtmlDocument, esc, label_for, page_shell
from .page_common import user_from_cookie


def _auth_card(mode, hint):
    if mode == "signup":
        heading = "Create your Pocketful account"
        fields = (
            f'<div class="field">{label_for("signup-email", "Email")}'
            '<input id="signup-email" data-testid="signup-email" type="email" '
            'autocomplete="email"></div>'
            f'<div class="field">{label_for("signup-password", "Password (at least 8 characters)")}'
            '<input id="signup-password" data-testid="signup-password" type="password" '
            'autocomplete="new-password"></div>'
            f'<div class="field">{label_for("signup-display-name", "Display name")}'
            '<input id="signup-display-name" data-testid="signup-display-name" '
            'type="text" autocomplete="name"></div>'
            '<div class="form__actions"><button type="submit" class="btn btn--primary" '
            'data-testid="signup-submit">Create account</button></div>'
        )
        switch = '<p class="card__hint">Already have an account? <a href="/login">Log in</a>.</p>'
        endpoint = "/auth/signup"
    else:
        heading = "Log in to Pocketful"
        fields = (
            f'<div class="field">{label_for("login-email", "Email")}'
            '<input id="login-email" data-testid="login-email" type="email" '
            'autocomplete="email"></div>'
            f'<div class="field">{label_for("login-password", "Password")}'
            '<input id="login-password" data-testid="login-password" type="password" '
            'autocomplete="current-password"></div>'
            '<div class="form__actions"><button type="submit" class="btn btn--primary" '
            'data-testid="login-submit">Log in</button></div>'
        )
        switch = '<p class="card__hint">New to Pocketful? <a href="/signup">Sign up</a>.</p>'
        endpoint = "/auth/login"
    return (
        '<section class="card" data-page="auth">'
        f"<h2>{esc(heading)}</h2>"
        f'<p class="card__hint">{esc(hint)}</p>'
        f'<form id="auth-form" data-endpoint="{endpoint}" novalidate>'
        f"{fields}"
        "</form>"
        f"{switch}"
        "</section>"
    )


def _signed_in_note(user):
    return (
        '<section class="card">'
        f"<h2>Welcome, {esc(user.display_name)}</h2>"
        '<p class="card__hint">You are already signed in.</p>'
        '<p><a class="btn btn--primary" href="/">Go to your wallet</a></p>'
        "</section>"
    )


def signup_page(headers, params=None):
    user = user_from_cookie(headers)
    content = _auth_card(
        "signup", "Enter your details to open your wallet.")
    if user is not None:
        content += _signed_in_note(user)
    return HtmlDocument(page_shell(
        "Sign up", "signup", state_module.STATE.minor_units, state_module.STATE.currency,
        user, content))


def login_page(headers, params=None):
    user = user_from_cookie(headers)
    content = _auth_card("login", "Welcome back. Enter your details to continue.")
    if user is not None:
        content += _signed_in_note(user)
    return HtmlDocument(page_shell(
        "Log in", "login", state_module.STATE.minor_units, state_module.STATE.currency,
        user, content))


def signed_out_login_content():
    return _auth_card("login", "Log in to see your balance and move money.")