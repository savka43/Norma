"""Exercise the real student/supervisor flow using synthetic data."""

import argparse
import tempfile
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4
from zipfile import ZipFile

from playwright.sync_api import Browser, Locator, Page, expect, sync_playwright

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
    page.get_by_label("Пароль", exact=True).fill(password)
    page.get_by_role("button", name="Войти", exact=True).click()
    expect(page.get_by_role("banner").get_by_role("navigation")).to_be_visible()


def upload(page: Page, source: Path) -> None:
    page.get_by_label("Файл DOCX").set_input_files(source)
    page.get_by_label("Заменить рабочий документ", exact=False).check()
    page.get_by_role("button", name="Загрузить DOCX").click()
    expect(page.get_by_text("Загружена версия", exact=False)).to_be_visible()


def place_caret_at_end(block: Locator) -> None:
    block.evaluate("""node => {
        node.closest('[contenteditable]').focus();
        const range = document.createRange();
        range.selectNodeContents(node);
        range.collapse(false);
        window.getSelection().removeAllRanges();
        window.getSelection().addRange(range);
    }""")


def check_editor(page: Page, base: str, directory: Path) -> None:
    work_url = page.url
    thesis_id = urlparse(work_url).path.split("/")[-1]
    document_path = f"{base}/api/v1/theses/{thesis_id}/document"
    document = page.request.get(document_path).json()
    path = f"{base}/api/v1/documents/{document['id']}"
    csrf = {"X-CSRF-Protection": "1"}
    errors: list[str] = []
    page.on("pageerror", lambda error: errors.append(str(error)))

    with page.expect_response(
        lambda response: (
            response.url == f"{path}/edit-lease" and response.request.method == "POST"
        )
    ) as first_lease:
        page.get_by_role("link", name="Редактор", exact=True).click()
    lease_id = first_lease.value.json()["lease_id"]
    root = page.get_by_role("textbox", name="Текст ВКР")
    position = page.get_by_test_id("page-position")
    saved = page.get_by_role("status").filter(has_text="Сохранено")
    expect(root).to_have_attribute("contenteditable", "true")
    expect(position).to_have_text("Лист 1 из 1")
    expect(root.locator("table")).to_be_visible()
    expect(root.locator("img").first).to_be_visible()

    section_text = "Экспериментальный абзац. " * 150
    place_caret_at_end(root.locator(":scope > p").last)
    page.keyboard.press("Enter")
    page.keyboard.insert_text(section_text)
    paragraph = root.locator(":scope > p").last
    expect(paragraph).to_contain_text("Экспериментальный абзац.")
    expect(position).not_to_have_text("Лист 1 из 1")
    assert paragraph.evaluate("node => node.getClientRects().length") > 1
    expect(saved).to_be_visible()
    previous = page.get_by_role("button", name="Предыдущий лист")
    next_sheet = page.get_by_role("button", name="Следующий лист")
    visible_page = position.inner_text()
    (previous if previous.is_enabled() else next_sheet).click()
    expect(position).not_to_have_text(visible_page)
    page.screenshot(path=directory / "editor-pages.png", full_page=True)

    # Select one DOM range that spans multiple physical columns and remove it.
    selected_columns = paragraph.evaluate("""node => {
        const walker = document.createTreeWalker(node, NodeFilter.SHOW_TEXT);
        const start = walker.nextNode();
        let last = start;
        while (walker.nextNode()) last = walker.currentNode;
        const range = document.createRange();
        range.setStart(start, 3);
        range.setEnd(last, last.length - 3);
        window.getSelection().removeAllRanges();
        window.getSelection().addRange(range);
        return new Set([...range.getClientRects()].map(rect => Math.round(rect.left))).size;
    }""")
    assert selected_columns > 1
    page.keyboard.press("Backspace")
    expect(position).to_have_text("Лист 1 из 1")
    expect(saved).to_be_visible()
    page.get_by_role("button", name="Отменить", exact=True).click()
    expect(paragraph).to_contain_text(section_text[:500])
    expect(position).not_to_have_text("Лист 1 из 1")
    expect(saved).to_be_visible()

    second = page.context.new_page()
    second.goto(page.url)
    expect(second.get_by_role("button", name="Получить доступ")).to_be_visible()
    expect(second.get_by_role("textbox", name="Текст ВКР")).to_have_attribute(
        "contenteditable", "false"
    )
    second.close()

    # Simulate another writer on the real API after the editor loses its lease.
    released = page.request.delete(
        f"{path}/edit-lease", headers={**csrf, "X-Edit-Lease": lease_id}
    )
    assert released.status == 204, released.text()
    external = page.request.post(f"{path}/edit-lease", headers=csrf).json()
    external_headers = {**csrf, "X-Edit-Lease": external["lease_id"]}
    fresh = page.request.get(document_path).json()
    server_version = "Серверная редакция в другой вкладке"
    fresh["content"]["root"]["children"].append(
        {
            "type": "paragraph",
            "version": 1,
            "direction": None,
            "format": "",
            "indent": 0,
            "children": [
                {
                    "type": "text",
                    "text": server_version,
                    "version": 1,
                    "style": "",
                    "format": 0,
                    "mode": "normal",
                    "detail": 0,
                }
            ],
        }
    )
    written = page.request.put(
        path,
        headers=external_headers,
        data={
            "content": fresh["content"],
            "schema_version": fresh["schema_version"],
            "template_version_id": fresh["template_version_id"],
            "expected_revision": fresh["revision"],
        },
    )
    assert written.ok, written.text()
    assert (
        page.request.delete(f"{path}/edit-lease", headers=external_headers).status
        == 204
    )
    place_caret_at_end(paragraph)
    local_text = "Черновик после конфликта вкладок"
    page.keyboard.press("Enter")
    page.keyboard.insert_text(local_text)
    expect(page.get_by_text("Сохранение приостановлено", exact=True)).to_be_visible()
    page.get_by_role("button", name="Перечитать с сервера").click()
    expect(root).to_contain_text(server_version)
    expect(root).not_to_contain_text(local_text)
    page.get_by_role("button", name="Восстановить черновик").click()
    expect(root).to_contain_text(local_text)
    expect(saved).to_be_visible()

    page.get_by_role("button", name="Сохранить версию").click()
    version = page.get_by_role("link", name="версия №", exact=False).first
    expect(version).to_be_visible()
    version_url = version.get_attribute("href")
    assert version_url
    page.reload()
    expect(root).to_have_attribute("contenteditable", "true")
    expect(root).to_contain_text(local_text)

    place_caret_at_end(root.locator(":scope > p").last)
    page.keyboard.press("Enter")
    page.keyboard.insert_text("Добавлено в редакторе")
    page.get_by_label("Стиль блока").select_option("h2")
    expect(root.locator("h2").last).to_have_text("Добавлено в редакторе")
    page.get_by_role("button", name="Таблица", exact=True).click()
    expect(root.locator("table")).to_have_count(2)
    with ZipFile(FIXTURE) as fixture:
        image = fixture.read(
            next(name for name in fixture.namelist() if name.startswith("word/media/"))
        )
    with page.expect_file_chooser() as chooser:
        page.get_by_role("button", name="Изображение", exact=True).click()
    chooser.value.set_files(
        {"name": "figure.png", "mimeType": "image/png", "buffer": image}
    )
    expect(root.get_by_role("img", name="figure.png")).to_be_visible()
    expect(saved).to_be_visible()

    viewport = page.viewport_size
    page.set_viewport_size({"width": 390, "height": 844})
    page.get_by_label("Масштаб").select_option("fit")
    assert page.evaluate("document.documentElement.scrollWidth === innerWidth")
    page.screenshot(path=directory / "editor-mobile.png", full_page=True)
    if viewport:
        page.set_viewport_size(viewport)
    with page.expect_response(
        lambda response: (
            response.url == f"{path}/edit-lease" and response.request.method == "DELETE"
        )
    ):
        page.get_by_role("link", name="К работе").click()
    page.goto(base + version_url)
    page.get_by_text("Восстановить версию", exact=True).click()
    page.get_by_role("button", name="Подтвердить восстановление").click()
    expect(root).to_have_attribute("contenteditable", "true")
    expect(root).to_contain_text(local_text)
    expect(root).not_to_contain_text("Добавлено в редакторе")
    with page.expect_response(
        lambda response: (
            response.url == f"{path}/edit-lease" and response.request.method == "DELETE"
        )
    ):
        page.get_by_role("link", name="К работе").click()
    expect(page.get_by_role("link", name="Редактор", exact=True)).to_be_visible()
    assert not errors, errors


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
    user.get_by_label("Фамилия", exact=True).fill("Демонстрационный")
    user.get_by_label("Имя", exact=True).fill("Студент")
    user.get_by_label("Учебная группа").fill("ТЕСТ-26")
    user.get_by_label("Электронная почта").fill(student_email)
    user.locator('input[autocomplete="new-password"]').first.fill(password)
    user.get_by_label("Повторите пароль").fill("Несовпадающий пароль")
    expect(user.get_by_text("Пароли не совпадают.")).to_be_visible()
    user.get_by_label("Показать пароль").check()
    expect(user.locator('input[autocomplete="new-password"]').first).to_have_attribute(
        "type", "text"
    )
    user.get_by_label("Повторите пароль").fill(password)
    user.get_by_label("Показать пароль").uncheck()
    user.get_by_role("button", name="Создать аккаунт").click()
    expect(user.get_by_text("Аккаунт создан", exact=False)).to_be_visible()
    login(user, args.base, student_email, password)
    expect(
        user.get_by_text("Руководитель ещё не назначил вам тему ВКР.")
    ).to_be_visible()
    expect(user).to_have_url(f"{args.base}/works")
    expect(user.get_by_role("navigation", name="Кабинет студента")).to_be_visible()

    account = user.get_by_label("Меню профиля")
    account.focus()
    account.press("Enter")
    expect(user.get_by_role("link", name="Мой профиль")).to_be_visible()
    account.press("Escape")
    expect(account).to_be_focused()
    account.click()
    user.get_by_role("link", name="Мой профиль").click()
    expect(
        user.get_by_role("main").get_by_text(student_email, exact=True)
    ).to_be_visible()
    expect(user.get_by_role("main").get_by_text("ТЕСТ-26", exact=True)).to_be_visible()
    expect(
        user.get_by_role("main").get_by_text("Демонстрационный Студент")
    ).to_be_visible()
    user.screenshot(path=directory / "profile.png")
    tabs = user.get_by_role("navigation", name="Разделы профиля")
    tabs.get_by_role("link", name="Безопасность").click()
    expect(user.get_by_role("heading", name="Пароль")).to_be_visible()
    tabs.get_by_role("link", name="Уведомления").click()
    expect(user.get_by_role("heading", name="Уведомления по почте")).to_be_visible()
    user.get_by_role("link", name="Моя ВКР").click()

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

    user.get_by_role("button", name="Проверить назначение").click()
    expect(user).to_have_url(work_url)
    user.get_by_label("Шаблон оформления").select_option(label="ГОСТ 7.32-2017")
    user.get_by_role("button", name="Создать документ").click()
    upload(user, first_doc)
    if args.editor:
        check_editor(user, args.base, directory)
        upload(user, first_doc)
    user.get_by_role("button", name="Отправить на проверку").click()
    expect(
        user.locator("li[data-status]").get_by_text("На проверке", exact=True)
    ).to_be_visible()
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
    expect(
        supervisor.locator("li[data-status]").get_by_text("Нужны правки", exact=True)
    ).to_be_visible()

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
    expect(
        user.locator("li[data-status]").get_by_text("На проверке", exact=True)
    ).to_be_visible()
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
    user.get_by_label("Меню профиля").click()
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
    parser.add_argument("--editor", action="store_true")
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
