from .. import state as state_module
from ..state import STATE_LOCK
from ..ui.template import HtmlDocument, esc, format_amount, label_for, minor_to_decimal, page_shell
from .auth_pages import signed_out_login_content
from .page_common import user_from_cookie
from .authorizations import authorization_json
from ..state import effective_status, remaining_amount


def authorizations_page(headers, params=None):
    user = user_from_cookie(headers)
    with STATE_LOCK:
        state = state_module.STATE
        if user is None:
            return HtmlDocument(page_shell(
                "Authorizations", "authorizations", state.minor_units, state.currency,
                None, signed_out_login_content()))
        now = state_module.now_dt()
        held = state_module.held(state, user.id, now)
        balance = state.users[user.id].balance
        minor_units = state.minor_units
        currency = state.currency
        items = [a for a in state.authorizations.values()
                 if a.from_user_id == user.id or a.to_user_id == user.id]
        items.sort(key=lambda a: (a.created_dt, a.seq), reverse=True)
        items_html = "".join(authorization_item_html(state, a, user, now, minor_units, currency)
                             for a in items)
        any_items = bool(items)
    content = (
        _wallet_card(balance, held, minor_units, currency)
        + _authorize_card()
        + '<section class="card">'
        "<h2>Your holds</h2>"
        '<p class="card__hint">Money you have reserved for others, or that is '
        "reserved for you.</p>"
        f'<ul class="list" data-testid="authorization-list" id="authorization-list" '
        f'aria-live="polite"{" hidden" if not any_items else ""}>{items_html}</ul>'
        f'<p class="empty" data-testid="empty-authorizations"{"" if not any_items else " hidden"}>'
        "No authorizations yet. Authorize money above to reserve it for someone.</p>"
        "</section>"
    )
    return HtmlDocument(page_shell(
        "Authorizations", "authorizations", minor_units, currency, user, content))


def _wallet_card(balance, held, minor_units, currency):
    from .wallet_page import _wallet_card as wallet_card

    return wallet_card(balance, held, minor_units, currency)


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


def authorization_item_html(state, auth, user, now, minor_units, currency):
    data = authorization_json(state, auth, now)
    aid = data["authorization_id"]
    is_outgoing = data["from_user_id"] == user.id
    title = ("You authorized money for " + esc(data["to_handle"]) if is_outgoing
             else esc(data["from_handle"]) + " authorized money for you")
    note_html = (f'<div class="note">{esc(data["note"])}</div>' if data["note"] else "")
    side = [f'<span class="pill pill--{esc(data["status"])}">{esc(data["status"])}</span>',
            f'<span class="amount amount--item" data-testid="authorization-amount-{esc(aid)}">'
            f'{esc(format_amount(data["amount"], currency, minor_units))}</span>']
    if data["status"] == "captured":
        side.append(f'<span class="amount amount--item amount--total" '
                    f'data-testid="authorization-captured-{esc(aid)}">'
                    f'{esc(format_amount(data["captured_amount"], currency, minor_units))} '
                    f"captured</span>")
    controls = ""
    if data["status"] == "open" and not is_outgoing:
        remaining = data["remaining_amount"]
        controls = (
            '<div class="capture-controls"><div class="field">'
            f'<label class="field__label" for="capture-{esc(aid)}">Capture amount</label>'
            f'<input id="capture-{esc(aid)}" type="text" inputmode="decimal" '
            f'value="{esc(minor_to_decimal(remaining, minor_units))}" '
            f'data-testid="authorization-capture-amount-{esc(aid)}">'
            '<button type="button" class="btn btn--good btn--small" '
            f'data-testid="authorization-capture-{esc(aid)}">Capture</button>'
            "</div></div>"
        )
    if data["status"] == "open" and is_outgoing:
        controls = ('<button type="button" class="btn btn--ghost btn--small" '
                    f'data-testid="authorization-void-{esc(aid)}">Release hold</button>')
    if controls:
        side.append(controls)
    return (
        '<li class="list__item" '
        f'data-testid="authorization-item-{esc(aid)}" data-status="{esc(data["status"])}">'
        f'<div class="list__main"><div class="list__title">{title}</div>'
        f"{note_html}"
        '<div class="list__meta">Expires '
        f'<span class="expiry" data-testid="authorization-expires-{esc(aid)}">'
        f'{esc(data["expires_at"])}</span></div></div>'
        f'<div class="list__side">{"".join(side)}</div>'
        "</li>"
    )