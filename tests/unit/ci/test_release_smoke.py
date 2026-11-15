"""Post-release smoke: published assets, installer checksums and build provenance."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest
import yaml

from scripts.ci import release_assets

ROOT = Path(__file__).resolve().parents[3]
REPO = "example/project"
TAG = "v1.2.3"


def workflows() -> dict[str, dict]:
    return {
        p.name: yaml.safe_load(p.read_text(encoding="utf-8"))
        for p in (ROOT / ".github/workflows").glob("*.yml")
    }


class FakePublishedRelease:
    """In-memory published release; any write command fails the test."""

    def __init__(self, *, attested=0, attestation_ok=True, draft=False, outages=0):
        self.payloads = {
            "Dodaios-Linux-x86_64.AppImage": b"appimage",
            "PersonalJarvis-Linux-x86_64.AppImage": b"appimage",
            "personal-jarvis_1.2.3_amd64.deb": b"deb",
            "Dodaios-Setup-x64.exe": b"exe",
            "PersonalJarvis-Setup-x64.exe": b"exe",
        }
        self.manifest = "".join(
            f"{hashlib.sha256(data).hexdigest()}  {name}\n"
            for name, data in sorted(self.payloads.items())
        )
        self.attested = attested
        self.attestation_ok = attestation_ok
        self.draft = draft
        #: Attestation lookups answered with a server error before a real answer.
        self.outages = outages
        self.commands = []

    def command(self, args, **kwargs):
        self.commands.append(args)
        if args[:3] == ["gh", "release", "download"]:
            name = args[args.index("--pattern") + 1]
            folder = Path(args[args.index("--dir") + 1])
            if name == "installers-SHA256SUMS.txt":
                (folder / name).write_text(self.manifest, encoding="utf-8")
            else:
                (folder / name).write_bytes(self.payloads[name])
            return subprocess.CompletedProcess(args, 0, "", "")
        if args[:2] == ["gh", "api"] and "/attestations/sha256:" in args[2]:
            if self.outages:
                self.outages -= 1
                return subprocess.CompletedProcess(
                    args, 1, "", "gh: trust-metadata-api service unavailable (HTTP 503)"
                )
            if not self.attested:
                return subprocess.CompletedProcess(args, 1, "", "gh: Not Found (HTTP 404)")
            return subprocess.CompletedProcess(args, 0, f"{self.attested}\n", "")
        if args[:3] == ["gh", "attestation", "verify"]:
            assert args[args.index("--source-ref") + 1] == f"refs/tags/{TAG}"
            assert args[args.index("--signer-workflow") + 1] == (
                f"{REPO}/.github/workflows/desktop-installers.yml"
            )
            return subprocess.CompletedProcess(args, 0 if self.attestation_ok else 1, "", "")
        raise AssertionError(f"unexpected external command: {args}")

    def install(self, monkeypatch):
        monkeypatch.setattr(release_assets, "run_command", self.command)
        monkeypatch.setattr(
            release_assets,
            "release_info",
            lambda *a: {"databaseId": 1, "tagName": TAG, "isDraft": self.draft},
        )


def test_linux_smoke_checks_appimage_and_deb_against_provenance(monkeypatch, tmp_path):
    fake = FakePublishedRelease(attested=1)
    fake.install(monkeypatch)
    errors = release_assets.platform_errors(REPO, TAG, "linux", tmp_path, require_attestation=True)
    assert errors == []
    verified = [c[3] for c in fake.commands if c[:3] == ["gh", "attestation", "verify"]]
    assert sorted(Path(p).name for p in verified) == [
        "Dodaios-Linux-x86_64.AppImage",
        "PersonalJarvis-Linux-x86_64.AppImage",
        "personal-jarvis_1.2.3_amd64.deb",
    ]


def test_a_renamed_debian_package_is_checked_too(monkeypatch, tmp_path):
    fake = FakePublishedRelease(attested=1)
    fake.payloads["dodaios_1.2.3_amd64.deb"] = fake.payloads.pop("personal-jarvis_1.2.3_amd64.deb")
    fake.manifest = "".join(
        f"{hashlib.sha256(data).hexdigest()}  {name}\n"
        for name, data in sorted(fake.payloads.items())
    )
    fake.install(monkeypatch)
    errors = release_assets.platform_errors(REPO, TAG, "linux", tmp_path, require_attestation=True)
    assert errors == []
    verified = {Path(c[3]).name for c in fake.commands if c[:3] == ["gh", "attestation", "verify"]}
    assert "dodaios_1.2.3_amd64.deb" in verified


@pytest.mark.parametrize(
    "defect,require,expected",
    [
        ("tampered", False, "does not match"),
        ("unattested", True, "attestation absent"),
        ("forged", False, "attestation failed"),
    ],
)
def test_installer_smoke_fails_closed(monkeypatch, tmp_path, defect, require, expected):
    fake = FakePublishedRelease(
        attested=0 if defect == "unattested" else 1,
        attestation_ok=defect != "forged",
    )
    if defect == "tampered":
        fake.payloads["PersonalJarvis-Setup-x64.exe"] = b"tampered"
    fake.install(monkeypatch)
    errors = release_assets.platform_errors(
        REPO, TAG, "windows", tmp_path, require_attestation=require
    )
    assert any(expected in error for error in errors), errors


def test_older_unattested_builds_pass_unless_provenance_is_required(monkeypatch, tmp_path):
    fake = FakePublishedRelease()
    fake.install(monkeypatch)
    errors = release_assets.platform_errors(
        REPO, TAG, "windows", tmp_path, require_attestation=False
    )
    assert errors == []


def test_a_brief_attestation_service_outage_is_retried(monkeypatch, tmp_path):
    monkeypatch.setattr(release_assets, "ATTESTATION_RETRY_DELAYS", (0, 0))
    fake = FakePublishedRelease(attested=1, outages=2)
    fake.install(monkeypatch)
    errors = release_assets.platform_errors(
        REPO, TAG, "windows", tmp_path, require_attestation=True
    )
    assert errors == []
    assert any(c[:3] == ["gh", "attestation", "verify"] for c in fake.commands)


@pytest.mark.parametrize("require,failing", [(False, False), (True, True)])
def test_a_lasting_attestation_outage_fails_only_required_provenance(
    monkeypatch, tmp_path, require, failing
):
    monkeypatch.setattr(release_assets, "ATTESTATION_RETRY_DELAYS", (0, 0))
    fake = FakePublishedRelease(attested=1, outages=99)
    fake.install(monkeypatch)
    errors = release_assets.platform_errors(
        REPO, TAG, "windows", tmp_path, require_attestation=require
    )
    lookups = [c for c in fake.commands if c[:2] == ["gh", "api"]]
    # Three tries for each of the two names the setup is published under.
    assert len(lookups) == 6
    assert bool(errors) is failing
    if failing:
        assert errors == [
            "build provenance attestation unavailable: Dodaios-Setup-x64.exe",
            "build provenance attestation unavailable: PersonalJarvis-Setup-x64.exe",
        ]


def test_smoke_refuses_a_draft_without_touching_it(monkeypatch):
    fake = FakePublishedRelease(draft=True)
    fake.install(monkeypatch)
    assert release_assets.published_errors(REPO, TAG) == [f"{TAG} is not a published release"]
    assert fake.commands == []


def test_source_archive_digest_is_part_of_the_published_check(monkeypatch):
    digest = "b" * 64
    assets = [
        {"name": name, "size": 1, "state": "uploaded", "digest": f"sha256:{digest}"}
        for name in release_assets.REQUIRED_ASSETS
        | {"dodaios-src.tar.gz", "personal-jarvis-src.tar.gz"}
    ]
    manifests = {
        "installers-SHA256SUMS.txt": "".join(
            f"{digest}  {n}\n" for n in sorted(release_assets.INSTALLERS)
        ),
        "checksums.txt": "".join(
            f"{digest}  {n}\n" for n in sorted(release_assets.SIGNED - {"payload-commit.txt"})
        ),
        "source-SHA256SUMS.txt": (
            f"{'c' * 64}  dodaios-src.tar.gz\n{'c' * 64}  personal-jarvis-src.tar.gz\n"
        ),
    }

    def command(args, **kwargs):
        assert args[:3] == ["gh", "release", "download"]
        name = args[args.index("--pattern") + 1]
        (Path(args[args.index("--dir") + 1]) / name).write_text(manifests[name], encoding="utf-8")
        return subprocess.CompletedProcess(args, 0, "", "")

    monkeypatch.setattr(release_assets, "run_command", command)
    monkeypatch.setattr(release_assets, "api_pages", lambda *a: assets)
    monkeypatch.setattr(
        release_assets, "release_info", lambda *a: {"databaseId": 1, "tagName": TAG}
    )
    assert release_assets.published_errors(REPO, TAG) == [
        "release asset checksum mismatch: dodaios-src.tar.gz",
        "release asset checksum mismatch: personal-jarvis-src.tar.gz",
    ]
    manifests["source-SHA256SUMS.txt"] = f"{digest}  personal-jarvis-src.tar.gz\n"
    assert release_assets.published_errors(REPO, TAG) == [
        "incomplete manifest: source-SHA256SUMS.txt lacks dodaios-src.tar.gz"
    ]
    manifests["source-SHA256SUMS.txt"] = (
        f"{digest}  dodaios-src.tar.gz\n{digest}  personal-jarvis-src.tar.gz\n"
    )
    assert release_assets.published_errors(REPO, TAG) == []


def test_both_names_of_an_installer_must_carry_the_same_bytes():
    current, earlier = release_assets.INSTALLER_NAME_PAIRS[0]
    assert release_assets.alias_errors({current: "a" * 64, earlier: "a" * 64}) == []
    assert release_assets.alias_errors({current: "a" * 64, earlier: "b" * 64}) == [
        f"installer names differ in content: {current} and {earlier}"
    ]


def test_native_installers_are_attested_on_tags_before_upload():
    job = workflows()["desktop-installers.yml"]["jobs"]["release"]
    assert job["permissions"]["id-token"] == "write"
    assert job["permissions"]["attestations"] == "write"
    steps = job["steps"]
    attest = next(i for i, s in enumerate(steps) if "attest-build-provenance@" in s.get("uses", ""))
    upload = next(i for i, s in enumerate(steps) if "release_assets.py upload" in s.get("run", ""))
    assert steps[attest]["if"] == "github.ref_type == 'tag'"
    assert steps[attest]["with"]["subject-checksums"] == "installers/installers-SHA256SUMS.txt"
    assert attest < upload


def test_rename_gap_still_verifies_the_released_wrapper():
    """v3.1.1 was signed by the renamed repository while its published
    verifier still names the previous owner. The smoke retargets that one
    unsigned pin and still executes the released script."""
    step = workflows()["release-wrapper-smoke.yml"]["jobs"]["verify"]["steps"][0]["run"]
    assert 'bash "$verifier"' in step
    assert 'readonly DEFAULT_OFFICIAL_REPO_SLUG=' in step
    assert "PersonalJarvis/PersonalJarvis" in step
    assert "Dodaios/Dodaios" in step
    assert "JARVIS_OFFICIAL_REPO_SLUG" in step
    assert "released layout regexp is not the pre-rename pin" in step


def test_release_smoke_is_read_only_and_follows_every_cut():
    definitions = workflows()
    for name in ("release-smoke.yml", "release-wrapper-smoke.yml"):
        workflow = definitions[name]
        assert workflow["permissions"] == {"contents": "read"}
        for job in workflow["jobs"].values():
            assert set(job.get("permissions", {}).values()) <= {"read"}
    smoke = definitions["release-cut.yml"]["jobs"]["smoke"]
    assert smoke["uses"] == "./.github/workflows/release-smoke.yml"
    assert "publish" in smoke["needs"]
    assert set(smoke["permissions"].values()) == {"read"}
    assert smoke["with"]["require_attestation"] is True
    wrapper = definitions["installer-smoke.yml"]["jobs"]["verify-release"]
    assert wrapper["uses"] == "./.github/workflows/release-wrapper-smoke.yml"


# -- closing the "tagged but not published" reports a release answers -------


class FakeIssues:
    """The repository's open issues and its releases; records every write."""

    def __init__(self, *, issues: list[dict], published=(TAG,), drafts=()):
        self.issues = issues
        self.published = set(published)
        self.drafts = set(drafts)
        self.writes: list[list[str]] = []

    def command(self, args, **kwargs):
        if args[:3] == ["gh", "release", "view"]:
            tag = args[3]
            if tag not in self.published | self.drafts:
                raise subprocess.CalledProcessError(1, args, "", "release not found")
            info = {"databaseId": 1, "tagName": tag, "isDraft": tag in self.drafts}
            return subprocess.CompletedProcess(args, 0, json.dumps(info), "")
        self.writes.append(args)
        return subprocess.CompletedProcess(args, 0, "{}", "")

    def pages(self, endpoint, key, **kwargs):
        assert endpoint.startswith(f"repos/{REPO}/issues?state=open")
        return self.issues


def _stranded(number: int, version: str) -> dict:
    return {"number": number, "title": f"Release v{version} is tagged but not published"}


def _close_stranded(monkeypatch, fake: FakeIssues, tag: str = TAG) -> int:
    monkeypatch.setattr(release_assets, "run_command", fake.command)
    monkeypatch.setattr(release_assets, "api_pages", fake.pages)
    return release_assets.close_stranded(REPO, tag)


def test_a_published_release_closes_its_own_report_and_those_of_lower_versions(monkeypatch):
    # v5.3.2 was public for hours with its report still open, beside the
    # reports of v5.3.0 and v5.3.1, which never got published, and the one of
    # v5.0.0, which had been published three days before.
    fake = FakeIssues(
        published=("v1.1.0", TAG),
        drafts=("v1.2.1",),
        issues=[
            _stranded(10, "1.1.0"),
            _stranded(11, "1.2.1"),
            _stranded(12, "1.2.3"),
            _stranded(13, "1.3.0"),
            {"number": 14, "title": "Release v1.2.3 is tagged but not published, why?"},
            {**_stranded(15, "1.2.2"), "pull_request": {}},
            _stranded(16, "1.2.0"),
        ],
    )

    assert _close_stranded(monkeypatch, fake) == 0

    closed = [args[4].split("/")[-1] for args in fake.writes if "PATCH" in args]
    assert closed == ["10", "11", "12", "16"]
    notes = {
        args[4].split("/")[-2]: args[-1] for args in fake.writes if args[4].endswith("/comments")
    }
    # A lower version with a public release of its own was published, not superseded.
    assert f"v1.1.0 is published: https://github.com/{REPO}/releases/tag/v1.1.0" in notes["10"]
    assert "Superseded by v1.2.3, which is published" in notes["11"]
    assert "v1.2.1 was never published" in notes["11"]
    assert f"v1.2.3 is published now: https://github.com/{REPO}/releases/tag/v1.2.3" in notes["12"]
    # No release at all for the tag reads like a draft: never published.
    assert "v1.2.0 was never published" in notes["16"]
    reasons = [args[-1].split("=")[1] for args in fake.writes if "PATCH" in args]
    assert reasons == ["completed", "not_planned", "completed", "not_planned"]


def test_a_draft_release_closes_nothing(monkeypatch):
    fake = FakeIssues(published=(), drafts=(TAG,), issues=[_stranded(12, "1.2.3")])

    assert _close_stranded(monkeypatch, fake) == 0
    assert fake.writes == []


def test_versions_compare_as_numbers(monkeypatch):
    # 1.10.0 is higher than 1.9.0; a text comparison would close the wrong one.
    fake = FakeIssues(
        published=("v1.10.0",), issues=[_stranded(21, "1.9.0"), _stranded(22, "1.10.1")]
    )

    assert _close_stranded(monkeypatch, fake, tag="v1.10.0") == 0

    assert [args[4] for args in fake.writes if "PATCH" in args] == [f"repos/{REPO}/issues/21"]
