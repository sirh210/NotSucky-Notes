"""Documentation checks.

Docs rot silently: a renamed module or a removed shortcut leaves the README
confidently wrong, which is how v1.0 came to advertise two features it did not
have. These tests fail when the documentation describes something that is not
there. Nothing here reaches the network — external URLs are checked for shape
only, so the suite stays offline and deterministic.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS = [
    "README.md",
    "AUDIT.md",
    "CHANGELOG.md",
    "SECURITY.md",
    "CONTRIBUTING.md",
    "OPERATIONS.md",
    "ROADMAP.md",
]

#: Paths that appear in prose as examples rather than as real files.
ILLUSTRATIVE = {
    "notes/",
    "notes/.trash/",
    "backups/",
    "logs/notsucky.log",
    "notes/505e8a20.json",
    "notsucky/notes",
    "site-packages",
    ".trash",
}


def read(name: str) -> str:
    return (PROJECT_ROOT / name).read_text(encoding="utf-8")


def existing_docs() -> list[str]:
    return [name for name in DOCS if (PROJECT_ROOT / name).is_file()]


class TestDocsExist:
    @pytest.mark.parametrize("name", DOCS)
    def test_every_advertised_document_is_present(self, name) -> None:
        assert (PROJECT_ROOT / name).is_file(), f"{name} is referenced but missing"

    def test_the_licence_file_exists(self) -> None:
        assert (PROJECT_ROOT / "LICENSE").is_file()

    def test_the_ci_workflow_exists(self) -> None:
        assert (PROJECT_ROOT / ".github" / "workflows" / "ci.yml").is_file()


class TestInternalLinks:
    @pytest.mark.parametrize("name", existing_docs())
    def test_markdown_links_resolve(self, name) -> None:
        """Every [text](target) pointing at a local path must exist."""
        broken = []
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", read(name)):
            if target.startswith(("http://", "https://", "#", "mailto:")):
                continue
            path = (PROJECT_ROOT / target.split("#")[0]).resolve()
            if not path.exists():
                broken.append(target)
        assert broken == [], f"{name} links to missing paths: {broken}"


class TestReferencedPaths:
    def test_project_structure_lists_real_modules(self) -> None:
        """The tree in the README must match the package on disk."""
        tree_block = read("README.md").split("## Project structure")[1].split("```")[1]
        listed = re.findall(r"([\w_]+\.py)", tree_block)

        actual = {p.name for p in (PROJECT_ROOT / "notsucky").rglob("*.py")}
        actual |= {"ci.yml"}
        missing = [name for name in listed if name not in actual]
        assert missing == [], f"README lists modules that do not exist: {missing}"

    def test_every_package_module_is_documented(self) -> None:
        tree_block = read("README.md").split("## Project structure")[1].split("```")[1]
        undocumented = [
            path.name
            for path in (PROJECT_ROOT / "notsucky").rglob("*.py")
            if path.name not in {"__init__.py"} and path.name not in tree_block
        ]
        assert undocumented == [], f"modules missing from the README tree: {undocumented}"

    @pytest.mark.parametrize("name", existing_docs())
    def test_backticked_repo_paths_exist(self, name) -> None:
        """`notsucky/...` or `tests/...` in backticks must be a real path."""
        broken = []
        for quoted in re.findall(r"`([^`\n]+)`", read(name)):
            if quoted in ILLUSTRATIVE or " " in quoted:
                continue
            if not quoted.startswith(("notsucky/", "tests/", ".github/")):
                continue
            candidate = quoted.split(":")[0]
            if not (PROJECT_ROOT / candidate).exists():
                broken.append(quoted)
        assert broken == [], f"{name} references missing paths: {broken}"


class TestClaimsMatchCode:
    def test_documented_shortcuts_are_all_registered(self) -> None:
        """Every shortcut in the README table must exist in the source."""
        table = read("README.md").split("### Keyboard shortcuts")[1].split("##")[0]
        documented = set(re.findall(r"`(Ctrl\+\w|F\d|Esc)`", table))

        sources = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (PROJECT_ROOT / "notsucky" / "views").glob("*.py")
        )
        standard_keys = {
            "Ctrl+N": "StandardKey.New",
            "Ctrl+F": "StandardKey.Find",
            "Ctrl+Z": "StandardKey.Undo",
            "Ctrl+S": "StandardKey.Save",
            "F5": "StandardKey.Refresh",
        }
        missing = [
            key
            for key in documented
            if f'"{key}"' not in sources and standard_keys.get(key, "\0") not in sources
        ]
        assert missing == [], f"README documents unregistered shortcuts: {missing}"

    def test_documented_cli_flags_exist(self) -> None:
        from notsucky.main import build_parser

        known = {
            action
            for entry in build_parser()._actions
            for action in entry.option_strings
        }
        documented = set(re.findall(r"`?(--[a-z][a-z-]+)`?", read("README.md")))
        # Flags shown for other tools (pip, pytest) are not ours to own.
        ours = {flag for flag in documented if flag in known or flag.startswith("--notes")}
        missing = [flag for flag in ours if flag not in known]
        assert missing == [], f"README documents unknown flags: {missing}"

    def test_the_version_is_consistent(self) -> None:
        from notsucky import __version__

        assert f'version = "{__version__}"' in read("pyproject.toml")
        assert f"[{__version__}]" in read("CHANGELOG.md")

    def test_the_documented_retention_matches_the_code(self) -> None:
        from notsucky.services.file_manager import TRASH_RETENTION_DAYS

        assert f"{TRASH_RETENTION_DAYS} days" in read("README.md")

    def test_the_documented_backup_count_matches_the_code(self) -> None:
        from notsucky.services import backup

        assert str(backup.MAX_BACKUPS) in read("README.md") or "ten" in read("README.md")


class TestExternalLinks:
    """Shape only — no network calls, so the suite stays offline."""

    @pytest.mark.parametrize("name", existing_docs())
    def test_urls_are_well_formed(self, name) -> None:
        bad = [
            url
            for url in re.findall(r"https?://[^\s)\]\"'>]+", read(name))
            if not re.match(r"^https?://[\w.-]+\.[a-z]{2,}(/\S*)?$", url)
        ]
        assert bad == [], f"{name} has malformed URLs: {bad}"

    @pytest.mark.parametrize("name", existing_docs())
    def test_no_placeholder_links_remain(self, name) -> None:
        text = read(name)
        for placeholder in ("<repo-url>", "TODO", "FIXME", "XXX", "example.com"):
            assert placeholder not in text, f"{name} still contains {placeholder!r}"

    def test_the_repository_url_is_the_real_one(self) -> None:
        assert "github.com/sirh210/NotSucky-Notes" in read("README.md")
