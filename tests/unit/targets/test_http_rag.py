import asyncio
import json
import socket
from uuid import UUID

import httpx
import pytest

from app.domain.evaluation import EvaluationCase, ExecutionContext
from app.targets.base import (
    InvalidTargetConfiguration,
    TargetExecutionError,
    TargetHTTPError,
    TargetTimeoutError,
)
from app.targets.http_rag import HTTPRAGTarget

RUN_ID = UUID("00000000-0000-0000-0000-000000000601")
JOB_ID = UUID("00000000-0000-0000-0000-000000000701")
ATTEMPT_ID = UUID("00000000-0000-0000-0000-000000000801")


class StaticResolver:
    def __init__(self, *addresses: str) -> None:
        self.addresses = addresses

    async def resolve(self, hostname: str) -> tuple[str, ...]:
        assert hostname == "rag.example.com"
        return self.addresses


class RebindingResolver:
    def __init__(self) -> None:
        self.call_count = 0

    async def resolve(self, hostname: str) -> tuple[str, ...]:
        assert hostname == "rag.example.com"
        self.call_count += 1
        if self.call_count == 1:
            return ("93.184.216.34",)
        return ("127.0.0.1",)


class FailingResolver:
    async def resolve(self, hostname: str) -> tuple[str, ...]:
        raise socket.gaierror(f"resolver failed for {hostname}")


class TimingOutResolver:
    async def resolve(self, hostname: str) -> tuple[str, ...]:
        raise TimeoutError(f"resolver timed out for {hostname}")


class NeverResolvingResolver:
    async def resolve(self, hostname: str) -> tuple[str, ...]:
        await asyncio.Event().wait()
        raise AssertionError(f"unreachable resolver completion for {hostname}")


class StaticPeerStream:
    def __init__(self, address: str, port: int = 443) -> None:
        self.address = address
        self.port = port

    def get_extra_info(self, info: str) -> object:
        if info == "server_addr":
            return (self.address, self.port)
        return None


class ExpiringPeerStream(StaticPeerStream):
    def __init__(self, address: str, port: int = 443) -> None:
        super().__init__(address, port)
        self.available = True

    def get_extra_info(self, info: str) -> object:
        if not self.available:
            return None
        return super().get_extra_info(info)


class RaisingPeerStream:
    def get_extra_info(self, info: str) -> object:
        raise RuntimeError(f"peer lookup failed for {info}: private-transport-detail")


class BodyThatClosesPeer(httpx.AsyncByteStream):
    def __init__(self, peer: ExpiringPeerStream) -> None:
        self.peer = peer

    async def __aiter__(self):
        self.peer.available = False
        yield b'{"answer":"checked-before-read"}'

    async def aclose(self) -> None:
        return None


def context() -> ExecutionContext:
    return ExecutionContext(
        run_id=RUN_ID,
        job_id=JOB_ID,
        attempt_id=ATTEMPT_ID,
        attempt_number=1,
        worker_id="worker-1",
        cancellation=asyncio.Event(),
    )


def registered_config(**overrides: object) -> dict[str, object]:
    config: dict[str, object] = {
        "target_id": "rag-production",
        "base_url": "https://rag.example.com",
        "endpoint": "/query",
        "allowed_hosts": ["rag.example.com"],
    }
    config.update(overrides)
    return config


def test_http_target_rejects_legacy_snapshot_without_target_id() -> None:
    legacy_config = registered_config()
    del legacy_config["target_id"]

    with pytest.raises(InvalidTargetConfiguration):
        HTTPRAGTarget(legacy_config)


@pytest.mark.parametrize(
    "config",
    [
        registered_config(base_url="http://rag.example.com"),
        registered_config(base_url="https://localhost", allowed_hosts=["localhost"]),
        registered_config(endpoint="https://evil.example/query"),
        registered_config(authentication={"bearer": "plaintext-secret"}),
    ],
)
def test_http_target_rejects_unsafe_url_configuration(config: dict[str, object]) -> None:
    with pytest.raises(InvalidTargetConfiguration):
        HTTPRAGTarget(config)


def test_http_target_rejects_custom_https_port() -> None:
    with pytest.raises(InvalidTargetConfiguration):
        HTTPRAGTarget(registered_config(base_url="https://rag.example.com:8443"))


def test_http_target_rejects_url_userinfo() -> None:
    with pytest.raises(InvalidTargetConfiguration):
        HTTPRAGTarget(registered_config(base_url="https://operator:secret@rag.example.com"))


def test_http_target_rejects_percent_encoded_ip_hostname() -> None:
    with pytest.raises(InvalidTargetConfiguration):
        HTTPRAGTarget(
            registered_config(
                base_url="https://%31%32%37.0.0.1",
                allowed_hosts=["%31%32%37.0.0.1"],
            )
        )


def test_http_target_rejects_decimal_ip_hostname() -> None:
    with pytest.raises(InvalidTargetConfiguration):
        HTTPRAGTarget(
            registered_config(
                base_url="https://2130706433",
                allowed_hosts=["2130706433"],
            )
        )


def test_http_target_rejects_unicode_idna_hostname() -> None:
    with pytest.raises(InvalidTargetConfiguration):
        HTTPRAGTarget(
            registered_config(
                base_url="https://éxample.com",
                allowed_hosts=["éxample.com"],
            )
        )


def test_http_target_accepts_operator_normalized_ascii_punycode_hostname() -> None:
    HTTPRAGTarget(
        registered_config(
            base_url="https://xn--xample-9ua.com",
            allowed_hosts=["xn--xample-9ua.com"],
        )
    )


@pytest.mark.parametrize(
    ("base_url", "allowed_host"),
    [
        ("https://224.0.0.1", "224.0.0.1"),
        ("https://[::ffff:8.8.8.8]", "::ffff:8.8.8.8"),
    ],
)
def test_http_target_rejects_disallowed_ip_literal_forms(
    base_url: str,
    allowed_host: str,
) -> None:
    with pytest.raises(InvalidTargetConfiguration):
        HTTPRAGTarget(registered_config(base_url=base_url, allowed_hosts=[allowed_host]))


def test_http_target_rejects_overlong_hostname_label() -> None:
    hostname = f"{'a' * 64}.example.com"

    with pytest.raises(InvalidTargetConfiguration):
        HTTPRAGTarget(registered_config(base_url=f"https://{hostname}", allowed_hosts=[hostname]))


def test_http_target_rejects_overlong_hostname() -> None:
    hostname = ".".join(["a" * 63] * 4)

    with pytest.raises(InvalidTargetConfiguration):
        HTTPRAGTarget(registered_config(base_url=f"https://{hostname}", allowed_hosts=[hostname]))


@pytest.mark.parametrize(
    "hostname",
    [
        "rag.example.com.evil.test",
        "evil.rag.example.com",
        "rag-example.com",
    ],
)
def test_http_target_requires_exact_allowed_hostname(hostname: str) -> None:
    with pytest.raises(InvalidTargetConfiguration):
        HTTPRAGTarget(registered_config(base_url=f"https://{hostname}"))


def test_http_target_rejects_control_characters_in_endpoint() -> None:
    with pytest.raises(InvalidTargetConfiguration):
        HTTPRAGTarget(registered_config(endpoint="/query\r\nHost: 127.0.0.1"))


def test_http_target_configuration_error_does_not_chain_plaintext_secret() -> None:
    secret = "plaintext-secret-that-must-not-be-logged"

    with pytest.raises(InvalidTargetConfiguration) as caught:
        HTTPRAGTarget(registered_config(authentication={"bearer": secret}))

    assert secret not in str(caught.value)
    assert secret not in repr(caught.value)
    assert caught.value.__cause__ is None


async def test_http_target_resolves_public_ip_maps_request_and_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("RAG_TEST_TOKEN", "secret-value")

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://93.184.216.34/v1/query")
        assert request.headers["Host"] == "rag.example.com"
        assert request.headers["Authorization"] == "Bearer secret-value"
        assert request.headers["X-EvalOps-Job-ID"] == str(JOB_ID)
        assert json.loads(request.content) == {"prompt": "What is 2 + 2?"}
        return httpx.Response(
            200,
            json={
                "data": {
                    "answer": "4",
                    "citations": [{"source_id": "math"}],
                    "sources": [{"id": "math", "visible": True}],
                    "trace": {"request_id": "upstream-1"},
                    "usage": {"input_tokens": 10, "output_tokens": 1},
                }
            },
            extensions={"network_stream": StaticPeerStream("93.184.216.34")},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        target = HTTPRAGTarget(
            registered_config(
                endpoint="/v1/query",
                auth_env_var="RAG_TEST_TOKEN",
                request_question_field="prompt",
                answer_path="data.answer",
                citations_path="data.citations",
                sources_path="data.sources",
                trace_path="data.trace",
                usage_path="data.usage",
            ),
            client=client,
            resolver=StaticResolver("93.184.216.34"),
        )
        result = await target.execute_case(
            EvaluationCase(
                case_id="case-1",
                question="What is 2 + 2?",
                expected_answer="4",
                metadata={},
            ),
            context(),
        )

    assert result.answer == "4"
    assert result.citations == ({"source_id": "math"},)
    assert result.token_usage is not None
    assert result.token_usage.output_tokens == 1


async def test_http_target_connects_to_validated_ip_with_original_host_and_sni() -> None:
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == httpx.URL("https://93.184.216.34/query")
        assert request.headers["Host"] == "rag.example.com"
        assert request.extensions["sni_hostname"] == "rag.example.com"
        return httpx.Response(
            200,
            json={"answer": "pinned"},
            extensions={"network_stream": StaticPeerStream("93.184.216.34")},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        target = HTTPRAGTarget(
            registered_config(),
            client=client,
            resolver=StaticResolver("93.184.216.34"),
        )

        result = await target.execute_case(
            EvaluationCase(
                case_id="case-pinned-ip",
                question="q",
                expected_answer=None,
                metadata={},
            ),
            context(),
        )

    assert result.answer == "pinned"


async def test_http_target_is_not_re_resolved_after_public_dns_validation() -> None:
    resolver = RebindingResolver()

    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "93.184.216.34"
        return httpx.Response(
            200,
            json={"answer": "no-rebind"},
            extensions={"network_stream": StaticPeerStream("93.184.216.34")},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        target = HTTPRAGTarget(
            registered_config(),
            client=client,
            resolver=resolver,
        )

        result = await target.execute_case(
            EvaluationCase(
                case_id="case-dns-rebinding",
                question="q",
                expected_answer=None,
                metadata={},
            ),
            context(),
        )

    assert result.answer == "no-rebind"
    assert resolver.call_count == 1


async def test_http_target_redacts_dns_resolution_failure() -> None:
    target = HTTPRAGTarget(
        registered_config(),
        resolver=FailingResolver(),
    )

    with pytest.raises(TargetExecutionError) as caught:
        await target.execute_case(
            EvaluationCase(
                case_id="case-dns-error",
                question="q",
                expected_answer=None,
                metadata={},
            ),
            context(),
        )

    assert caught.value.code == "target_dns_error"
    assert caught.value.retryable is True
    assert "rag.example.com" not in str(caught.value)


async def test_http_target_maps_dns_timeout_to_target_timeout() -> None:
    target = HTTPRAGTarget(
        registered_config(),
        resolver=TimingOutResolver(),
    )

    with pytest.raises(TargetTimeoutError):
        await target.execute_case(
            EvaluationCase(
                case_id="case-dns-timeout",
                question="q",
                expected_answer=None,
                metadata={},
            ),
            context(),
        )


async def test_http_target_applies_configured_timeout_to_dns_resolution() -> None:
    target = HTTPRAGTarget(
        registered_config(timeout_seconds=0.01),
        resolver=NeverResolvingResolver(),
    )

    with pytest.raises(TargetTimeoutError):
        await asyncio.wait_for(
            target.execute_case(
                EvaluationCase(
                    case_id="case-dns-deadline",
                    question="q",
                    expected_answer=None,
                    metadata={},
                ),
                context(),
            ),
            timeout=0.5,
        )


async def test_http_target_rejects_actual_peer_outside_validated_addresses() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"answer": "unsafe-peer"},
            extensions={"network_stream": StaticPeerStream("127.0.0.1")},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        target = HTTPRAGTarget(
            registered_config(),
            client=client,
            resolver=StaticResolver("93.184.216.34"),
        )

        with pytest.raises(TargetExecutionError, match="peer"):
            await target.execute_case(
                EvaluationCase(
                    case_id="case-peer-mismatch",
                    question="q",
                    expected_answer=None,
                    metadata={},
                ),
                context(),
            )


async def test_http_target_rejects_different_public_peer() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"answer": "wrong-public-peer"},
            extensions={"network_stream": StaticPeerStream("1.1.1.1")},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        target = HTTPRAGTarget(
            registered_config(),
            client=client,
            resolver=StaticResolver("93.184.216.34"),
        )

        with pytest.raises(TargetExecutionError, match="peer"):
            await target.execute_case(
                EvaluationCase(
                    case_id="case-different-public-peer",
                    question="q",
                    expected_answer=None,
                    metadata={},
                ),
                context(),
            )


async def test_http_target_fails_closed_when_peer_metadata_is_unavailable() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"answer": "missing-peer"})
        )
    ) as client:
        target = HTTPRAGTarget(
            registered_config(),
            client=client,
            resolver=StaticResolver("93.184.216.34"),
        )

        with pytest.raises(TargetExecutionError, match="peer"):
            await target.execute_case(
                EvaluationCase(
                    case_id="case-missing-peer",
                    question="q",
                    expected_answer=None,
                    metadata={},
                ),
                context(),
            )


async def test_http_target_redacts_peer_metadata_lookup_failure() -> None:
    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"answer": "unreachable"},
            extensions={"network_stream": RaisingPeerStream()},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        target = HTTPRAGTarget(
            registered_config(),
            client=client,
            resolver=StaticResolver("93.184.216.34"),
        )

        with pytest.raises(TargetExecutionError) as caught:
            await target.execute_case(
                EvaluationCase(
                    case_id="case-peer-lookup-failure",
                    question="q",
                    expected_answer=None,
                    metadata={},
                ),
                context(),
            )

    assert caught.value.code == "target_peer_mismatch"
    assert caught.value.retryable is False
    assert "private-transport-detail" not in str(caught.value)
    assert caught.value.__cause__ is None


async def test_http_target_checks_peer_before_reading_response_body() -> None:
    peer = ExpiringPeerStream("93.184.216.34")

    async def handler(_: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            stream=BodyThatClosesPeer(peer),
            extensions={"network_stream": peer},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        target = HTTPRAGTarget(
            registered_config(),
            client=client,
            resolver=StaticResolver("93.184.216.34"),
        )

        result = await target.execute_case(
            EvaluationCase(
                case_id="case-peer-before-body",
                question="q",
                expected_answer=None,
                metadata={},
            ),
            context(),
        )

    assert result.answer == "checked-before-read"


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "169.254.169.254",
        "0.0.0.0",
        "224.0.0.1",
        "192.0.2.1",
        "::1",
        "fc00::1",
        "fe80::1",
        "::",
        "ff02::1",
    ],
)
async def test_http_target_rejects_non_public_dns_resolution(address: str) -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200))
    ) as client:
        target = HTTPRAGTarget(
            registered_config(),
            client=client,
            resolver=StaticResolver(address),
        )
        with pytest.raises(InvalidTargetConfiguration, match="public"):
            await target.execute_case(
                EvaluationCase(
                    case_id="case-private",
                    question="q",
                    expected_answer=None,
                    metadata={},
                ),
                context(),
            )


async def test_http_target_rejects_mixed_public_and_private_dns_answers() -> None:
    request_reached_transport = False

    async def handler(_: httpx.Request) -> httpx.Response:
        nonlocal request_reached_transport
        request_reached_transport = True
        return httpx.Response(200)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        target = HTTPRAGTarget(
            registered_config(),
            client=client,
            resolver=StaticResolver("93.184.216.34", "10.0.0.8"),
        )

        with pytest.raises(InvalidTargetConfiguration, match="public"):
            await target.execute_case(
                EvaluationCase(
                    case_id="case-mixed-dns",
                    question="q",
                    expected_answer=None,
                    metadata={},
                ),
                context(),
            )

    assert request_reached_transport is False


async def test_http_target_rejects_ipv4_mapped_ipv6_dns_answer() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"answer": "unsafe"}))
    ) as client:
        target = HTTPRAGTarget(
            registered_config(),
            client=client,
            resolver=StaticResolver("::ffff:93.184.216.34"),
        )

        with pytest.raises(InvalidTargetConfiguration, match="public"):
            await target.execute_case(
                EvaluationCase(
                    case_id="case-ipv4-mapped-ipv6",
                    question="q",
                    expected_answer=None,
                    metadata={},
                ),
                context(),
            )


async def test_http_target_allows_native_public_ipv6_dns_answer() -> None:
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(
                200,
                json={"answer": "ok"},
                extensions={
                    "network_stream": StaticPeerStream("2606:2800:220:1:248:1893:25c8:1946")
                },
            )
        )
    ) as client:
        target = HTTPRAGTarget(
            registered_config(),
            client=client,
            resolver=StaticResolver("2606:2800:220:1:248:1893:25c8:1946"),
        )

        result = await target.execute_case(
            EvaluationCase(
                case_id="case-native-ipv6",
                question="q",
                expected_answer=None,
                metadata={},
            ),
            context(),
        )

    assert result.answer == "ok"


async def test_http_target_does_not_follow_redirect_to_metadata_address() -> None:
    requested_urls: list[httpx.URL] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        requested_urls.append(request.url)
        if len(requested_urls) == 1:
            return httpx.Response(
                302,
                headers={"Location": "http://169.254.169.254/latest/meta-data"},
                extensions={"network_stream": StaticPeerStream("93.184.216.34")},
            )
        return httpx.Response(200, json={"answer": "metadata-secret"})

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        follow_redirects=True,
    ) as client:
        target = HTTPRAGTarget(
            registered_config(),
            client=client,
            resolver=StaticResolver("93.184.216.34"),
        )

        with pytest.raises(TargetHTTPError, match="HTTP 302"):
            await target.execute_case(
                EvaluationCase(
                    case_id="case-redirect",
                    question="q",
                    expected_answer=None,
                    metadata={},
                ),
                context(),
            )

    assert requested_urls == [httpx.URL("https://93.184.216.34/query")]
