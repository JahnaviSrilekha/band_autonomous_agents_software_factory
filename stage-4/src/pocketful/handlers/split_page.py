from .. import state as state_module
from ..ui.template import HtmlDocument, esc, label_for, page_shell
from .auth_pages import signed_out_login_content
from .page_common import user_from_cookie


def split_page(headers, params=None):
    user = user_from_cookie(headers)
    state = state_module.STATE
    if user is None:
        return HtmlDocument(page_shell(
            "Split", "split", state.minor_units, state.currency, None,
            signed_out_login_content()))
    content = (
        '<section class="card" data-page="split">'
        "<h2>Split a bill</h2>"
        '<p class="card__hint">Pocketful divides the amount exactly, with any odd '
        "cents going to the first people listed.</p>"
        '<form id="split-form" novalidate>'
        f'<div class="field">{label_for("split-handles", "Handles to split between (comma separated, in order)")}'
        '<input id="split-handles" data-testid="split-handles" type="text" '
        'autocomplete="off" placeholder="e.g. ada, bob, carol"></div>'
        f'<div class="field">{label_for("split-amount", "Total amount")}'
        '<input id="split-amount" data-testid="split-amount" type="text" '
        'inputmode="decimal" placeholder="30.00"></div>'
        f'<div class="field">{label_for("split-note", "Note (optional)")}'
        '<input id="split-note" data-testid="split-note" type="text" maxlength="200"></div>'
        '<div id="split-preview-slot" data-testid="split-preview" hidden>'
        '<div class="preview"><div class="preview__title">Preview — everyone\u2019s share</div>'
        '<div id="split-preview-rows"></div></div></div>'
        '<div class="form__actions"><button type="submit" class="btn btn--primary" '
        'data-testid="split-submit">Create the split</button></div>'
        "</form>"
        "</section>"
    )
    return HtmlDocument(page_shell(
        "Split", "split", state.minor_units, state.currency, user, content))