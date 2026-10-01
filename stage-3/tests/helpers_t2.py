from datetime import datetime, timedelta, timezone

import base


def login(port, email="ada@example.com", password="correct horse"):
    status, payload, _ = base.request(port, "POST", "/auth/login",
                                      body={"email": email, "password": password})
    assert status == 200, payload
    return {"Authorization": f"Bearer {payload['token']}"}


def future(days=1, **kwargs):
    return (datetime.now(timezone.utc) + timedelta(days=days, **kwargs)).isoformat()


def past(**kwargs):
    return (datetime.now(timezone.utc) - timedelta(days=1, **kwargs)).isoformat()


BASE_FIXTURE = {
    "currency": "EUR",
    "minor_units": 2,
    "users": [
        {"id": "u_ada", "email": "ada@example.com", "password": "correct horse",
         "display_name": "Ada", "handle": "ada", "balance": 10000},
        {"id": "u_bob", "email": "bob@example.com", "password": "correct horse",
         "display_name": "Bob", "handle": "bob", "balance": 2500},
        {"id": "u_carol", "email": "carol@example.com", "password": "correct horse",
         "display_name": "Carol", "handle": "carol", "balance": 500},
    ],
}


def seeded_fixture(authorizations):
    fixture = {**BASE_FIXTURE, "authorizations": authorizations}
    return fixture