"""Exercise the real student/supervisor flow using synthetic data."""

import argparse
import tempfile
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4
from zipfile import ZipFile

from playwright.sync_api import Browser, Page, expect, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "backend/tests/fixtures/synthetic-import.docx"
DEMO_TEXT = (
    "В выдуманной лаборатории собрали механический календарь. "
    "Устройство отмечает дни деревянными фишками. Для демонстрации сравнили размер лотков, "
    "записали наблюдения и подготовили описание поведения механизма. "
    "Этот синтетический абзац используется только для проверки учебного кабинета."
)


def synthetic_docx(target: Path, final_text: str) -> None:
    with ZipFile(FIXTURE) as source, ZipFile(target, "w") as output:
        for entry in source.infolist():
            data = source.read(entry)
            if entry.filename == "word/document.xml":
                data = data.replace("Конец документа".encode(), final_text.encode())
            output.writestr(entry, data)


def login(page: Page, base: str, email: str, password: str) -> None:
    page.goto(f"{base}/login")
    page.get_by_label("Электронная почта").fill(email)
    page.get_by_label("Пароль").fill(password)
    page.get_by_role("button", name="Войти", exact=True).click()
    expect(page.get_by_role("button", name="Выйти")).to_be_visible()


def upload(page: Page, source: Path) -> None:
    page.get_by_label("Файл DOCX").set_input_files(source)
    page.get_by_label("Заменить рабочий документ", exact=False).check()
    page.get_by_role("button", name="Загрузить DOCX").click()
    expect(page.get_by_text("Загружена версия", exact=False)).to_be_visible()


def accept(browser: Browser, args: argparse.Namespace, directory: Path) -> None:
    password = args.password_file.read_text().strip()
    suffix = uuid4().hex[:8]
    student_email = f"student-{suffix}@example.com"
    group = f"Учебная группа {suffix}"
    thesis = f"Синтетический календарь {suffix}"
    stage = "Описание механизма"
    remark = "Уточните, как сравнивались лотки."
    first_doc, second_doc = directory / "draft.docx", directory / "fixed.docx"
    synthetic_docx(first_doc, DEMO_TEXT)
    synthetic_docx(second_doc, f"{DEMO_TEXT} Исправление: измерения сделаны линейкой.")

    student_ctx = browser.new_context()
    user = student_ctx.new_page()
    user.goto(args.base)
    user.wait_for_load_state("networkidle")
    user.screenshot(path=directory / "login.png", full_page=True)
    user.get_by_role("link", name="Зарегистрироваться студенту").click()
    user.get_by_label("Имя и фамилия").fill("Студент Демонстрационный")
    user.get_by_label("Учебная группа").fill("ТЕСТ-26")
    user.get_by_label("Электронная почта").fill(student_email)
    user.get_by_label("Пароль").fill(password)
    user.get_by_role("button", name="Создать аккаунт").click()
    expect(user.get_by_text("Аккаунт создан", exact=False)).to_be_visible()
    login(user, args.base, student_email, password)
    expect(
        user.get_by_text("Руководитель ещё не назначил вам тему ВКР.")
    ).to_be_visible()

    supervisor_ctx = browser.new_context()
    supervisor = supervisor_ctx.new_page()
    login(supervisor, args.base, args.supervisor, password)
    supervisor.get_by_label("Название группы").fill(group)
    supervisor.get_by_role("button", name="Создать группу", exact=True).click()
    expect(supervisor.get_by_role("heading", name=group)).to_be_visible()
    supervisor.get_by_label("Имя или email").fill(student_email)
    supervisor.get_by_role("button", name="Найти студента").click()
    expect(supervisor.get_by_text(student_email)).to_be_visible()
    supervisor.get_by_role("button", name="Добавить", exact=True).click()
    supervisor.get_by_text("Назначить ВКР", exact=True).click()
    supervisor.get_by_label("Тема ВКР").fill(thesis)
    supervisor.get_by_label("Срок ВКР").fill(
        (date.today() + timedelta(days=180)).isoformat()
    )
    supervisor.get_by_role("button", name="Создать ВКР").click()
    expect(supervisor.get_by_role("heading", name=thesis)).to_be_visible()
    work_url = supervisor.url
    supervisor.get_by_label("Название этапа").fill(stage)
    supervisor.get_by_role("button", name="Добавить этап").click()
    expect(supervisor.get_by_role("heading", name=stage, exact=False)).to_be_visible()
    supervisor.get_by_role("button", name="Изменить этап").click()
    edit = supervisor.get_by_role("listitem").filter(has_text=stage).first
    edit.get_by_label("Название этапа").fill(f"{stage} ВКР")
    edit.get_by_role("button", name="Сохранить этап").click()
    expect(
        supervisor.get_by_role("heading", name=f"{stage} ВКР", exact=False)
    ).to_be_visible()
    supervisor.get_by_role("link", name="Шаблоны").click()
    supervisor.get_by_role("button", name="Добавить шаблон").click()
    expect(
        supervisor.get_by_text("Шаблон доступен студентам вашей группы.")
    ).to_be_visible()

    user.reload()
    user.get_by_role("link", name=thesis).click()
    user.get_by_label("Шаблон оформления").select_option(label="ГОСТ 7.32-2017")
    user.get_by_role("button", name="Создать документ").click()
    upload(user, first_doc)
    user.get_by_role("button", name="Отправить на проверку").click()
    expect(user.get_by_text("На проверке", exact=True)).to_be_visible()
    user.screenshot(path=directory / "student.png", full_page=True)

    supervisor.goto(work_url)
    supervisor.get_by_role("link", name="Открыть проверку").click()
    initial_url = supervisor.url
    expect(supervisor.get_by_text(DEMO_TEXT, exact=True)).to_be_visible()
    supervisor.get_by_text("Написать замечание", exact=True).click()
    supervisor.get_by_label("Абзац или элемент").select_option(
        label=f"10. {DEMO_TEXT[:90]}"
    )
    supervisor.get_by_role("button", name="Выделить весь фрагмент").click()
    supervisor.get_by_label("Текст замечания").fill(remark)
    supervisor.get_by_role("button", name="Оставить замечание").click()
    expect(supervisor.get_by_text(remark, exact=True)).to_be_visible()
    assert supervisor.evaluate("document.documentElement.scrollWidth === innerWidth")
    supervisor.screenshot(path=directory / "review.png", full_page=True)
    supervisor.get_by_role("button", name="Вернуть на доработку").click()
    expect(supervisor.get_by_text("Нужны правки", exact=True)).to_be_visible()

    user.reload()
    user.get_by_role("link", name="Открыть отправленную версию").click()
    expect(user.get_by_text(remark, exact=True)).to_be_visible()
    user.get_by_role("button", name="К цитате в версии").click()
    user.get_by_role("button", name="Отметить исправленным").click()
    expect(user.get_by_text(remark, exact=True)).to_have_count(0)
    user.get_by_label("Показать закрытые").check()
    expect(user.get_by_text("Закрыто", exact=True)).to_be_visible()
    user.get_by_role("link", name=thesis).click()
    upload(user, second_doc)
    user.get_by_role("button", name="Отправить на проверку").click()
    expect(user.get_by_text("На проверке", exact=True)).to_be_visible()
    user.get_by_role("link", name="Открыть отправленную версию").click()
    final_url = user.url
    expect(user.get_by_text("Исправление: измерения", exact=False)).to_be_visible()
    thesis_id = urlparse(work_url).path.split("/")[-1]
    initial_id = urlparse(initial_url).path.split("/")[-1]
    final_id = urlparse(final_url).path.split("/")[-1]
    document = user.request.get(f"{args.base}/api/v1/theses/{thesis_id}/document")
    assert document.ok
    comparison = user.request.get(
        f"{args.base}/api/v1/documents/{document.json()['id']}/diff",
        params={"base": initial_id, "target": final_id},
    )
    assert comparison.ok
    assert any(
        change["kind"] == "changed"
        and "Исправление: измерения" in change["after"]["text"]
        for change in comparison.json()["changes"]
    )
    format_check = user.request.post(
        f"{args.base}/api/v1/document-versions/{final_id}/format-check",
        headers={"X-CSRF-Protection": "1"},
    )
    assert format_check.ok

    with user.expect_download() as download:
        user.get_by_role("button", name="Скачать DOCX").click()
    assert download.value.path().read_bytes().startswith(b"PK")
    if args.pdf:
        with user.expect_download(timeout=90_000) as pdf:
            user.get_by_role("button", name="Скачать PDF").click()
        assert pdf.value.path().read_bytes().startswith(b"%PDF")

    supervisor.goto(work_url)
    supervisor.get_by_role("link", name="Открыть проверку").click()
    expect(
        supervisor.get_by_text("Исправление: измерения", exact=False)
    ).to_be_visible()
    supervisor.get_by_role("button", name="Подтвердить этап").click()
    expect(supervisor.get_by_text("Подтверждён", exact=True)).to_be_visible()
    expect(supervisor.get_by_role("progressbar")).to_have_attribute("value", "100")
    supervisor.goto(initial_url)
    expect(supervisor.get_by_text(DEMO_TEXT, exact=True)).to_be_visible()
    expect(supervisor.get_by_text("Исправление: измерения", exact=False)).to_have_count(
        0
    )

    if args.live_plagiarism:
        user.get_by_label(
            "Версия содержит только демонстрационный текст", exact=False
        ).check()
        with user.expect_response(
            lambda response: (
                response.request.method == "POST"
                and response.url.endswith("/plagiarism-checks")
            )
        ) as response:
            user.get_by_role("button", name="Запустить проверку").click()
        assert response.value.status == 202, response.value.text()
        student_ctx.close()
        student_ctx = browser.new_context()
        user = student_ctx.new_page()
        login(user, args.base, student_email, password)
        user.goto(final_url)
        expect(user.get_by_text("Завершена", exact=True)).to_be_visible(timeout=120_000)
        user.get_by_text("Результаты проверки", exact=True).click()
        expect(user.get_by_text("Оригинальность", exact=True)).to_be_visible()
        expect(user.get_by_role("link", name="Краткий отчёт")).to_be_visible()
        print(
            "Live Antiplagiat worker, saved status and report verified after closing browser context"
        )

    outsider_ctx = browser.new_context()
    outsider = outsider_ctx.new_page()
    login(outsider, args.base, args.outsider, password)
    outsider.goto(final_url)
    expect(outsider.get_by_role("alert")).to_have_text("Запись не найдена.")
    expect(outsider.get_by_text(DEMO_TEXT, exact=False)).to_have_count(0)
    outsider_ctx.close()

    user.goto(work_url)
    expect(user.get_by_text("Подтверждён", exact=True)).to_be_visible()
    user.set_viewport_size({"width": 390, "height": 844})
    expect(user.get_by_role("heading", name=thesis)).to_be_visible()
    assert user.evaluate("document.documentElement.scrollWidth === innerWidth")
    user.screenshot(path=directory / "student-mobile.png", full_page=True)
    user.get_by_role("button", name="Выйти").click()
    expect(user.get_by_role("heading", name="Вход в кабинет")).to_be_visible()
    user.goto(work_url)
    expect(user.get_by_role("heading", name="Вход в кабинет")).to_be_visible()
    student_ctx.close()
    supervisor_ctx.close()
    print(
        f"Cabinets, review, document history, progress, isolation and logout verified. Screenshots: {directory}"
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="http://127.0.0.1:5173")
    parser.add_argument("--supervisor", required=True)
    parser.add_argument("--outsider", required=True)
    parser.add_argument("--password-file", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--live-plagiarism", action="store_true")
    parser.add_argument("--pdf", action="store_true")
    args = parser.parse_args()
    directory = args.output or Path(tempfile.mkdtemp(prefix="norma-cabinets-"))
    directory.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)
        try:
            accept(browser, args, directory)
        finally:
            browser.close()


if __name__ == "__main__":
    main()
