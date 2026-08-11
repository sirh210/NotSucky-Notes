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

    def test_the_docs_do_not_promise_a_retention_window(self) -> None:
        """Trash is kept indefinitely; the docs must not imply a deadline."""
        from notsucky.services.file_manager import TRASH_RETENTION_DAYS

        assert TRASH_RETENTION_DAYS is None
        for name in ("README.md", "OPERATIONS.md"):
            text = read(name)
            assert "purged after 30 days" not in text
            assert "for 30 days" not in text

    def test_the_documented_backup_count_matches_the_code(self) -> None:
        from notsucky.services import backup

        assert str(backup.MAX_BACKUPS) in read("README.md") or "ten" in read("README.md")


class TestStandaloneReport:
    """docs/audit-report.html is the only HTML in the repository.

    The hosted copy gets its doctype, charset and viewport from the artifact
    wrapper; this file has no wrapper, so it must supply them itself. These
    assertions are the front-end checklist, enforced rather than trusted.
    """

    REPORT = PROJECT_ROOT / "docs" / "audit-report.html"

    @pytest.fixture()
    def html(self) -> str:
        return self.REPORT.read_text(encoding="utf-8")

    @staticmethod
    def stylesheet(html: str) -> str:
        """The CSS with comments stripped — prose about a property must not
        read as a use of it."""
        css = "\n".join(re.findall(r"<style>(.*?)</style>", html, re.S))
        return re.sub(r"/\*.*?\*/", "", css, flags=re.S)

    def test_the_report_exists(self) -> None:
        assert self.REPORT.is_file()

    def test_html5_doctype_is_first(self, html) -> None:
        assert html.lstrip().lower().startswith("<!doctype html>")

    def test_charset_is_declared_first_in_head(self, html) -> None:
        head = html.split("<head>", 1)[1]
        first_meta = re.search(r"<meta[^>]*>", head).group(0)
        assert "charset" in first_meta.lower()
        assert "utf-8" in first_meta.lower()

    def test_the_language_is_declared(self, html) -> None:
        assert re.search(r"<html[^>]+lang=\"[a-z]{2}", html)

    def test_the_viewport_allows_zooming(self, html) -> None:
        viewport = re.search(r'<meta name="viewport"[^>]*>', html)
        assert viewport, "no viewport meta tag"
        assert "user-scalable=no" not in viewport.group(0)
        assert "maximum-scale=1" not in viewport.group(0)

    def test_it_has_a_title_and_description(self, html) -> None:
        assert re.search(r"<title>\S", html)
        assert re.search(r'<meta name="description" content="\S', html)

    def test_it_is_self_contained(self, html) -> None:
        """No CDN, no external font, nothing to fail or leak a referrer."""
        assert re.findall(r'(?:src|href)="https?://', html) == []

    def test_there_is_no_javascript(self, html) -> None:
        assert "<script" not in html
        assert not re.search(r"\son[a-z]+=\"", html), "inline event handler attribute"

    def test_ids_are_unique(self, html) -> None:
        ids = re.findall(r'\sid="([^"]+)"', html)
        assert len(ids) == len(set(ids))

    def test_it_uses_semantic_landmarks(self, html) -> None:
        for tag in ("<main", "<header", "<footer", "<section"):
            assert tag in html, f"missing {tag}"

    def test_specificity_stays_flat(self, html) -> None:
        """No ID selectors, and no !important outside the reduced-motion
        escape hatch, which is the one place the cascade must be overridden."""
        style = self.stylesheet(html)
        assert not re.search(r"(?m)^\s*#[\w-]+\s*[,{]", style)
        for line in style.splitlines():
            if "!important" in line:
                assert re.search(r"(animation|transition)-", line), line

    def test_cascade_layers_order_the_stylesheet(self, html) -> None:
        style = self.stylesheet(html)
        assert re.search(r"@layer\s+[\w\s,]+;", style), "no layer order statement"

    def test_the_body_rule_stays_unlayered(self, html) -> None:
        """The host injects an unlayered reset, and unlayered beats every
        layer. A layered body rule would lose, and the page would render the
        host's light background under our dark theme."""
        style = self.stylesheet(html)
        body_rule = re.search(r"(?m)^  body \{", style)
        assert body_rule, "body rule is indented into a layer or missing"

    def test_both_themes_are_defined_at_token_level(self, html) -> None:
        style = self.stylesheet(html)
        assert "prefers-color-scheme: dark" in style
        assert ':root[data-theme="dark"]' in style
        assert ':root:not([data-theme="light"])' in style

    def test_a_print_stylesheet_is_present(self, html) -> None:
        assert "@media print" in html

    def test_motion_preferences_are_respected(self, html) -> None:
        assert "prefers-reduced-motion: reduce" in html

    def test_type_uses_relative_units(self, html) -> None:
        style = self.stylesheet(html)
        pixel_type = [
            m for m in re.findall(r"font-size:\s*[^;]+;", style) if re.search(r"\d+px", m)
        ]
        assert pixel_type == [], f"fixed pixel type: {pixel_type}"

    def test_layout_uses_logical_properties(self, html) -> None:
        style = self.stylesheet(html)
        physical = re.findall(r"(?:border|margin|padding)-(?:left|right|top|bottom):", style)
        assert physical == [], f"physical properties: {set(physical)}"

    def test_wide_content_scrolls_inside_its_own_container(self, html) -> None:
        """Otherwise the page body scrolls sideways, which breaks zoom."""
        style = self.stylesheet(html)
        assert "overflow-x: auto" in style

    def test_the_report_matches_the_shipped_version(self, html) -> None:
        from notsucky import __version__

        assert __version__ in html


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
