"""Operator CLI for `shared.user` — the auth bootstrap.

Zero users means nobody can log in (password_hash is NOT NULL), so this is the
entry point after a fresh migrate. Runs against `DATABASE_URL`.

    python -m scripts.manage_users create --username admin --display "Admin" \
        --role admin --password '...'
    python -m scripts.manage_users set-password --username admin --password '...'
    python -m scripts.manage_users list

Passwords are hashed with the same passlib context the API uses. Never pass a
production password on a shared shell history without care — prefer piping or an
interactive prompt in real deployments (v1 keeps it simple).
"""

from __future__ import annotations

import argparse
import os
import sys

import sqlalchemy as sa

from apps.tooling.api.security import hash_password
from shared.db import user as user_t
from shared.dsn_guard import assert_target_allowed

ROLES = ("viewer", "operator", "setter", "admin")


def _engine() -> sa.Engine:
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    if not url:
        sys.exit("DATABASE_URL not set")
    assert_target_allowed(url, action="manage_users")
    eng = sa.create_engine(url, future=True)

    @sa.event.listens_for(eng, "connect")
    def _sp(dbapi_conn, _rec):
        with dbapi_conn.cursor() as cur:
            cur.execute("SET search_path TO tooling, shared")

    return eng


def cmd_create(args: argparse.Namespace) -> None:
    if args.role not in ROLES:
        sys.exit(f"role must be one of {ROLES}")
    with _engine().begin() as conn:
        conn.execute(sa.insert(user_t).values(
            username=args.username, display_name=args.display, email=args.email,
            role=args.role, password_hash=hash_password(args.password),
        ))
    print(f"created user '{args.username}' role={args.role}")


def cmd_set_password(args: argparse.Namespace) -> None:
    with _engine().begin() as conn:
        res = conn.execute(
            sa.update(user_t).where(user_t.c.username == args.username)
            .values(password_hash=hash_password(args.password))
        )
    if res.rowcount == 0:
        sys.exit(f"no such user '{args.username}'")
    print(f"password updated for '{args.username}'")


def cmd_list(_args: argparse.Namespace) -> None:
    with _engine().connect() as conn:
        rows = conn.execute(
            sa.select(user_t.c.username, user_t.c.role, user_t.c.display_name,
                      user_t.c.disabled_at).order_by(user_t.c.username)
        ).all()
    for r in rows:
        state = "disabled" if r.disabled_at else "active"
        print(f"{r.username:20} {r.role:10} {state:10} {r.display_name}")
    if not rows:
        print("(no users)")


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Manage shared.user rows")
    sub = p.add_subparsers(dest="cmd", required=True)

    c = sub.add_parser("create")
    c.add_argument("--username", required=True)
    c.add_argument("--display", required=True)
    c.add_argument("--role", required=True, choices=ROLES)
    c.add_argument("--password", required=True)
    c.add_argument("--email", default=None)
    c.set_defaults(func=cmd_create)

    s = sub.add_parser("set-password")
    s.add_argument("--username", required=True)
    s.add_argument("--password", required=True)
    s.set_defaults(func=cmd_set_password)

    ls = sub.add_parser("list")
    ls.set_defaults(func=cmd_list)

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
