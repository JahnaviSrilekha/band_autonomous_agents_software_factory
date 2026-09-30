from .. import state as state_module
from ..state import STATE_LOCK
from ..ui.template import HtmlDocument, esc, label_for, page_shell
from .auth_pages import signed_out_login_content
from .page_common import user_from_cookie
from .wallet_page import _wallet_card


def authorizations_page(headers, params=None):
    user = user_from_cookie(headers)
    with STATE_LOCK:
        state = state_module.STATE
        if user is None:
            return HtmlDocument(page_shell(
                "Authorizations", "authorizations", state.minor_units, state.currency,
                None, signed_out_login_content()))
        held = state_module.held(state, user.id, state_module.now_dt())
        balance = state.users[user.id].balance
        minor_units = state.minor_units
        currency = state.currency
    content = (
        _wallet_card(balance, held, minor_units, currency)
        + _authorize_card()
        + '<section class="card">'
        "<h2>Your holds</h2>"
        '<p class="card__hint">Money you have reserved for others, or that is '
        "reserved for you.</p>"
        '<ul class="list" data-testid="authorization-list" id="authorization-list" '
        'aria-live="polite"><li class="loading">Loading authorizations…</li></ul>'
        '<p class="empty" data-testid="empty-authorizations" hidden>'
        "No authorizations yet. Authorize money above to reserve it for someone.</p>"
        "</section>"
    )
    return HtmlDocument(page_shell(
        "Authorizations", "authorizations", minor_units, currency, user, content))


def _authorize_card():
    return (
        '<section class="card">'
        "<h2>Authorize money</h2>"
        '<p class="card__hint">The amount is held from your available balance and '
        "only moves when the recipient captures it.</p>"
        '<form id="authorize-form" novalidate>'
        f'<div class="field">{label_for("authorize-handle", "Recipient handle")}'
        '<input id="authorize-handle" data-testid="authorize-handle" type="text" '
        'autocomplete="off" placeholder="e.g. bob"></div>'
        f'<div class="field">{label_for("authorize-amount", "Amount to hold")}'
        '<input id="authorize-amount" data-testid="authorize-amount" type="text" '
        'inputmode="decimal" placeholder="15.00"></div>'
        f'<div class="field">{label_for("authorize-note", "Note (optional)")}'
        '<input id="authorize-note" data-testid="authorize-note" type="text" maxlength="200"></div>'
        f'<div class="field">{label_for("authorize-visibility", "Visibility")}'
        '<select id="authorize-visibility" data-testid="authorize-visibility">'
        '<option value="public">Public</option>'
        '<option value="private">Private</option>'
        "</select></div>"
        '<div class="form__actions"><button type="submit" class="btn btn--primary" '
        'data-testid="authorize-submit">Authorize</button></div>'
        "</form>"
        "</section>"
    )