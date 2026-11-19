import sys
from unittest.mock import AsyncMock

import pytest

from app import bootstrap
from app.api_v1.auth.schemas import SupervisorBootstrap


@pytest.fixture
def bootstrap_arguments(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "app.bootstrap",
            "--email",
            "supervisor@example.com",
            "--full-name",
            "Руководитель",
            "--position",
            "Доцент",
            "--department",
            "Информационные системы",
        ],
    )


def test_bootstrap_reads_password_from_hidden_prompt(
    bootstrap_arguments: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    def prompt(_prompt: str) -> str:
        return "Synthetic-password-123"

    monkeypatch.setattr(bootstrap, "getpass", prompt)
    create = AsyncMock()
    monkeypatch.setattr(bootstrap, "_create_supervisor", create)
    bootstrap.main()
    create.assert_awaited_once()
    data = create.call_args.args[0]
    assert isinstance(data, SupervisorBootstrap)
    assert data.password.get_secret_value() == "Synthetic-password-123"


@pytest.mark.parametrize(
    "passwords", [["P@ss-123", "P@ss-123"], ["Synthetic-password-123", "Different-password-123"]]
)
def test_bootstrap_rejects_bad_password_without_echoing_it(
    bootstrap_arguments: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    passwords: list[str],
) -> None:
    values = iter(passwords)

    def prompt(_prompt: str) -> str:
        return next(values)

    monkeypatch.setattr(bootstrap, "getpass", prompt)
    create = AsyncMock()
    monkeypatch.setattr(bootstrap, "_create_supervisor", create)
    with pytest.raises(SystemExit) as exc:
        bootstrap.main()
    assert exc.value.code == 1
    create.assert_not_called()
    output = capsys.readouterr()
    assert all(password not in output.err + output.out for password in passwords)
