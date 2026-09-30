"""Minimal DOM helper for UI acceptance checks (R96: HTTP + DOM assertions
against data-testid attributes; stdlib html.parser only — no JS execution).

An Element carries tag, attributes, its concatenated text, its parent, and its
document order. Lookup helpers are by data-testid or testid prefix.
"""
from html.parser import HTMLParser

VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr"}


class Element:
    def __init__(self, tag, attrs, parent):
        self.tag = tag
        self.attrs = dict(attrs)
        self.parent = parent
        self.children = []
        self._text_parts = []
        self.order = 0

    def text(self):
        """Concatenated descendant text, outer whitespace stripped, internal
        whitespace runs collapsed to single spaces (R103 'text is exactly')."""
        parts = []

        def walk(el):
            for ch in el.children:
                if isinstance(ch, str):
                    parts.append(ch)
                else:
                    walk(ch)
        walk(self)
        return " ".join("".join(parts).split())

    def attr(self, name):
        return self.attrs.get(name)

    def find_testid(self, testid):
        for el in self.iter():
            if el.attrs.get("data-testid") == testid:
                return el
        return None

    def find_all_testid_prefix(self, prefix):
        return [el for el in self.iter()
                if isinstance(el.attrs.get("data-testid"), str)
                and el.attrs.get("data-testid").startswith(prefix)]

    def iter(self):
        for ch in self.children:
            if isinstance(ch, Element):
                yield ch
                yield from ch.iter()

    def closest(self, pred):
        el = self
        while el is not None:
            if pred(el):
                return el
            el = el.parent
        return None


class _Parser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Element("#root", {}, None)
        self.stack = [self.root]
        self.order = 0

    def handle_starttag(self, tag, attrs):
        el = Element(tag, {k: (v if v is not None else "") for k, v in attrs},
                     self.stack[-1])
        self.order += 1
        el.order = self.order
        self.stack[-1].children.append(el)
        if tag not in VOID:
            self.stack.append(el)

    def handle_startendtag(self, tag, attrs):
        el = Element(tag, {k: (v if v is not None else "") for k, v in attrs},
                     self.stack[-1])
        self.order += 1
        el.order = self.order
        self.stack[-1].children.append(el)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                break

    def handle_data(self, data):
        if data:
            self.stack[-1]._text_parts.append(data)

    def close(self):
        super().close()
        # push collected text parts down: each element owns its direct text
        def assign(el):
            for ch in el.children:
                if isinstance(ch, Element):
                    assign(ch)
            direct = el._text_parts
            el._text_parts = []
            for ch in el.children:
                if isinstance(ch, str):
                    continue
            # direct text lives on the element itself
            el._direct_text = direct
        assign(self.root)

        def collect(el):
            text = list(getattr(el, "_direct_text", []))
            for ch in el.children:
                if isinstance(ch, Element):
                    text.extend(collect(ch))
            el._text_parts = text
            return text
        collect(self.root)


def parse(html):
    """Parse an HTML document string; return the root Element."""
    p = _Parser()
    p.feed(html)
    p.close()
    return p.root


def dom_of(resp, what="page"):
    if resp.status != 200:
        raise SuiteFailure(f"{what}: page fetch failed: HTTP {resp.status}: {resp.raw[:300]!r}")
    check("text/html" in resp.content_type,
          f"{what}: expected text/html page, got content-type {resp.content_type!r}")
    body = resp.raw.decode("utf-8", "replace")
    check(body.lstrip()[:15].lower().startswith(("<!doctype", "<html")),
          f"{what}: response is not an HTML document")
    return parse(body)


def require(root, testid, what):
    el = root.find_testid(testid)
    check(el is not None, f"{what}: missing [data-testid={testid}]")
    return el


def forbid(root, testid, what):
    el = root.find_testid(testid)
    check(el is None, f"{what}: [data-testid={testid}] must be absent, found: "
                      f"{el.text()[:80]!r}" if el is not None else "")


def has_label(root, control, what):
    """R99: every input has a visible label — label[for], wrapping <label>, or
    aria-label/aria-labelledby."""
    if any(control.attr(a) for a in ("aria-label", "aria-labelledby")):
        return True
    cid = control.attr("id")
    if cid:
        for el in root.iter():
            if el.tag == "label" and el.attr("for") == cid:
                return True
    if control.closest(lambda el: el.tag == "label") is not None:
        return True
    raise SuiteFailure(f"{what}: input [data-testid={control.attrs.get('data-testid')}] "
                       f"has no associated label")


def anchors(root):
    return [el.attr("href") or "" for el in root.iter() if el.tag == "a"]


def external_refs(root):
    """src/href values pointing off-origin (CDN links are forbidden, stage-1 R11)."""
    out = []
    for el in root.iter():
        for a in ("src", "href"):
            v = el.attr(a)
            if v and v.startswith(("http://", "https://", "//")):
                out.append((el.tag, a, v))
    return out