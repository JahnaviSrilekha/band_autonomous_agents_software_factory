from .. import state as state_module
from ..state import STATE_LOCK
from ..ui.template import HtmlDocument, esc, format_amount, format_when, page_shell
from .auth_pages import signed_out_login_content
from .page_common import user_from_cookie
from .requests import request_json


def requests_page(headers, params=None):
    user = user_from_cookie(headers)
    with STATE_LOCK:
        state = state_module.STATE
        if user is None:
            return HtmlDocument(page_shell(
                "Requests", "requests", state.minor_units, state.currency, None,
                signed_out_login_content()))
        minor_units = state.minor_units
        currency = state.currency
        items = [r for r in state.requests.values()
                 if r.requester_id == user.id or r.payer_id == user.id]
        items.sort(key=lambda r: (r.created_at, r.seq), reverse=True)
        incoming = [r for r in items if r.payer_id == user.id]
        outgoing = [r for r in items if r.requester_id == user.id]
        incoming_html = "".join(request_item_html(state, r, user, minor_units, currency)
                                for r in incoming)
        outgoing_html = "".join(request_item_html(state, r, user, minor_units, currency)
                                for r in outgoing)
        any_items = bool(items)
    content = (
        '<section class="card" data-page="requests">'
        "<h2>Requests</h2>"
        '<p class="card__hint">Requests you owe and requests waiting on others.</p>'
        "<h2>Incoming</h2>"
        f'<ul class="list" data-testid="incoming-list" id="incoming-list" '
        f'aria-live="polite"{" hidden" if not incoming else ""}>{incoming_html}</ul>'
        "<h2>Outgoing</h2>"
        f'<ul class="list" data-testid="outgoing-list" id="outgoing-list" '
        f'aria-live="polite"{" hidden" if not outgoing else ""}>{outgoing_html}</ul>'
        f'<p class="empty" data-testid="empty-requests"{"" if not any_items else " hidden"}>'
        "No requests yet. Create one from your wallet with the request form.</p>"
        "</section>"
    )
    return HtmlDocument(page_shell(
        "Requests", "requests", minor_units, currency, user, content))


def request_item_html(state, request, user, minor_units, currency):
    data = request_json(state, request)
    rid = data["request_id"]
    is_incoming = data["payer_id"] == user.id
    title = (f'{esc(data["requester_handle"])} asked you for' if is_incoming
             else f'You asked {esc(data["payer_handle"])}')
    note_html = (f'<div class="note">{esc(data["note"])}</div>' if data["note"] else "")
    side = [f'<span class="pill pill--{esc(data["status"])}">{esc(data["status"])}</span>',
            f'<span class="amount amount--item" data-testid="request-amount-{esc(rid)}">'
            f'{esc(format_amount(data["amount"], currency, minor_units))}</span>']
    if data["status"] == "pending" and is_incoming:
        side.append('<button type="button" class="btn btn--good btn--small" '
                    f'data-testid="request-pay-{esc(rid)}">Pay</button>')
        side.append('<button type="button" class="btn btn--danger btn--small" '
                    f'data-testid="request-decline-{esc(rid)}">Decline</button>')
    if data["status"] == "pending" and not is_incoming:
        side.append('<button type="button" class="btn btn--ghost btn--small" '
                    f'data-testid="request-cancel-{esc(rid)}">Cancel</button>')
    return (
        '<li class="list__item" '
        f'data-testid="request-item-{esc(rid)}" data-status="{esc(data["status"])}">'
        f'<div class="list__main"><div class="list__title">{title}</div>'
        f"{note_html}"
        f'<div class="list__meta">{esc(format_when(data["created_at"]))}</div></div>'
        f'<div class="list__side">{"".join(side)}</div>'
        "</li>"
    )