"""Feed contract (R26-R29, R75, R92 feed visibility)."""
import time

from client import (check, eq, expect_ok, fresh, get_me, make_payment)


def visible_ids(c, tok):
    out, offset = [], 0
    while True:
        page = expect_ok(c.get(f"/activity?limit=50&offset={offset}", token=tok),
                         200, "activity page")
        out.extend(page["payments"])
        if not page["has_more"]:
            return [p["payment_id"] for p in out]
        offset += len(page["payments"])
        check(offset < 1000, "pagination did not terminate")


def test_feed_iff_rule(c):
    # Exhaustive per-caller filter: public OR sender/receiver (R26).
    toks = fresh(c)
    p1 = expect_ok(make_payment(c, toks["ada"], "bob", 100, "f-1"), 201).json()   # public
    p2 = expect_ok(make_payment(c, toks["bob"], "cy", 200, "f-2",
                                visibility="private"), 201).json()
    p3 = expect_ok(make_payment(c, toks["cy"], "ada", 300, "f-3"), 201).json()
    p4 = expect_ok(make_payment(c, toks["ada"], "cy", 400, "f-4",
                                visibility="private"), 201).json()
    want = {
        "ada": {p1["payment_id"], p3["payment_id"], p4["payment_id"]},
        # bob sees public p1+p3 plus own p2 (receiver p1, sender p2)
        "bob": {p1["payment_id"], p2["payment_id"], p3["payment_id"]},
        # cy sees public p1+p3 plus own p2/p3/p4
        "cy": {p1["payment_id"], p2["payment_id"], p3["payment_id"],
               p4["payment_id"]},
    }
    for handle, tok in toks.items():
        eq(set(visible_ids(c, tok)), want[handle], f"feed set for {handle} (R26)")


def test_private_hidden_from_third_party_not_receiver(c):
    toks = fresh(c)
    p = expect_ok(make_payment(c, toks["ada"], "bob", 100, "pf-1",
                               visibility="private"), 201).json()
    check(p["payment_id"] in visible_ids(c, toks["ada"]),
          "sender sees own private payment (R29)")
    check(p["payment_id"] in visible_ids(c, toks["bob"]),
          "receiver sees own private payment, not hidden (R29)")
    check(p["payment_id"] not in visible_ids(c, toks["cy"]),
          "third party does not see private payment (R29)")


def test_visibility_identical_to_both_parties(c):
    toks = fresh(c)
    p = expect_ok(make_payment(c, toks["ada"], "bob", 100, "vf-1",
                               visibility="private"), 201).json()
    for tok in (toks["ada"], toks["bob"]):
        item = [x for x in expect_ok(c.get("/activity", token=tok), 200)["payments"]
                if x["payment_id"] == p["payment_id"]][0]
        eq(item["visibility"], "private", "one value seen identically (R29)")


def test_requests_never_in_feed(c):
    toks = fresh(c)
    rq = expect_ok(c.post("/requests", body={"payer_handle": "ada", "amount": 100},
                          token=toks["bob"], headers={"Idempotency-Key": "feedrq-1"}),
                   201)
    expect_ok(c.post(f"/requests/{rq['request_id']}/pay", body={},
                     token=toks["ada"], headers={"Idempotency-Key": "feedrq-1-k"}),
              201, "pay the request")
    feed = expect_ok(c.get("/activity", token=toks["ada"]), 200)["payments"]
    for item in feed:
        check("request_id" in item and "payment_id" in item,
              f"feed item is a payment, not a request: {sorted(item.keys())}")
    # The request object itself never surfaces via /activity (R25/R27).
    check(all(item["payment_id"] != rq["request_id"] for item in feed),
          "request id not presented as a feed item")


def test_split_not_a_feed_item(c):
    # R28: a split is not a feed item; only its eventual payments appear.
    toks = fresh(c)
    before = set(visible_ids(c, toks["cy"]))
    split = expect_ok(c.post("/splits", body={"amount": 300,
                                              "participant_handles": ["ada", "bob", "cy"]},
                             token=toks["ada"], headers={"Idempotency-Key": "spf-1"}),
                      201, "split")
    eq(set(visible_ids(c, toks["cy"])), before, "split creation adds no feed item (R28)")
    eq(set(visible_ids(c, toks["bob"])), before, "no feed item for other party (R28)")
    # The split's requests are visible to their two parties via /requests (R28).
    reqs = expect_ok(c.get("/requests?direction=incoming", token=toks["bob"]), 200)
    got = [r["request_id"] for r in reqs["requests"]]
    check(split["requests"][0]["request_id"] in got, "split request visible to payer")
    reqs_cy = expect_ok(c.get("/requests?direction=incoming", token=toks["cy"]), 200)
    got_cy = [r["request_id"] for r in reqs_cy["requests"]]
    check(split["requests"][1]["request_id"] in got_cy,
          "split request visible to its payer (R28)")


def test_feed_order_and_paging(c):
    toks = fresh(c)
    first_batch = [expect_ok(make_payment(c, toks["ada"], "bob", 10 + i, f"ord-{i}"),
                             201).json()["payment_id"] for i in range(3)]
    time.sleep(1.1)  # cross the second boundary; same-second order is unspecified (A3)
    second_batch = [expect_ok(make_payment(c, toks["ada"], "bob", 20 + i, f"ord2-{i}"),
                              201).json()["payment_id"] for i in range(3)]
    ids = visible_ids(c, toks["ada"])
    eq(set(ids), set(first_batch + second_batch), "all payments visible")
    check(ids.index(second_batch[0]) < ids.index(first_batch[0]),
          "newer payments appear before older ones (R75)")
    page1 = expect_ok(c.get("/activity?limit=2", token=toks["ada"]), 200)
    eq(len(page1["payments"]), 2, "limit respected (R75)")
    eq(page1["has_more"], True, "has_more true (R75)")
    page2 = expect_ok(c.get("/activity?limit=2&offset=2", token=toks["ada"]), 200)
    eq(page2["has_more"], True, "has_more still true (R75)")
    page3 = expect_ok(c.get("/activity?limit=2&offset=4", token=toks["ada"]), 200)
    eq(page3["has_more"], False, "has_more false at end (R75)")
    check(set(visible_ids(c, toks["ada"])) ==
          {p["payment_id"] for pg in (page1, page2, page3) for p in pg["payments"]},
          "paging covers the full feed without gaps or duplicates")


def test_activity_validation(c):
    toks = fresh(c)
    expect_error(c.get("/activity?limit=0", token=toks["ada"]), 422, "limit 0 (R41)")
    expect_error(c.get("/activity?limit=201", token=toks["ada"]), 422, "limit 201 (R41)")
    expect_error(c.get("/activity?offset=-1", token=toks["ada"]), 422, "offset -1 (R41)")
    expect_error(c.get("/activity?limit=2.5", token=toks["ada"]), 422, "limit 2.5 (R39)")