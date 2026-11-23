"""SOAP 1.1 subset of the Antiplagiat ApiCorp WSDL."""

from base64 import b64encode
from dataclasses import dataclass
from http.client import HTTPException
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree.ElementTree import Element, ParseError, SubElement, tostring

from defusedxml.common import DefusedXmlException
from defusedxml.ElementTree import fromstring

from app.api_v1.plagiarism.schemas import CheckReport
from app.core.config import Settings

SOAP = "http://schemas.xmlsoap.org/soap/envelope/"
API = "http://www.antiplagiat.ru/3.0/apicorp"
MAX_RESPONSE_BYTES = 256 * 1024  # Only small SOAP metadata responses are expected.


class ProviderError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ProviderStatus:
    wait_seconds: int | None = None
    report: CheckReport | None = None


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(
        self, req: Request, fp: object, code: int, msg: str, headers: object, newurl: str
    ) -> None:
        return None


def tag(name: str) -> str:
    return f"{{{API}}}{name}"


def field(parent: Element, name: str, value: str) -> Element:
    element = SubElement(parent, tag(name))
    element.text = value
    return element


def value(parent: Element, name: str) -> str:
    return parent.findtext(tag(name), "").strip()


def required(parent: Element, name: str) -> Element:
    element = parent.find(tag(name))
    if element is None:
        raise ProviderError("invalid_response", "Antiplagiat response is missing required data")
    return element


def number(raw: str) -> int | None:
    if raw.isascii() and raw.isdecimal() and len(raw) <= 10:
        result = int(raw)
        if result <= 2**31 - 1:
            return result
    return None


def percentage(parent: Element | None, name: str) -> float | None:
    if parent is None:
        return None
    try:
        result = float(value(parent, name))
    except ValueError:
        return None
    return result if 0 <= result <= 100 else None


class AntiplagiatClient:
    def __init__(self, settings: Settings) -> None:
        self.endpoint = str(settings.plagiarism_wsdl_url).split("?", 1)[0]
        self.site = str(settings.plagiarism_site_url).rstrip("/")
        self.timeout = settings.plagiarism_request_timeout_seconds
        self.credentials = (
            settings.plagiarism_login.get_secret_value(),
            settings.plagiarism_password.get_secret_value(),
        )

    def safe_detail(self, detail: str, fallback: str) -> str:
        for secret in self.credentials:
            if secret:
                detail = detail.replace(secret, "[redacted]")
        detail = " ".join(detail.split()).replace("\x00", "")
        return detail[:1000] or fallback

    def send(self, request: Request) -> bytes:
        opener = build_opener(NoRedirects())
        try:
            with opener.open(request, timeout=self.timeout) as response:
                return response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            with exc:
                if exc.code == 500:
                    return exc.read(MAX_RESPONSE_BYTES + 1)  # SOAP fault
                raise ProviderError(
                    "provider_http", f"Antiplagiat returned HTTP {exc.code}"
                ) from None
        except (URLError, OSError, HTTPException):
            raise ProviderError("provider_connection", "Could not reach Antiplagiat") from None

    def call(self, operation: Element) -> Element:
        name = operation.tag.split("}", 1)[1]
        envelope = Element(f"{{{SOAP}}}Envelope")
        SubElement(envelope, f"{{{SOAP}}}Body").append(operation)
        auth = b64encode(":".join(self.credentials).encode()).decode("ascii")
        request = Request(
            self.endpoint,
            data=tostring(envelope, encoding="utf-8", xml_declaration=True),
            headers={
                "Content-Type": "text/xml; charset=utf-8",
                "SOAPAction": f'"{API}/IApiCorp/{name}"',
                "Authorization": f"Basic {auth}",
            },
            method="POST",
        )
        try:
            payload = self.send(request)
            if len(payload) > MAX_RESPONSE_BYTES:
                raise ProviderError("invalid_response", "Antiplagiat response exceeds local limit")
            root = fromstring(payload, forbid_dtd=True)
        except (ParseError, DefusedXmlException):
            raise ProviderError("invalid_response", "Invalid Antiplagiat SOAP response") from None
        body = root.find(f"{{{SOAP}}}Body")
        if body is None:
            raise ProviderError("invalid_response", "Missing Antiplagiat SOAP body")
        fault = body.find(f"{{{SOAP}}}Fault")
        if fault is not None:
            detail = self.safe_detail(fault.findtext("faultstring", ""), "Antiplagiat SOAP fault")
            raise ProviderError("provider_fault", detail)
        # CheckDocument's WSDL output message has no parts.
        if name == "CheckDocument" and len(body) == 0:
            return body
        return required(body, f"{name}Response")

    def upload(self, data: bytes, external_user_id: str) -> int:
        operation = Element(tag("UploadDocument"))
        document = SubElement(operation, tag("data"))
        field(document, "FileName", "norma-demo")
        field(document, "FileType", ".txt")
        field(document, "Data", b64encode(data).decode("ascii"))
        field(document, "Encoding", "utf-8")
        field(document, "ExternalUserID", external_user_id)
        field(SubElement(operation, tag("options")), "AddToIndex", "false")
        result = required(self.call(operation), "UploadDocumentResult")
        uploaded = required(result, "Uploaded")
        reason = value(uploaded, "Reason")
        if reason != "NoError":
            detail = self.safe_detail(
                value(uploaded, "FailDetails") or reason, "Antiplagiat rejected the document"
            )
            raise ProviderError("upload_rejected", detail)
        external_id = number(value(required(uploaded, "Id"), "Id"))
        if not external_id:
            raise ProviderError("invalid_response", "Antiplagiat did not return a document ID")
        return external_id

    def document_operation(self, name: str, external_id: int) -> Element:
        operation = Element(tag(name))
        field(SubElement(operation, tag("docId")), "Id", str(external_id))
        return operation

    def start(self, external_id: int) -> None:
        self.call(self.document_operation("CheckDocument", external_id))

    def poll(self, external_id: int) -> ProviderStatus:
        result = required(
            self.call(self.document_operation("GetCheckStatus", external_id)),
            "GetCheckStatusResult",
        )
        status = value(result, "Status")
        if status in {"InProgress", "None"}:
            return ProviderStatus(wait_seconds=number(value(result, "EstimatedWaitTime")))
        if status == "Failed":
            raise ProviderError(
                "check_rejected",
                self.safe_detail(value(result, "FailDetails"), "Antiplagiat check failed"),
            )
        if status != "Ready":
            raise ProviderError("invalid_response", "Unknown Antiplagiat check status")
        summary = result.find(tag("Summary"))
        if summary is None:
            report = required(
                self.call(self.document_operation("GetReportView", external_id)),
                "GetReportViewResult",
            )
            summary = required(report, "Summary")
        scores = summary.find(tag("DetailedScore"))
        suspicious = value(summary, "IsSuspicious")
        return ProviderStatus(
            report=CheckReport(
                report_number=number(value(summary, "ReportNum")),
                originality_percent=percentage(scores, "Unknown"),
                similarity_percent=percentage(scores, "Plagiarism"),
                citation_percent=percentage(scores, "Legal"),
                self_citation_percent=percentage(scores, "SelfCite"),
                is_suspicious={"true": True, "false": False, "1": True, "0": False}.get(suspicious),
                short_report_url=self.report_url(value(summary, "ShortReportWebId")),
                readonly_report_url=self.report_url(value(summary, "ReadonlyReportWebId")),
            )
        )

    def report_url(self, path: str) -> str | None:
        if not path.startswith("/") or path.startswith("//") or "\\" in path:
            return None
        if any(ord(char) <= 32 or ord(char) == 127 for char in path) or len(path) > 2048:
            return None
        target = self.site + path
        return target if urlsplit(target).netloc == urlsplit(self.site).netloc else None
