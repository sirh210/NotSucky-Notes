"""Tests for the theme setting and the settings file behind it."""

from __future__ import annotations

import json

import pytest

from notsucky.utils import settings, theme


@pytest.fixture(autouse=True)
def _fresh_settings():
    settings.reset_cache()
    yield
    settings.reset_cache()


class TestPalettes:
    def test_both_themes_exist(self) -> None:
        assert set(theme.THEMES) == {"dark", "light"}

    def test_the_palettes_define_the_same_keys(self) -> None:
        dark, light = theme.THEMES["dark"], theme.THEMES["light"]
        assert dark.keys() == light.keys()

    @pytest.mark.parametrize("name", ["dark", "light"])
    def test_every_colour_is_a_hex_value(self, name) -> None:
        for key, value in theme.THEMES[name].items():
            assert value.startswith("#"), f"{name}.{key}"
            assert len(value) in (4, 7), f"{name}.{key} = {value}"

    def test_the_two_themes_actually_differ(self) -> None:
        assert theme.THEMES["dark"]["bg"] != theme.THEMES["light"]["bg"]

    def test_text_and_ground_are_far_apart_in_both(self) -> None:
        """A cheap luminance check: text must not approach its background."""

        def luminance(hex_colour: str) -> float:
            r, g, b = (int(hex_colour[i : i + 2], 16) / 255 for i in (1, 3, 5))
            return 0.2126 * r + 0.7152 * g + 0.0722 * b

        for name in ("dark", "light"):
            palette = theme.THEMES[name]
            assert abs(luminance(palette["text"]) - luminance(palette["bg"])) > 0.4, name

    def test_an_unknown_name_falls_back(self) -> None:
        assert theme.palette("chartreuse") == theme.THEMES[theme.DEFAULT_THEME]


class TestThemeSetting:
    def test_the_default_is_dark(self, notes_dir) -> None:
        assert theme.current_theme() == "dark"

    def test_a_choice_is_remembered(self, notes_dir) -> None:
        theme.set_theme("light")
        settings.reset_cache()
        assert theme.current_theme() == "light"

    def test_toggling_alternates(self, notes_dir) -> None:
        assert theme.toggle_theme() == "light"
        assert theme.toggle_theme() == "dark"

    def test_an_unknown_theme_is_refused(self, notes_dir) -> None:
        assert theme.set_theme("neon") == theme.DEFAULT_THEME

    def test_a_corrupt_setting_falls_back(self, notes_dir) -> None:
        settings.save_settings({"theme": "banana"})
        assert theme.current_theme() == theme.DEFAULT_THEME

    def test_the_setting_lands_beside_the_notes_not_inside(self, notes_dir) -> None:
        theme.set_theme("light")
        assert settings.settings_path().parent == notes_dir.parent
        assert settings.settings_path().exists()


class TestSettingsFile:
    def test_a_missing_file_reads_as_empty(self, notes_dir) -> None:
        assert settings.load_settings() == {}

    def test_values_round_trip(self, notes_dir) -> None:
        settings.set_setting("theme", "light")
        settings.reset_cache()
        assert settings.get_setting("theme") == "light"

    def test_an_unrelated_key_is_preserved(self, notes_dir) -> None:
        settings.set_setting("other", 42)
        settings.set_setting("theme", "light")
        settings.reset_cache()
        assert settings.get_setting("other") == 42

    def test_corrupt_json_is_ignored_not_fatal(self, notes_dir) -> None:
        settings.settings_path().write_text("{not json", encoding="utf-8")
        settings.reset_cache()
        assert settings.load_settings() == {}

    def test_a_non_object_file_is_ignored(self, notes_dir) -> None:
        settings.settings_path().write_text("[1, 2, 3]", encoding="utf-8")
        settings.reset_cache()
        assert settings.load_settings() == {}

    def test_the_file_is_human_readable(self, notes_dir) -> None:
        settings.set_setting("theme", "light")
        assert json.loads(settings.settings_path().read_text(encoding="utf-8")) == {
            "theme": "light"
        }

    def test_no_temp_files_are_left_behind(self, notes_dir) -> None:
        settings.set_setting("theme", "light")
        assert list(settings.settings_path().parent.glob(".settings.*")) == []

    def test_a_failed_write_is_reported_not_raised(self, notes_dir, monkeypatch) -> None:
        monkeypatch.setattr(
            "tempfile.mkstemp", lambda *a, **k: (_ for _ in ()).throw(OSError("full"))
        )
        assert settings.save_settings({"theme": "light"}) is False

    def test_settings_are_never_mistaken_for_a_note(self, notes_dir) -> None:
        from notsucky.services.file_manager import FileManager

        settings.set_setting("theme", "light")
        assert FileManager.load_all() == []
