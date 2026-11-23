from base64 import b64decode
from urllib.request import Request
from xml.etree.ElementTree import fromstring

import pytest
from pydantic import SecretStr

from app.api_v1.plagiarism.client import API, SOAP, AntiplagiatClient, ProviderError, tag
from app.core.config import Settings


def envelope(body: str) -> bytes:
    return (
        f'<s:Envelope xmlns:s="{SOAP}" xmlns="{API}"><s:Body>{body}</s:Body></s:Envelope>'
    ).encode()


def test_api_corp_soap_sequence_including_void_check_response(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = AntiplagiatClient(settings)
    responses = iter(
        [
            envelope(
                "<UploadDocumentResponse><UploadDocumentResult><Uploaded><Id><Id>42</Id></Id>"
                "<Reason>NoError</Reason></Uploaded></UploadDocumentResult></UploadDocumentResponse>"
            ),
            envelope(""),
            envelope(
                "<GetCheckStatusResponse><GetCheckStatusResult><Status>InProgress</Status>"
                "<EstimatedWaitTime>13</EstimatedWaitTime>"
                "</GetCheckStatusResult></GetCheckStatusResponse>"
            ),
            envelope(
                "<GetCheckStatusResponse><GetCheckStatusResult><Status>Ready</Status><Summary>"
                "<ReportNum>1</ReportNum><ShortReportWebId>/report/42</ShortReportWebId>"
                "<ReadonlyReportWebId>//example.org/report</ReadonlyReportWebId>"
                "<IsSuspicious>false</IsSuspicious>"
                "<DetailedScore><Unknown>91.5</Unknown><Plagiarism>2.5</Plagiarism>"
                "<Legal>4</Legal><SelfCite>2</SelfCite></DetailedScore>"
                "</Summary></GetCheckStatusResult></GetCheckStatusResponse>"
            ),
        ]
    )
    requests: list[Request] = []

    def send(request: Request) -> bytes:
        requests.append(request)
        return next(responses)

    monkeypatch.setattr(client, "send", send)
    document = "Синтетический текст".encode()
    external_user = "d7b285b9-fd1e-40b1-90ee-bef182cb9cf0"
    assert client.upload(document, external_user) == 42
    client.start(42)
    assert client.poll(42).wait_seconds == 13
    result = client.poll(42).report
    assert result is not None and result.originality_percent == 91.5
    assert (result.similarity_percent, result.citation_percent, result.self_citation_percent) == (
        2.5,
        4,
        2,
    )
    assert result.short_report_url == "https://testapi.antiplagiat.ru/report/42"
    assert result.readonly_report_url is None
    assert result.is_suspicious is False
    upload = requests[0]
    assert upload.get_header("Soapaction") == f'"{API}/IApiCorp/UploadDocument"'
    assert isinstance(upload.data, bytes)
    root = fromstring(upload.data)
    assert b64decode(root.findtext(f".//{tag('Data')}", "")) == document
    assert root.findtext(f".//{tag('ExternalUserID')}") == external_user
    assert root.findtext(f".//{tag('FileType')}") == ".txt"
    assert root.findtext(f".//{tag('AddToIndex')}") == "false"


def test_provider_failure_keeps_detail_and_redacts_credentials(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = AntiplagiatClient(
        settings.model_copy(update={"plagiarism_password": SecretStr("test-secret")})
    )

    def rejected(_request: Request) -> bytes:
        return envelope(
            "<GetCheckStatusResponse><GetCheckStatusResult><Status>Failed</Status>"
            "<FailDetails>Unexpected response for test-secret</FailDetails>"
            "</GetCheckStatusResult></GetCheckStatusResponse>"
        )

    monkeypatch.setattr(client, "send", rejected)
    with pytest.raises(ProviderError, match="Unexpected response for \\[redacted\\]") as error:
        client.poll(42)
    assert error.value.code == "check_rejected"
