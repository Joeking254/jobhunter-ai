"""Administrative commands for secure first-install setup."""

import argparse
import getpass
import secrets

from sqlalchemy import select

from app.core.security import hash_password, validate_password
from app.db.session import SessionLocal
from app.models.models import User, UserSettings


def create_admin(email: str, password: str | None, generate_password: bool) -> str | None:
    if password is None and generate_password:
        password = secrets.token_urlsafe(18) + "A1"
    if password is None:
        password = getpass.getpass("Administrator password: ")
        confirmation = getpass.getpass("Confirm administrator password: ")
        if password != confirmation:
            raise SystemExit("Passwords do not match")
    validate_password(password)
    with SessionLocal.begin() as db:
        if db.scalar(select(User).where(User.email == email.lower())):
            raise SystemExit("An account with this email already exists")
        user = User(email=email.lower(), password_hash=hash_password(password), first_name="System", last_name="Administrator", is_admin=True, is_verified=True)
        db.add(user)
        db.flush()
        db.add(UserSettings(user_id=user.id))
    return password if generate_password else None


def main() -> None:
    parser = argparse.ArgumentParser(description="JOBHUNTER AI administrative commands")
    subparsers = parser.add_subparsers(dest="command", required=True)
    admin_parser = subparsers.add_parser("create-admin", help="Create the first administrator without a default password")
    admin_parser.add_argument("--email", required=True)
    admin_parser.add_argument("--password")
    admin_parser.add_argument("--generate-password", action="store_true")
    args = parser.parse_args()
    if args.command == "create-admin":
        generated = create_admin(args.email, args.password, args.generate_password)
        if generated:
            print(f"Generated administrator password (store it securely): {generated}")


if __name__ == "__main__":
    main()
