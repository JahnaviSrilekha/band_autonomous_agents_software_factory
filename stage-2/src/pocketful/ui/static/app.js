/* Pocketful UI — vanilla JS, no dependencies, no network beyond this origin. */
(function () {
  "use strict";

  var TOKEN_KEY = "pocketful_token";
  var PENDING_PAY_KEY = "pocketful_pending_pay";
  var PAY_TIMEOUT_MS = 4500;

  var body = document.body;
  var MINOR_UNITS = parseInt(body.getAttribute("data-minor-units") || "2", 10);
  var CURRENCY = body.getAttribute("data-currency") || "";

  function getToken() {
    try { return window.localStorage.getItem(TOKEN_KEY); } catch (err) { return null; }
  }

  function setToken(token) {
    try { window.localStorage.setItem(TOKEN_KEY, token); } catch (err) { /* cookie suffices */ }
    document.cookie = "pocketful_token=" + encodeURIComponent(token) + "; path=/; SameSite=Lax";
  }

  function clearToken() {
    try { window.localStorage.removeItem(TOKEN_KEY); } catch (err) { /* ignore */ }
    try { window.localStorage.removeItem(PENDING_PAY_KEY); } catch (err) { /* ignore */ }
    document.cookie = "pocketful_token=; Max-Age=0; path=/; SameSite=Lax";
  }

  function formatMinor(minor, minorUnits, currency) {
    var units = typeof minorUnits === "number" ? minorUnits : MINOR_UNITS;
    var cur = currency || CURRENCY;
    var negative = minor < 0;
    var value = Math.abs(Math.trunc(minor));
    var text;
    if (units <= 0) {
      text = String(value);
    } else {
      var digits = String(value);
      while (digits.length <= units) { digits = "0" + digits; }
      text = digits.slice(0, digits.length - units) + "." + digits.slice(digits.length - units);
    }
    return (negative ? "-" : "") + text + " " + cur;
  }

  function minorToDecimal(minor, minorUnits) {
    var units = typeof minorUnits === "number" ? minorUnits : MINOR_UNITS;
    var value = Math.abs(Math.trunc(minor));
    if (units <= 0) { return String(value); }
    var digits = String(value);
    while (digits.length <= units) { digits = "0" + digits; }
    return digits.slice(0, digits.length - units) + "." + digits.slice(digits.length - units);
  }

  function parseAmountToMinor(text, minorUnits) {
    var units = typeof minorUnits === "number" ? minorUnits : MINOR_UNITS;
    var trimmed = String(text === undefined || text === null ? "" : text).trim();
    var pattern = units > 0
      ? new RegExp("^(?:\\d+(?:\\.\\d{0," + units + "})?|\\.\\d{1," + units + "})$")
      : /^\d+$/;
    if (!pattern.test(trimmed)) { return null; }
    var dot = trimmed.indexOf(".");
    var whole = dot === -1 ? trimmed : trimmed.slice(0, dot);
    var frac = dot === -1 ? "" : trimmed.slice(dot + 1);
    if (whole === "") { whole = "0"; }
    while (frac.length < units) { frac += "0"; }
    var minor = parseInt(whole, 10) * Math.pow(10, units) + (units > 0 ? parseInt(frac, 10) : 0);
    return minor;
  }

  function computeShares(amount, count) {
    var base = Math.floor(amount / count);
    var remainder = amount % count;
    var shares = [];
    for (var i = 0; i < count; i += 1) {
      shares.push(i < remainder ? base + 1 : base);
    }
    return shares;
  }

  function idemKey(tag, fields) {
    var keys = Object.keys(fields).sort();
    var canonical = keys.map(function (k) {
      var v = fields[k];
      return JSON.stringify(k) + ":" + JSON.stringify(v === undefined ? null : v);
    }).join(",");
    var h1 = 0x811c9dc5;
    var h2 = 0x01000193;
    for (var i = 0; i < canonical.length; i += 1) {
      var code = canonical.charCodeAt(i);
      h1 = ((h1 ^ code) * 0x01000193) >>> 0;
      h2 = ((h2 ^ (h2 << 13)) + code * 31) >>> 0;
    }
    return "ui-" + tag + "-" + h1.toString(16) + h2.toString(16);
  }

  function sequencer() {
    return {
      issued: 0,
      applied: 0,
      next: function () { this.issued += 1; return this.issued; },
      shouldApply: function (seq) {
        if (seq >= this.applied) { this.applied = seq; return true; }
        return false;
      },
    };
  }

  var WALLET_SEQ = sequencer();
  var FEED_SEQ = sequencer();
  var REQUEST_SEQ = sequencer();
  var AUTH_SEQ = sequencer();

  function api(path, options) {
    options = options || {};
    var controller = new AbortController();
    var timer = window.setTimeout(function () { controller.abort(); },
      options.timeoutMs || 10000);
    var headers = { "Accept": "application/json" };
    var token = getToken();
    if (token) { headers["Authorization"] = "Bearer " + token; }
    if (options.key) { headers["Idempotency-Key"] = options.key; }
    var init = { method: options.method || "GET", headers: headers, signal: controller.signal };
    if (options.body !== undefined) {
      headers["Content-Type"] = "application/json";
      init.body = JSON.stringify(options.body);
    }
    return window.fetch(path, init).then(function (res) {
      return res.text().then(function (text) {
        var data = null;
        if (text) { try { data = JSON.parse(text); } catch (err) { data = null; } }
        return { status: res.status, ok: res.ok, data: data };
      });
    }).finally(function () { window.clearTimeout(timer); });
  }

  function errorMessage(data, fallback) {
    if (data && data.error && data.error.message) { return data.error.message; }
    return fallback;
  }

  function ensureMsgBox(container, testid, cssClass) {
    var box = container.querySelector('[data-testid="' + testid + '"]');
    if (!box) {
      box = el("div", "form-msg " + cssClass);
      box.setAttribute("data-testid", testid);
      box.setAttribute("role", "alert");
      container.appendChild(box);
    }
    return box;
  }

  function showMsg(container, testid, cssClass, text) {
    if (!container) { return; }
    var box = ensureMsgBox(container, testid, cssClass);
    box.textContent = text;
    box.classList.add("is-visible");
  }

  function clearMsg(container, testid) {
    if (!container) { return; }
    var box = container.querySelector('[data-testid="' + testid + '"]');
    if (box) { box.remove(); }
  }

  function el(tag, className, text) {
    var node = document.createElement(tag);
    if (className) { node.className = className; }
    if (text !== undefined && text !== null) { node.textContent = text; }
    return node;
  }

  function humanTime(iso) {
    var moment = new Date(iso);
    if (isNaN(moment.getTime())) { return iso || ""; }
    return moment.toLocaleString(undefined, {
      month: "short", day: "numeric", year: "numeric", hour: "2-digit", minute: "2-digit",
    });
  }

  function testid(id) { return '[data-testid="' + id + '"]'; }

  function myHandle() {
    var node = body.querySelector(testid("current-handle"));
    return node ? node.textContent : "";
  }

  function setAmount(node, minor) {
    node.textContent = formatMinor(minor);
    node.setAttribute("data-amount", String(Math.trunc(minor)));
  }

  function renderWallet(me) {
    if (typeof me.minor_units === "number") { MINOR_UNITS = me.minor_units; }
    if (me.currency) { CURRENCY = me.currency; }
    var available = body.querySelector(testid("wallet-available"));
    var balance = body.querySelector(testid("wallet-balance"));
    if (balance) { setAmount(balance, me.balance); }
    if (available) { setAmount(available, me.available); }
    var held = body.querySelector(testid("wallet-held"));
    if (me.held > 0) {
      if (!held) {
        var secondary = balance ? balance.closest(".wallet__secondary") : null;
        if (secondary) {
          var cell = el("span", "wallet__cell");
          cell.appendChild(el("span", "wallet__label", "Held"));
          held = el("span", "amount amount--held");
          held.setAttribute("data-testid", "wallet-held");
          cell.appendChild(held);
          secondary.appendChild(cell);
        }
      }
      if (held) { setAmount(held, me.held); }
    } else if (held) {
      var cell = held.closest(".wallet__cell") || held;
      cell.remove();
    }
  }

  function mainSide() {
    var main = el("div", "list__main");
    var side = el("div", "list__side");
    return { main: main, side: side, item: el("li", "list__item") };
  }

  function renderFeed(payments) {
    var list = body.querySelector(testid("activity-list"));
    var empty = body.querySelector(testid("empty-activity"));
    if (!list) { return; }
    list.textContent = "";
    payments.forEach(function (payment) {
      var id = payment.payment_id;
      var parts = mainSide();
      parts.item.setAttribute("data-testid", "activity-item-" + id);
      parts.item.setAttribute("data-visibility", payment.visibility);
      var parties = el("div", "list__title",
        payment.from_handle + " \u2192 " + payment.to_handle);
      parties.setAttribute("data-testid", "activity-parties-" + id);
      parts.main.appendChild(parties);
      var note = el("div", "note", payment.note || "");
      note.setAttribute("data-testid", "activity-note-" + id);
      parts.main.appendChild(note);
      parts.main.appendChild(el("div", "list__meta", humanTime(payment.created_at)));
      parts.side.appendChild(el("span", "pill pill--visibility",
        payment.visibility === "private" ? "Private" : "Public"));
      var amount = el("span", "amount amount--item", formatMinor(payment.amount));
      amount.setAttribute("data-testid", "activity-amount-" + id);
      parts.side.appendChild(amount);
      parts.item.appendChild(parts.main);
      parts.item.appendChild(parts.side);
      list.appendChild(parts.item);
    });
    if (payments.length === 0) {
      list.hidden = true;
      if (empty) { empty.hidden = false; }
    } else {
      list.hidden = false;
      if (empty) { empty.hidden = true; }
    }
  }

  function requestSideControls(request, isIncoming) {
    var fragment = document.createDocumentFragment();
    if (request.status === "pending" && isIncoming) {
      var payBtn = el("button", "btn btn--good btn--small", "Pay");
      payBtn.type = "button";
      payBtn.setAttribute("data-testid", "request-pay-" + request.request_id);
      var declineBtn = el("button", "btn btn--danger btn--small", "Decline");
      declineBtn.type = "button";
      declineBtn.setAttribute("data-testid", "request-decline-" + request.request_id);
      fragment.appendChild(payBtn);
      fragment.appendChild(declineBtn);
    }
    if (request.status === "pending" && !isIncoming) {
      var cancelBtn = el("button", "btn btn--ghost btn--small", "Cancel");
      cancelBtn.type = "button";
      cancelBtn.setAttribute("data-testid", "request-cancel-" + request.request_id);
      fragment.appendChild(cancelBtn);
    }
    return fragment;
  }

  function renderRequests(payload) {
    var incoming = body.querySelector(testid("incoming-list"));
    var outgoing = body.querySelector(testid("outgoing-list"));
    var empty = body.querySelector(testid("empty-requests"));
    if (!incoming || !outgoing) { return; }
    var handle = myHandle();
    incoming.textContent = "";
    outgoing.textContent = "";
    payload.requests.forEach(function (request) {
      var id = request.request_id;
      var isIncoming = request.payer_handle === handle;
      var parts = mainSide();
      parts.item.setAttribute("data-testid", "request-item-" + id);
      parts.item.setAttribute("data-status", request.status);
      parts.main.appendChild(el("div", "list__title", isIncoming
        ? request.requester_handle + " asked you for"
        : "You asked " + request.payer_handle));
      if (request.note) {
        parts.main.appendChild(el("div", "note", request.note));
      }
      parts.main.appendChild(el("div", "list__meta", humanTime(request.created_at)));
      parts.side.appendChild(el("span", "pill pill--" + request.status, request.status));
      var amount = el("span", "amount amount--item", formatMinor(request.amount));
      amount.setAttribute("data-testid", "request-amount-" + id);
      parts.side.appendChild(amount);
      parts.side.appendChild(requestSideControls(request, isIncoming));
      parts.item.appendChild(parts.main);
      parts.item.appendChild(parts.side);
      (isIncoming ? incoming : outgoing).appendChild(parts.item);
    });
    var any = payload.requests.length > 0;
    incoming.hidden = !any;
    outgoing.hidden = !any;
    if (empty) { empty.hidden = any; }
  }

  function authorizationSideControls(auth, isOutgoing) {
    var fragment = document.createDocumentFragment();
    if (auth.status === "open" && !isOutgoing) {
      var field = el("div", "field");
      var label = el("label", "field__label", "Capture amount");
      label.setAttribute("for", "capture-" + auth.authorization_id);
      var input = el("input");
      input.type = "text";
      input.inputMode = "decimal";
      input.id = "capture-" + auth.authorization_id;
      input.value = minorToDecimal(auth.remaining_amount);
      input.setAttribute("data-testid",
        "authorization-capture-amount-" + auth.authorization_id);
      label.appendChild(input);
      field.appendChild(label);
      var captureBtn = el("button", "btn btn--good btn--small", "Capture");
      captureBtn.type = "button";
      captureBtn.setAttribute("data-testid", "authorization-capture-" + auth.authorization_id);
      field.appendChild(captureBtn);
      var controls = el("div", "capture-controls");
      controls.appendChild(field);
      fragment.appendChild(controls);
    }
    if (auth.status === "open" && isOutgoing) {
      var voidBtn = el("button", "btn btn--ghost btn--small", "Release hold");
      voidBtn.type = "button";
      voidBtn.setAttribute("data-testid", "authorization-void-" + auth.authorization_id);
      fragment.appendChild(voidBtn);
    }
    return fragment;
  }

  function renderAuthorizations(payload) {
    var list = body.querySelector(testid("authorization-list"));
    var empty = body.querySelector(testid("empty-authorizations"));
    if (!list) { return; }
    var handle = myHandle();
    list.textContent = "";
    payload.authorizations.forEach(function (auth) {
      var id = auth.authorization_id;
      var isOutgoing = auth.from_handle === handle;
      var parts = mainSide();
      parts.item.setAttribute("data-testid", "authorization-item-" + id);
      parts.item.setAttribute("data-status", auth.status);
      parts.main.appendChild(el("div", "list__title", isOutgoing
        ? "You authorized money for " + auth.to_handle
        : auth.from_handle + " authorized money for you"));
      if (auth.note) {
        parts.main.appendChild(el("div", "note", auth.note));
      }
      var meta = el("div", "list__meta");
      meta.appendChild(document.createTextNode("Expires "));
      var expiry = el("span", "expiry", auth.expires_at);
      expiry.setAttribute("data-testid", "authorization-expires-" + id);
      meta.appendChild(expiry);
      parts.main.appendChild(meta);
      parts.side.appendChild(el("span", "pill pill--" + auth.status, auth.status));
      var amount = el("span", "amount amount--item", formatMinor(auth.amount));
      amount.setAttribute("data-testid", "authorization-amount-" + id);
      parts.side.appendChild(amount);
      if (auth.status === "captured") {
        var captured = el("span", "amount amount--item amount--total",
          formatMinor(auth.captured_amount) + " captured");
        captured.setAttribute("data-testid", "authorization-captured-" + id);
        parts.side.appendChild(captured);
      }
      parts.side.appendChild(authorizationSideControls(auth, isOutgoing));
      parts.item.appendChild(parts.main);
      parts.item.appendChild(parts.side);
      list.appendChild(parts.item);
    });
    var any = payload.authorizations.length > 0;
    list.hidden = !any;
    if (empty) { empty.hidden = any; }
  }

  function refreshWallet() {
    var seq = WALLET_SEQ.next();
    api("/me").then(function (result) {
      if (WALLET_SEQ.shouldApply(seq) && result.ok) { renderWallet(result.data); }
    }).catch(function () { /* keep last state */ });
  }

  function refreshFeed() {
    var list = body.querySelector(testid("activity-list"));
    if (!list) { return; }
    var seq = FEED_SEQ.next();
    api("/activity").then(function (result) {
      if (FEED_SEQ.shouldApply(seq) && result.ok) { renderFeed(result.data.payments); }
    }).catch(function () { /* keep last state */ });
  }

  function refreshWalletAndFeed() {
    refreshWallet();
    refreshFeed();
  }

  function refreshRequests() {
    var incoming = body.querySelector(testid("incoming-list"));
    if (!incoming) { return; }
    var seq = REQUEST_SEQ.next();
    api("/requests").then(function (result) {
      if (REQUEST_SEQ.shouldApply(seq) && result.ok) { renderRequests(result.data); }
    }).catch(function () { /* keep last state */ });
  }

  function refreshAuthorizationsAndWallet() {
    var list = body.querySelector(testid("authorization-list"));
    if (list) {
      var seq = AUTH_SEQ.next();
      api("/authorizations").then(function (result) {
        if (AUTH_SEQ.shouldApply(seq) && result.ok) { renderAuthorizations(result.data); }
      }).catch(function () { /* keep last state */ });
    }
    refreshWallet();
  }

  function answerRequest(id, action, button) {
    var section = body.querySelector('[data-page="requests"]') || body;
    var path = "/requests/" + encodeURIComponent(id) + "/" + action;
    var options = { method: "POST", body: {} };
    if (action === "pay") {
      options.key = idemKey("reqpay-" + id, { request_id: id });
    }
    if (button) { button.disabled = true; }
    api(path, options).then(function (result) {
      if (result.ok) {
        clearMsg(section, "request-error");
      } else {
        showMsg(section, "request-error", "form-msg form-msg--error",
          errorMessage(result.data, "That request could not be completed."));
      }
      refreshRequests();
      if (action === "pay") { refreshWallet(); }
      if (button) { button.disabled = false; }
    }).catch(function () {
      showMsg(section, "request-error", "form-msg form-msg--error",
        "We could not reach Pocketful. Please try again.");
      if (button) { button.disabled = false; }
    });
  }

  function captureAuthorization(id, amountText, button) {
    var section = body.querySelector('[data-page="authorizations"]') || body;
    clearMsg(section, "authorization-error");
    var minor = parseAmountToMinor(amountText);
    if (minor === null) {
      showMsg(section, "authorization-error", "form-msg form-msg--error",
        "Please enter a capture amount with at most " + MINOR_UNITS + " decimal places.");
      return;
    }
    if (button) { button.disabled = true; }
    api("/authorizations/" + encodeURIComponent(id) + "/capture", {
      method: "POST",
      body: { amount: minor },
      key: idemKey("capture-" + id, { authorization_id: id, amount: minor }),
    }).then(function (result) {
      if (!result.ok) {
        showMsg(section, "authorization-error", "form-msg form-msg--error",
          errorMessage(result.data, "The capture was refused."));
      }
      refreshAuthorizationsAndWallet();
      if (button) { button.disabled = false; }
    }).catch(function () {
      showMsg(section, "authorization-error", "form-msg form-msg--error",
        "We could not reach Pocketful. Please try again.");
      if (button) { button.disabled = false; }
    });
  }

  function voidAuthorization(id, button) {
    var section = body.querySelector('[data-page="authorizations"]') || body;
    clearMsg(section, "authorization-error");
    if (button) { button.disabled = true; }
    api("/authorizations/" + encodeURIComponent(id) + "/void", {
      method: "POST", body: {},
    }).then(function (result) {
      if (!result.ok) {
        showMsg(section, "authorization-error", "form-msg form-msg--error",
          errorMessage(result.data, "The release was refused."));
      }
      refreshAuthorizationsAndWallet();
      if (button) { button.disabled = false; }
    }).catch(function () {
      showMsg(section, "authorization-error", "form-msg form-msg--error",
        "We could not reach Pocketful. Please try again.");
      if (button) { button.disabled = false; }
    });
  }

  function wireLogoutButtons() {
    var logout = body.querySelector(testid("logout-button"));
    if (!logout) { return; }
    logout.addEventListener("click", function () {
      clearToken();
      window.location.href = "/login";
    });
  }

  function wireAuthForm() {
    var form = document.getElementById("auth-form");
    if (!form) { return; }
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      clearMsg(form, "auth-error");
      var endpoint = form.getAttribute("data-endpoint");
      var payload = {};
      if (endpoint === "/auth/signup") {
        payload.email = document.getElementById("signup-email").value;
        payload.password = document.getElementById("signup-password").value;
        payload.display_name = document.getElementById("signup-display-name").value;
      } else {
        payload.email = document.getElementById("login-email").value;
        payload.password = document.getElementById("login-password").value;
      }
      api(endpoint, { method: "POST", body: payload }).then(function (result) {
        if (result.ok && result.data && result.data.token) {
          setToken(result.data.token);
          window.location.href = "/";
          return;
        }
        showMsg(form, "auth-error", "form-msg form-msg--error", errorMessage(result.data,
          result.status === 401 ? "Unknown email or wrong password."
            : "We could not sign you in. Please check your details."));
      }).catch(function () {
        showMsg(form, "auth-error", "form-msg form-msg--error",
          "We could not reach Pocketful. Please try again.");
      });
    });
  }

  function wirePayForm() {
    var payForm = document.getElementById("pay-form");
    if (!payForm) { return; }
    payForm.addEventListener("submit", function (event) {
      event.preventDefault();
      clearMsg(payForm, "pay-error");
      clearMsg(payForm, "pay-uncertain");
      var handle = document.getElementById("pay-handle").value.trim();
      var amountText = document.getElementById("pay-amount").value;
      var note = document.getElementById("pay-note").value;
      var visibility = document.getElementById("pay-visibility").value;
      var minor = parseAmountToMinor(amountText);
      if (!handle || minor === null) {
        showMsg(payForm, "pay-error", "form-msg form-msg--error", minor === null
          ? "Enter an amount with at most " + MINOR_UNITS + " decimal places."
          : "Please enter a recipient handle.");
        return;
      }
      var payload = { to_handle: handle, amount: minor, note: note, visibility: visibility };
      var key = idemKey("pay", payload);
      api("/payments", { method: "POST", body: payload, key: key,
        timeoutMs: PAY_TIMEOUT_MS }).then(function (result) {
        clearPendingPay();
        if (result.ok) {
          refreshWalletAndFeed();
          return;
        }
        if (result.status >= 500) {
          showUncertain();
          return;
        }
        showMsg(payForm, "pay-error", "form-msg form-msg--error",
          errorMessage(result.data, "The payment was refused."));
        refreshWalletAndFeed();
      }).catch(function () {
        showUncertain();
      });

      function showUncertain() {
        try {
          window.localStorage.setItem(PENDING_PAY_KEY,
            JSON.stringify({ key: key, body: payload }));
        } catch (err) { /* ignore */ }
        showMsg(payForm, "pay-uncertain", "form-msg form-msg--uncertain",
          "We sent your payment but could not confirm it. Press Send payment again " +
          "to check its status — you will not be charged twice.");
      }
    });
  }

  function clearPendingPay() {
    try { window.localStorage.removeItem(PENDING_PAY_KEY); } catch (err) { /* ignore */ }
  }

  function wireRequestForm() {
    var requestForm = document.getElementById("request-form");
    if (!requestForm) { return; }
    requestForm.addEventListener("submit", function (event) {
      event.preventDefault();
      clearMsg(requestForm, "request-error");
      var handle = document.getElementById("request-handle").value.trim();
      var minor = parseAmountToMinor(document.getElementById("request-amount").value);
      var note = document.getElementById("request-note").value;
      if (!handle || minor === null) {
        showMsg(requestForm, "request-error", "form-msg form-msg--error", minor === null
          ? "Please enter an amount with at most " + MINOR_UNITS + " decimal places."
          : "Please enter who the request is for.");
        return;
      }
      var payload = { payer_handle: handle, amount: minor, note: note };
      var key = idemKey("request", payload);
      api("/requests", { method: "POST", body: payload, key: key }).then(function (result) {
        if (result.ok) {
          refreshWalletAndFeed();
        } else {
          showMsg(requestForm, "request-error", "form-msg form-msg--error",
            errorMessage(result.data, "The request was refused."));
        }
      }).catch(function () {
        showMsg(requestForm, "request-error", "form-msg form-msg--error",
          "We could not reach Pocketful. Please try again.");
      });
    });
  }

  function wireRequestsPage() {
    var incoming = body.querySelector(testid("incoming-list"));
    if (!incoming) { return; }
    var section = incoming.closest('[data-page="requests"]') || body;
    section.addEventListener("click", function (event) {
      var button = event.target.closest("button");
      if (!button) { return; }
      var testidAttr = button.getAttribute("data-testid") || "";
      var match = /^(request-(?:pay|decline|cancel)-(.+))$/.exec(testidAttr);
      if (!match) { return; }
      var action = match[1].indexOf("request-pay-") === 0 ? "pay"
        : match[1].indexOf("request-decline-") === 0 ? "decline" : "cancel";
      answerRequest(match[2], action, button);
    });
  }

  function wireAuthorizationsPage() {
    var form = document.getElementById("authorize-form");
    var list = body.querySelector(testid("authorization-list"));
    var authorizeNonce = 0;
    if (list) {
      list.addEventListener("click", function (event) {
        var button = event.target.closest("button");
        if (!button) { return; }
        var testidAttr = button.getAttribute("data-testid") || "";
        var captureMatch = /^authorization-capture-(.+)$/.exec(testidAttr);
        var voidMatch = /^authorization-void-(.+)$/.exec(testidAttr);
        if (captureMatch) {
          var input = document.getElementById("capture-" + captureMatch[1]);
          captureAuthorization(captureMatch[1], input ? input.value : "", button);
        } else if (voidMatch) {
          voidAuthorization(voidMatch[1], button);
        }
      });
    }
    if (!form) { return; }
    form.addEventListener("submit", function (event) {
      event.preventDefault();
      clearMsg(form, "authorize-error");
      var handle = document.getElementById("authorize-handle").value.trim();
      var minor = parseAmountToMinor(document.getElementById("authorize-amount").value);
      var note = document.getElementById("authorize-note").value;
      var visibility = document.getElementById("authorize-visibility").value;
      if (!handle || minor === null) {
        showMsg(form, "authorize-error", "form-msg form-msg--error", minor === null
          ? "Please enter an amount with at most " + MINOR_UNITS + " decimal places."
          : "Please enter a recipient handle.");
        return;
      }
      authorizeNonce += 1;
      var payload = { to_handle: handle, amount: minor, note: note, visibility: visibility };
      var key = idemKey("authz", {
        to_handle: handle, amount: minor, note: note, visibility: visibility,
        n: authorizeNonce,
      });
      api("/authorizations", { method: "POST", body: payload, key: key })
        .then(function (result) {
          if (result.ok) {
            refreshAuthorizationsAndWallet();
          } else {
            showMsg(form, "authorize-error", "form-msg form-msg--error",
              errorMessage(result.data, "The authorization was refused."));
          }
        }).catch(function () {
          showMsg(form, "authorize-error", "form-msg form-msg--error",
            "We could not reach Pocketful. Please try again.");
        });
    });
  }

  function wireSplitPage() {
    var form = document.getElementById("split-form");
    if (!form) { return; }
    var previewSlot = body.querySelector(testid("split-preview"));
    var previewRows = document.getElementById("split-preview-rows");

    function parseHandles(text) {
      return String(text || "").split(",").map(function (h) { return h.trim(); })
        .filter(function (h) { return h.length > 0; });
    }

    function refreshPreview() {
      var handles = parseHandles(document.getElementById("split-handles").value);
      var minor = parseAmountToMinor(document.getElementById("split-amount").value);
      if (handles.length === 0 || minor === null) {
        previewSlot.hidden = true;
        previewRows.textContent = "";
        return;
      }
      var shares = computeShares(minor, handles.length);
      previewRows.textContent = "";
      handles.forEach(function (handle, index) {
        var row = el("div", "preview__row");
        row.appendChild(el("span", null, handle));
        var share = el("span", "amount amount--item", formatMinor(shares[index]));
        share.setAttribute("data-testid", "split-share-" + handle);
        row.appendChild(share);
        previewRows.appendChild(row);
      });
      previewSlot.hidden = false;
    }

    document.getElementById("split-handles").addEventListener("input", refreshPreview);
    document.getElementById("split-amount").addEventListener("input", refreshPreview);

    form.addEventListener("submit", function (event) {
      event.preventDefault();
      clearMsg(form, "split-error");
      clearMsg(form, "split-success");
      var handles = parseHandles(document.getElementById("split-handles").value);
      var minor = parseAmountToMinor(document.getElementById("split-amount").value);
      var note = document.getElementById("split-note").value;
      if (handles.length === 0) {
        showMsg(form, "split-error", "form-msg form-msg--error",
          "Please enter at least one handle, separated by commas.");
        return;
      }
      if (minor === null) {
        showMsg(form, "split-error", "form-msg form-msg--error",
          "Please enter an amount with at most " + MINOR_UNITS + " decimal places.");
        return;
      }
      var key = idemKey("split", {
        participant_handles: handles, amount: minor, note: note,
      });
      api("/splits", {
        method: "POST",
        body: { participant_handles: handles, amount: minor, note: note },
        key: key,
      }).then(function (result) {
        if (result.ok) {
          var created = result.data && result.data.requests ? result.data.requests.length : 0;
          showMsg(form, "split-success", "form-msg form-msg--success", created > 0
            ? "Split created — " + created + " payment " +
              (created === 1 ? "request" : "requests") + " sent."
            : "Split created.");
        } else {
          showMsg(form, "split-error", "form-msg form-msg--error",
            errorMessage(result.data, "The split was refused."));
        }
      }).catch(function () {
        showMsg(form, "split-error", "form-msg form-msg--error",
          "We could not reach Pocketful. Please try again.");
      });
    });
  }

  function wireRefreshButton() {
    var refresh = body.querySelector(testid("wallet-refresh"));
    if (refresh) {
      refresh.addEventListener("click", function () {
        refreshWalletAndFeed();
      });
    }
  }

  document.addEventListener("DOMContentLoaded", function () {
    wireLogoutButtons();
    wireAuthForm();
    wirePayForm();
    wireRequestForm();
    wireRequestsPage();
    wireSplitPage();
    wireAuthorizationsPage();
    wireRefreshButton();
  });
}());