from .. import state as state_module


def user_from_cookie(headers):
    cookie_header = headers.get("Cookie")
    if not cookie_header:
        return None
    token = None
    for part in cookie_header.split(";"):
        name, _, value = part.strip().partition("=")
        if name == "pocketful_token":
            token = value
            break
    if not token:
        return None
    with state_module.STATE_LOCK:
        user_id = state_module.STATE.tokens.get(token)
        user = state_module.STATE.users.get(user_id) if user_id is not None else None
    return user


def static_file(name):
    import os

    if name not in ("app.js", "styles.css"):
        raise KeyError(name)
    content_types = {"app.js": "text/javascript; charset=utf-8",
                     "styles.css": "text/css; charset=utf-8"}
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "ui", "static", name)
    with open(path, "rb") as fh:
        data = fh.read()
    from ..ui.template import StaticFile

    return StaticFile(data, content_types[name])