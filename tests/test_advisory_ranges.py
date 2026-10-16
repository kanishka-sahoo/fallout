"""OSV range events -> npm semver ranges (DECISIONS D17), and package-spec parsing for
exposure_path package targets (D18)."""

import pytest

from fallout.advisory import advisory_kind, osv_range
from fallout.tools import repo_key, split_spec


@pytest.mark.parametrize(
    ("events", "expected"),
    [
        ([{"introduced": "0"}, {"fixed": "4.17.21"}], ">=0.0.0 <4.17.21"),
        (
            [{"introduced": "0"}, {"fixed": "5.7.2"}, {"introduced": "6.0.0"}, {"fixed": "6.3.1"}],
            ">=0.0.0 <5.7.2 || >=6.0.0 <6.3.1",
        ),
        ([{"introduced": "1.0.0"}, {"last_affected": "1.2.5"}], ">=1.0.0 <=1.2.5"),
        ([{"introduced": "2.0.0"}], ">=2.0.0"),
        ([], None),
    ],
)
def test_osv_range(events: list[dict[str, str]], expected: str | None) -> None:
    assert osv_range(events) == expected


def test_advisory_kind() -> None:
    assert advisory_kind("MAL-2025-46974", {}) == "MALICIOUS"
    ua = {"summary": "Embedded malware in ua-parser-js"}
    assert advisory_kind("GHSA-pjwm-rvh2-c87w", ua) == "MALICIOUS"
    assert advisory_kind("GHSA-35jh-r3h4-6jhm", {"summary": "Command Injection in lodash"}) == "VULN"


def test_split_spec_and_repo_key() -> None:
    assert split_spec("debug@4.4.1") == ("debug", "4.4.1")
    assert split_spec("@scope/pkg@1.0.0") == ("@scope/pkg", "1.0.0")
    assert split_spec("@scope/pkg") == ("@scope/pkg", None)
    assert split_spec("debug") == ("debug", None)
    assert repo_key("billing-api") == "repo:fallout-demo/billing-api"
    assert repo_key("repo:fallout-demo/cli-tool") == "repo:fallout-demo/cli-tool"
