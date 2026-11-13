"""Manage the login from the command line, on the machine running the backend.

    python -m app.auth set-password [--username NAME]
    python -m app.auth enable-totp
    python -m app.auth disable-totp
    python -m app.auth add-token NAME --scope read|write
    python -m app.auth revoke-token NAME
    python -m app.auth list-tokens
    python -m app.auth logout-all
    python -m app.auth status

Run from ``backend/`` with the project's virtualenv. Nothing secret is ever
taken from the command line itself: passwords and codes are typed at a prompt
without echo, so they don't end up in the shell history.
"""

from __future__ import annotations

import argparse
import getpass
import sys

from app.auth import service
from app.db import SessionLocal, init_db


def _set_password(args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        current = service.get_account(db)
        username = args.username or (current.username if current else None)
        if not username:
            username = input("Identifiant : ").strip()
        first = getpass.getpass("Nouveau mot de passe : ")
        second = getpass.getpass("Encore une fois : ")
        if first != second:
            print("Les deux saisies diffèrent, rien n'a changé.", file=sys.stderr)
            return 1
        try:
            service.set_password(db, username, first)
        except ValueError as err:
            print(f"Refusé : {err}", file=sys.stderr)
            return 1
    print(f"Mot de passe enregistré pour « {username} ». Les sessions ouvertes sont fermées.")
    return 0


def _enable_totp(_: argparse.Namespace) -> int:
    from app.auth import totp

    with SessionLocal() as db:
        account = service.get_account(db)
        if account is None:
            print("Crée d'abord le compte : python -m app.auth set-password", file=sys.stderr)
            return 1
        secret = service.start_totp(db)
        uri = totp.provisioning_uri(secret, account.username)
        print("Ajoute ce compte dans ton appli d'authentification.")
        print(f"  Clé à saisir : {secret}")
        print(f"  Ou lien à scanner : {uri}")
        print("  (QR dans le terminal : qrencode -t ansiutf8 '<le lien>')")
        for _attempt in range(3):
            code = getpass.getpass("Code à 6 chiffres affiché par l'appli : ")
            if service.confirm_totp(db, code):
                print("Code à 6 chiffres activé. Il sera demandé à chaque connexion.")
                return 0
            print("Code refusé, réessaie (vérifie l'heure du téléphone).", file=sys.stderr)
    print("Pas activé : relance la commande pour une nouvelle clé.", file=sys.stderr)
    return 1


def _disable_totp(_: argparse.Namespace) -> int:
    with SessionLocal() as db:
        service.disable_totp(db)
    print("Code à 6 chiffres désactivé.")
    return 0


def _add_token(args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        try:
            token = service.add_service_token(db, args.name, args.scope)
        except ValueError as err:
            print(f"Refusé : {err}", file=sys.stderr)
            return 1
    # The token alone on stdout, so it can be piped straight into a file.
    print(token)
    print(f"Jeton « {args.name} » ({args.scope}) créé. Il ne sera plus jamais affiché.", file=sys.stderr)
    return 0


def _revoke_token(args: argparse.Namespace) -> int:
    with SessionLocal() as db:
        found = service.revoke_service_token(db, args.name)
    print("Jeton révoqué." if found else "Aucun jeton à ce nom.")
    return 0 if found else 1


def _list_tokens(_: argparse.Namespace) -> int:
    with SessionLocal() as db:
        rows = service.list_service_tokens(db)
    if not rows:
        print("Aucun jeton de service.")
    for row in rows:
        used = row.last_used_at.strftime("%Y-%m-%d %H:%M") if row.last_used_at else "jamais"
        print(f"{row.name:<24} {row.scope:<6} dernier usage : {used}")
    return 0


def _logout_all(_: argparse.Namespace) -> int:
    with SessionLocal() as db:
        count = service.logout_everywhere(db)
    print(f"{count} session(s) fermée(s).")
    return 0


def _status(_: argparse.Namespace) -> int:
    from app.config import get_settings

    with SessionLocal() as db:
        account = service.get_account(db)
        tokens = service.list_service_tokens(db)
    print(f"Connexion exigée (AUTH_REQUIRED) : {'oui' if get_settings().auth_required else 'non, journal seulement'}")
    print(f"Compte : {account.username if account else 'aucun'}")
    print(f"Code à 6 chiffres : {'actif' if account and account.totp_enabled else 'inactif'}")
    print(f"Jetons de service : {', '.join(t.name for t in tokens) or 'aucun'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.auth", description="Connexion à Stock Analyst")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("set-password", help="créer le compte ou changer le mot de passe")
    p.add_argument("--username")
    p.set_defaults(func=_set_password)

    sub.add_parser("enable-totp", help="activer le code à 6 chiffres").set_defaults(func=_enable_totp)
    sub.add_parser("disable-totp", help="désactiver le code à 6 chiffres").set_defaults(func=_disable_totp)

    p = sub.add_parser("add-token", help="créer un jeton de service (affiché une fois)")
    p.add_argument("name")
    p.add_argument("--scope", choices=service.SCOPES, required=True)
    p.set_defaults(func=_add_token)

    p = sub.add_parser("revoke-token", help="supprimer un jeton de service")
    p.add_argument("name")
    p.set_defaults(func=_revoke_token)

    sub.add_parser("list-tokens", help="lister les jetons de service").set_defaults(func=_list_tokens)
    sub.add_parser("logout-all", help="fermer toutes les sessions").set_defaults(func=_logout_all)
    sub.add_parser("status", help="état de la connexion").set_defaults(func=_status)

    args = parser.parse_args(argv)
    init_db()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
