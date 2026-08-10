"""Tests for on-screen positioning helpers."""

from __future__ import annotations

import pytest

from notsucky.utils.geometry import cascade_position, clamp_to_screens, columns_for_width

PRIMARY = (0, 0, 1920, 1040)
SECONDARY = (1920, 0, 1280, 1024)
LEFT_OF_PRIMARY = (-1920, 0, 1920, 1040)


class TestClamp:
    def test_a_visible_window_is_left_alone(self) -> None:
        assert clamp_to_screens(100, 100, 320, 280, [PRIMARY]) == (100, 100)

    def test_runaway_negative_position_is_pulled_back(self) -> None:
        """Reproduces the stored x=-45088 left by the old accumulating drag."""
        assert clamp_to_screens(-45088, 33945, 320, 280, [PRIMARY]) == (0, 1040 - 280)

    def test_off_the_right_edge_is_pulled_back(self) -> None:
        x, y = clamp_to_screens(5000, 100, 320, 280, [PRIMARY])
        assert x == 1920 - 320
        assert y == 100

    def test_off_the_bottom_edge_is_pulled_back(self) -> None:
        _, y = clamp_to_screens(10, 9000, 320, 280, [PRIMARY])
        assert y == 1040 - 280

    def test_a_window_on_the_second_screen_stays_there(self) -> None:
        assert clamp_to_screens(2000, 50, 320, 280, [PRIMARY, SECONDARY]) == (2000, 50)

    def test_a_window_partly_off_the_second_screen_clamps_to_it(self) -> None:
        x, _ = clamp_to_screens(3100, 50, 320, 280, [PRIMARY, SECONDARY])
        assert x == 1920 + 1280 - 320

    def test_negative_screen_origins_are_supported(self) -> None:
        assert clamp_to_screens(-1000, 20, 320, 280, [LEFT_OF_PRIMARY, PRIMARY]) == (-1000, 20)

    def test_a_window_from_a_detached_monitor_lands_on_the_first_screen(self) -> None:
        x, y = clamp_to_screens(9999, 9999, 320, 280, [PRIMARY, SECONDARY])
        assert (x, y) == (1920 - 320, 1040 - 280)

    def test_a_window_wider_than_the_screen_aligns_to_the_origin(self) -> None:
        assert clamp_to_screens(500, 500, 4000, 4000, [PRIMARY]) == (0, 0)

    def test_no_screens_returns_the_input(self) -> None:
        assert clamp_to_screens(7, 9, 320, 280, []) == (7, 9)


class TestColumns:
    """Grid density: 180px cards, 16px gaps, 20px margins, 1-6 columns."""

    @pytest.mark.parametrize(
        ("width", "expected"),
        [
            (0, 1),
            (-500, 1),
            (100, 1),
            (300, 1),
            (500, 2),
            (700, 3),
            (900, 4),
            (5000, 6),  # capped
        ],
    )
    def test_columns_scale_with_width(self, width, expected) -> None:
        assert columns_for_width(width, 180, 16, 20, 1, 6) == expected

    def test_result_is_monotonic_in_width(self) -> None:
        counts = [columns_for_width(w, 180, 16, 20, 1, 6) for w in range(0, 2000, 20)]
        assert counts == sorted(counts)


class TestCascade:
    @pytest.mark.parametrize("seed", ["abc12345", "", "zzzz", "0", "a" * 60])
    def test_positions_are_always_on_screen(self, seed) -> None:
        x, y = cascade_position(seed, 320, 280, [PRIMARY])
        assert 0 <= x <= 1920 - 320
        assert 0 <= y <= 1040 - 280

    def test_position_is_stable_for_a_given_seed(self) -> None:
        assert cascade_position("abc12345", 320, 280, [PRIMARY]) == cascade_position(
            "abc12345", 320, 280, [PRIMARY]
        )

    def test_different_seeds_generally_differ(self) -> None:
        placements = {cascade_position(f"note{i:04d}", 320, 280, [PRIMARY]) for i in range(40)}
        assert len(placements) > 20

    def test_tiny_screen_still_produces_a_valid_point(self) -> None:
        x, y = cascade_position("abc", 320, 280, [(0, 0, 400, 300)])
        assert (x, y) == (0, 0) or (x >= 0 and y >= 0)

    def test_no_screens_returns_origin(self) -> None:
        assert cascade_position("abc", 320, 280, []) == (0, 0)
