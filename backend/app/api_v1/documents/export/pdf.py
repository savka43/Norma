import os
import shutil
import signal
import subprocess
from pathlib import Path
from tempfile import TemporaryDirectory

from app.api_v1.formatting.schemas import TemplateParameters


def font_substitutions(parameters: TemplateParameters) -> bool:
    matcher = shutil.which("fc-match")
    if matcher is None:
        return True
    fonts = {
        style.font_family
        for style in [
            parameters.body,
            *parameters.headings,
            parameters.caption,
            parameters.list,
            parameters.table,
        ]
    }
    for font in sorted(fonts):
        try:
            result = subprocess.run(
                [matcher, "--format=%{family}", "--", font],
                capture_output=True,
                text=True,
                timeout=3,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired):
            return True
        if result.returncode != 0 or font.casefold() not in {
            family.strip().casefold() for family in result.stdout.split(",")
        }:
            return True
    return False


class ConversionUnavailable(Exception):
    pass


class ConversionFailed(Exception):
    pass


def render_pdf(docx: bytes, executable: str, timeout: int, max_bytes: int) -> bytes:
    converter = shutil.which(executable)
    if converter is None:
        raise ConversionUnavailable("PDF converter is not installed")
    with TemporaryDirectory(prefix="norma-export-") as directory:
        root = Path(directory)
        source = root / "document.docx"
        source.write_bytes(docx)
        profile = root / "profile"
        environment = {**os.environ, "HOME": str(root), "SAL_USE_VCLPLUGIN": "svp"}
        try:
            process = subprocess.Popen(
                [
                    converter,
                    f"-env:UserInstallation={profile.as_uri()}",
                    "--headless",
                    "--nologo",
                    "--nodefault",
                    "--norestore",
                    "--nolockcheck",
                    "--convert-to",
                    "pdf:writer_pdf_Export",
                    "--outdir",
                    str(root),
                    str(source),
                ],
                env=environment,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            try:
                process.communicate(timeout=timeout)
            except subprocess.TimeoutExpired:
                # LibreOffice's launcher can spawn soffice.bin. Kill the entire
                # private process group, then reap before deleting the workspace.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                process.communicate()
                raise
        except (subprocess.TimeoutExpired, OSError) as exc:
            raise ConversionFailed("PDF conversion failed or timed out") from exc
        output = root / "document.pdf"
        if process.returncode != 0 or not output.is_file():
            raise ConversionFailed("PDF conversion did not produce a file")
        if output.stat().st_size > max_bytes:
            raise ConversionFailed("PDF output size limit exceeded")
        data = output.read_bytes()
        if not data.startswith(b"%PDF-"):
            raise ConversionFailed("Invalid PDF output")
        return data
