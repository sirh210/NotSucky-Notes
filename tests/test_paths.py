"""Tests for storage location resolution and legacy data import."""

from __future__ import annotations

import json
import sys

import pytest

from notsucky.utils import paths


@pytest.fixture(autouse=True)
def _clean_override():
    yield
    paths.set_notes_dir(None)


class TestResolution:
    def test_explicit_override_wins(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv(paths.ENV_NOTES_DIR, str(tmp_path / "from-env"))
        paths.set_notes_dir(tmp_path / "explicit")
        assert paths.notes_dir() == tmp_path / "explicit"

    def test_environment_variable_is_honoured(self, tmp_path, monkeypatch) -> None:
        paths.set_notes_dir(None)
        monkeypatch.setenv(paths.ENV_NOTES_DIR, str(tmp_path / "from-env"))
        assert paths.notes_dir() == tmp_path / "from-env"

    def test_default_is_under_the_user_data_dir(self, monkeypatch) -> None:
        paths.set_notes_dir(None)
        monkeypatch.delenv(paths.ENV_NOTES_DIR, raising=False)
        assert paths.notes_dir(create=False) == paths.user_data_dir() / "notes"

    def test_directory_is_created(self, tmp_path) -> None:
        target = tmp_path / "deep" / "nested" / "notes"
        paths.set_notes_dir(target)
        assert paths.notes_dir().is_dir()

    def test_create_false_does_not_touch_the_filesystem(self, tmp_path) -> None:
        target = tmp_path / "never-created"
        paths.set_notes_dir(target)
        assert paths.notes_dir(create=False) == target
        assert not target.exists()

    def test_override_invalidates_the_cache(self, tmp_path) -> None:
        first, second = tmp_path / "one", tmp_path / "two"
        paths.set_notes_dir(first)
        assert paths.notes_dir() == first
        paths.set_notes_dir(second)
        assert paths.notes_dir() == second

    def test_user_dir_is_platform_appropriate(self) -> None:
        directory = str(paths.user_data_dir())
        if sys.platform == "win32":
            assert "AppData" in directory or "Local" in directory
        elif sys.platform == "darwin":
            assert "Application Support" in directory
        else:
            assert ".local/share" in directory or "XDG" in directory or directory

    def test_log_dir_sits_beside_the_data_dir(self) -> None:
        assert paths.log_dir().parent == paths.user_data_dir()


class TestLegacyImport:
    """Notes written by v1.0 must survive the move to the user data dir."""

    @staticmethod
    def _write(directory, note_id: str, title: str) -> None:
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{note_id}.json").write_text(
            json.dumps({"id": note_id, "title": title}), encoding="utf-8"
        )

    @pytest.fixture()
    def legacy(self, tmp_path, monkeypatch):
        """Pretend the package lives in a checkout with a ./notes directory."""
        checkout = tmp_path / "checkout"
        legacy_dir = checkout / "notes"
        legacy_dir.mkdir(parents=True)
        monkeypatch.setattr(paths, "_legacy_candidates", lambda: [legacy_dir])
        return legacy_dir

    def test_legacy_notes_are_imported(self, tmp_path, legacy) -> None:
        self._write(legacy, "old00001", "Old note")
        target = tmp_path / "new-notes"
        paths.set_notes_dir(target)

        assert (paths.notes_dir() / "old00001.json").exists()

    def test_originals_are_left_in_place(self, tmp_path, legacy) -> None:
        self._write(legacy, "old00001", "Old note")
        paths.set_notes_dir(tmp_path / "new-notes")
        paths.notes_dir()
        assert (legacy / "old00001.json").exists()

    def test_existing_files_are_never_overwritten(self, tmp_path, legacy) -> None:
        self._write(legacy, "dup00001", "legacy version")
        target = tmp_path / "new-notes"
        self._write(target, "dup00001", "current version")

        paths.set_notes_dir(target)
        payload = json.loads((paths.notes_dir() / "dup00001.json").read_text(encoding="utf-8"))
        assert payload["title"] == "current version"

    def test_import_runs_only_once(self, tmp_path, legacy) -> None:
        self._write(legacy, "old00001", "Old note")
        target = tmp_path / "new-notes"
        paths.set_notes_dir(target)
        paths.notes_dir()

        # User deletes the note; it must not come back on the next launch.
        (target / "old00001.json").unlink()
        paths.set_notes_dir(target)
        assert not (paths.notes_dir() / "old00001.json").exists()

    def test_marker_is_written(self, tmp_path, legacy) -> None:
        paths.set_notes_dir(tmp_path / "new-notes")
        assert (paths.notes_dir() / paths.MIGRATION_MARKER).exists()

    def test_missing_legacy_dir_is_not_an_error(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setattr(paths, "_legacy_candidates", lambda: [tmp_path / "nope"])
        paths.set_notes_dir(tmp_path / "new-notes")
        assert paths.notes_dir().is_dir()

    def test_legacy_equal_to_target_is_skipped(self, tmp_path, monkeypatch) -> None:
        target = tmp_path / "same-dir-notes"
        target.mkdir()
        monkeypatch.setattr(paths, "_legacy_candidates", lambda: [target])
        paths.set_notes_dir(target)
        self._write(target, "keep0001", "kept")
        assert paths.notes_dir().is_dir()
