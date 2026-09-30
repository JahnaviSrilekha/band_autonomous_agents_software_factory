from .. import state as state_module
from ..ui.template import HtmlDocument, esc, page_shell
from .auth_pages import signed_out_login_content
from .page_common import user_from_cookie


def requests_page(headers, params=None):
    user = user_from_cookie(headers)
    state = state_module.STATE
    if user is None:
        return HtmlDocument(page_shell(
            "Requests", "requests", state.minor_units, state.currency, None,
            signed_out_login_content()))
    content = (
        '<section class="card" data-page="requests">'
        "<h2>Requests</h2>"
        '<p class="card__hint">Requests you owe and requests waiting on others.</p>'
        "<h3>Incoming</h2></h3>".replace("</h2></h3>", "</h2>")
        + '<ul class="list" data-testid="incoming-list" id="incoming-list" '
        'aria-live="polite"><li class="loading">Loading incoming requests…</li></ul>'
        "<h2>Outgoing</h2>"
        '<ul class="list" data-testid="outgoing-list" id="outgoing-list" '
        'aria-live="polite"><li class="loading">Loading outgoing requests…</li></ul>'
        '<p class="empty" data-testid="empty-requests" hidden>'
        "No requests yet. Create one from your wallet with the request form.</p>"
        "</section>"
    )
    return HtmlDocument(page_shell(
        "Requests", "requests", state.minor_units, state.currency, user, content))