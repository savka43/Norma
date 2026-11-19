"""Create a supervisor without exposing privileged registration over HTTP."""

import argparse
import asyncio
from getpass import getpass

from pydantic import ValidationError

from app.api_v1.auth.schemas import SupervisorBootstrap
from app.api_v1.auth.service import EmailAlreadyExistsError, bootstrap_supervisor
from app.core.config import load_settings
from app.core.database import create_engine, create_session_factory


async def _create_supervisor(data: SupervisorBootstrap) -> None:
    engine = create_engine(load_settings())
    try:
        async with create_session_factory(engine)() as session:
            user = await bootstrap_supervisor(session, data)
            print(f"Supervisor created: {user.id}")
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a supervisor account")
    parser.add_argument("--email", required=True)
    parser.add_argument("--full-name", required=True)
    parser.add_argument("--position", required=True)
    parser.add_argument("--department", required=True)
    arguments = parser.parse_args()
    password = getpass("Password (12–128 characters): ")
    if password != getpass("Confirm password: "):
        parser.exit(1, "Passwords do not match\n")
    try:
        data = SupervisorBootstrap.model_validate(
            {
                "email": arguments.email,
                "full_name": arguments.full_name,
                "position": arguments.position,
                "department": arguments.department,
                "password": password,
            }
        )
    except ValidationError as exc:
        parser.exit(
            1, f"Invalid account data: {exc.errors(include_input=False, include_context=False)}\n"
        )
    try:
        asyncio.run(_create_supervisor(data))
    except EmailAlreadyExistsError:
        parser.exit(1, "Email already registered; existing account was not changed\n")


if __name__ == "__main__":
    main()
