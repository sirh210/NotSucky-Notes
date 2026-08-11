"""Repository-level security hygiene.

Most of a front-end security checklist is response headers, TLS, cookies and
form handling, none of which exist for a desktop application. Three items do
apply to a public repository shipping one static HTML file, and they are the
ones checked here:

* nothing committed leaks a secret or a real person's details,
* the one HTML document declares a policy it can actually enforce,
* a future link cannot open a tab that keeps a handle on this one.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
REPORT = PROJECT_ROOT / "docs" / "audit-report.html"

SCANNED_SUFFIXES = {".py", ".md", ".toml", ".txt", ".yml", ".yaml", ".html", ".json", ".cfg"}
SKIPPED_DIRS = {".git", ".venv", "__pycache__", ".pytest_cache", ".ruff_cache", ".mypy_cache",
                "build", "dist", "notes", "htmlcov"}

SECRET_PATTERNS = {
    "private key": r"BEGIN (?:RSA |OPENSSH |EC |DSA |PGP )?PRIVATE KEY",
    "aws access key": r"AKIA[0-9A-Z]{16}",
    "github token": r"gh[pousr]_[A-Za-z0-9]{20,}",
    "slack token": r"xox[baprs]-[A-Za-z0-9-]{10,}",
    "google api key": r"AIza[0-9A-Za-z_-]{35}",
    "bearer header": r"(?i)authorization\s*:\s*bearer\s+\S{8,}",
    "assigned credential": (
        r"(?i)\b(?:api[_-]?key|secret[_-]?key|access[_-]?token|passwd|password)\b"
        r"\s*[:=]\s*[\"'][^\"'\s]{12,}[\"']"
    ),
    "windows home path": r"[A-Z]:\\\\?Users\\\\?[A-Za-z0-9._-]+",
    "unix home path": r"/(?:home|Users)/[a-z][A-Za-z0-9._-]+/",
    "email address": r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
}

#: Deliberate exceptions, each with a reason.
ALLOWED = {
    # The canary a test plants to prove note content never reaches the logs.
    ("tests/test_security.py", "assigned credential"),
    # Documented placeholder addresses in the security policy, not real ones.
}


def scanned_files() -> list[Path]:
    found = []
    for path in PROJECT_ROOT.rglob("*"):
        if not path.is_file() or path.suffix not in SCANNED_SUFFIXES:
            continue
        if any(part in SKIPPED_DIRS for part in path.relative_to(PROJECT_ROOT).parts):
            continue
        found.append(path)
    return found


class TestNothingSensitiveIsCommitted:
    @pytest.mark.parametrize("label,pattern", sorted(SECRET_PATTERNS.items()))
    def test_no_secrets_or_personal_data(self, label, pattern) -> None:
        hits = []
        for path in scanned_files():
            rel = path.relative_to(PROJECT_ROOT).as_posix()
            if (rel, label) in ALLOWED:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            for match in re.finditer(pattern, text):
                line = text[: match.start()].count("\n") + 1
                hits.append(f"{rel}:{line} {match.group(0)[:60]}")
        assert hits == [], f"{label} found: {hits[:5]}"

    def test_the_scan_actually_reads_files(self) -> None:
        """A scan that silently matches nothing is worse than none at all."""
        files = scanned_files()
        assert len(files) > 20
        assert any(f.suffix == ".html" for f in files)
        assert any(f.suffix == ".py" for f in files)

    def test_no_environment_files_are_tracked(self) -> None:
        for name in (".env", ".env.local", "secrets.json", "credentials.json", "id_rsa"):
            assert not (PROJECT_ROOT / name).exists(), f"{name} must never be committed"

    def test_user_notes_are_not_committed(self) -> None:
        """The notes directory holds private content and stays ignored."""
        gitignore = (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8")
        assert re.search(r"(?m)^notes/\s*$", gitignore)


class TestDocumentSecurityPolicy:
    @pytest.fixture()
    def html(self) -> str:
        return REPORT.read_text(encoding="utf-8")

    def test_a_content_security_policy_is_declared(self, html) -> None:
        csp = re.search(
            r'<meta http-equiv="Content-Security-Policy"\s+content="([^"]+)"', html
        )
        assert csp, "no CSP meta tag"
        policy = csp.group(1)
        assert "default-src 'none'" in policy, "policy must deny by default"
        assert "base-uri 'none'" in policy
        assert "form-action 'none'" in policy

    def test_the_policy_permits_no_scripts(self, html) -> None:
        policy = re.search(
            r'<meta http-equiv="Content-Security-Policy"\s+content="([^"]+)"', html
        ).group(1)
        assert "script-src" not in policy, "default-src 'none' already denies scripts"
        assert "unsafe-eval" not in policy

    def test_no_header_only_directives_are_faked(self, html) -> None:
        """frame-ancestors and friends are ignored in a meta tag; declaring
        them would imply protection that is not there."""
        policy = re.search(
            r'<meta http-equiv="Content-Security-Policy"\s+content="([^"]+)"', html
        ).group(1)
        for ignored in ("frame-ancestors", "report-uri", "sandbox"):
            assert ignored not in policy

    def test_a_referrer_policy_is_declared(self, html) -> None:
        assert re.search(r'<meta name="referrer" content="no-referrer"', html)

    def test_new_tab_links_cannot_reach_the_opener(self, html) -> None:
        """No target=_blank today; this fails the day one arrives without rel."""
        for tag in re.findall(r"<a\s[^>]*>", html):
            if 'target="_blank"' in tag:
                assert "noopener" in tag, tag

    def test_nothing_is_loaded_over_plain_http(self, html) -> None:
        insecure = [
            url
            for url in re.findall(r'(?:href|src)="(http://[^"]+)"', html)
            if not url.startswith("http://www.w3.org/")  # namespace, never fetched
        ]
        assert insecure == []
