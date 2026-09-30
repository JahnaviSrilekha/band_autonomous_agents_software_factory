from .. import state as state_module
from ..state import STATE_LOCK
from ..ui.template import HtmlDocument, esc, format_amount, label_for, page_shell
from .auth_pages import signed_out_login_content
from .page_common import user_from_cookie


def wallet_page(headers, params=None):
    user = user_from_cookie(headers)
    with STATE_LOCK:
        state = state_module.STATE
        if user is None:
            return HtmlDocument(page_shell(
                "Wallet", "home", state.minor_units, state.currency, None,
                signed_out_login_content()))
        me_held = state_module.held(state, user.id, state_module.now_dt())
        me = state.users[user.id]
        balance = me.balance
        minor_units = state.minor_units
        currency = state.currency
    content = (
        _wallet_card(balance, me_held, minor_units, currency)
        + '<div class="grid-2">'
        + _pay_card(minor_units)
        + _request_card(minor_units)
        + "</div>"
        + _activity_card()
    )
    return HtmlDocument(page_shell("Wallet", "home", minor_units, currency, user, content))


def _wallet_card(balance, held, minor_units, currency):
    held_cell = ""
    if held > 0:
        held_cell = (
            '<span class="wallet__cell">'
            '<span class="wallet__label">Held</span>'
            f'<span class="amount amount--held" data-testid="wallet-held" '
            f'data-amount="{int(held)}">{esc(format_amount(held, currency, minor_units))}</span>'
            "</span>"
        )
    return (
        '<section class="card wallet" data-page="wallet">'
        "<h2>Your money</h2>"
        '<p class="card__hint">Available is what you can spend right now.</p>'
        '<div class="wallet__available">'
        '<span class="wallet__label">Available</span>'
        f'<span class="amount amount--available" data-testid="wallet-available" '
        f'data-amount="{int(balance - held)}">'
        f"{esc(format_amount(balance - held, currency, minor_units))}</span>"
        "</div>"
        '<div class="wallet__secondary">'
        '<span class="wallet__cell">'
        '<span class="wallet__label">Total balance</span>'
        f'<span class="amount amount--total" data-testid="wallet-balance" '
        f'data-amount="{int(balance)}">{esc(format_amount(balance, currency, minor_units))}</span>'
        "</span>"
        + held_cell +
        "</div>"
        '<div class="form__actions" style="margin-top:14px">'
        '<button type="button" class="btn btn--ghost" data-testid="wallet-refresh">'
        "Refresh</button>"
        "</div>"
        "</section>"
    )


def _pay_card(minor_units):
    hint = ("Money moves instantly. Retries are always safe."
            if minor_units == 2 else
            f"Money moves instantly. This currency uses {minor_units} decimal places.")
    return (
        '<section class="card">'
        "<h2>Pay someone</h2>"
        f'<p class="card__hint">{esc(hint)}</p>'
        '<form id="pay-form" novalidate>'
        f'<div class="field">{label_for("pay-handle", "Recipient handle")}'
        '<input id="pay-handle" data-testid="pay-handle" type="text" '
        'autocomplete="off" placeholder="e.g. bob"></div>'
        f'<div class="field">{label_for("pay-amount", "Amount")}'
        '<input id="pay-amount" data-testid="pay-amount" type="text" '
        'inputmode="decimal" placeholder="15.00"></div>'
        f'<div class="field">{label_for("pay-note", "Note (optional)")}'
        '<input id="pay-note" data-testid="pay-note" type="text" maxlength="200"></div>'
        f'<div class="field">{label_for("pay-visibility", "Visibility")}'
        '<select id="pay-visibility" data-testid="pay-visibility">'
        '<option value="public">Public</option>'
        '<option value="private">Private</option>'
        "</select></div>"
        '<div class="form__actions"><button type="submit" class="btn btn--primary" '
        'data-testid="pay-submit">Send payment</button></div>'
        "</form>"
        "</section>"
    )


def _request_card(minor_units):
    return (
        '<section class="card">'
        "<h2>Request money</h2>"
        '<p class="card__hint">Ask someone to pay you. They can pay or decline.</p>'
        '<form id="request-form" novalidate>'
        f'<div class="field">{label_for("request-handle", "From handle")}'
        '<input id="request-handle" data-testid="request-handle" type="text" '
        'autocomplete="off" placeholder="e.g. bob"></div>'
        f'<div class="field">{label_for("request-amount", "Amount")}'
        '<input id="request-amount" data-testid="request-amount" type="text" '
        'inputmode="decimal" placeholder="15.00"></div>'
        f'<div class="field">{label_for("request-note", "Note (optional)")}'
        '<input id="request-note" data-testid="request-note" type="text" maxlength="200"></div>'
        '<div class="form__actions"><button type="submit" class="btn btn--primary" '
        'data-testid="request-submit">Create request</button></div>'
        "</form>"
        "</section>"
    )


def _activity_card():
    return (
        '<section class="card">'
        "<h2>Activity</h2>"
        '<p class="card__hint">Payments you made, received or can see, newest first.</p>'
        '<ul class="list" data-testid="activity-list" id="activity-list" '
        'aria-live="polite"><li class="loading">Loading your activity…</li></ul>'
        '<p class="empty" data-testid="empty-activity" hidden>'
        "No payments to show yet. Send a payment or receive one to see it here.</p>"
        "</section>"
    )