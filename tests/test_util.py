"""Tests for the small helpers that everything else leans on."""

from __future__ import annotations

import pytest

from siesta.util import (
    canonical_name,
    clamp,
    cosine,
    parse_json_lenient,
    same_item,
    slugify,
    strip_code_fences,
    truncate,
)


class TestParseJsonLenient:
    def test_plain_json(self):
        assert parse_json_lenient('{"a": 1}') == {"a": 1}

    def test_fenced_json(self):
        assert parse_json_lenient('```json\n{"a": 1}\n```') == {"a": 1}

    def test_fenced_without_language(self):
        assert parse_json_lenient('```\n{"a": 1}\n```') == {"a": 1}

    def test_prose_around_json(self):
        text = 'Sure! Here is the result:\n{"a": 1}\nHope that helps.'
        assert parse_json_lenient(text) == {"a": 1}

    def test_trailing_comma(self):
        assert parse_json_lenient('{"a": 1,}') == {"a": 1}

    def test_garbage_returns_none(self):
        assert parse_json_lenient("no json at all") is None

    def test_none_input(self):
        assert parse_json_lenient(None) is None


class TestStripCodeFences:
    def test_keeps_plain_text(self):
        assert strip_code_fences("hello") == "hello"

    def test_removes_fence(self):
        assert strip_code_fences("```json\n{}\n```") == "{}"


class TestCosine:
    def test_identical(self):
        assert cosine([1, 2, 3], [1, 2, 3]) == pytest.approx(1.0)

    def test_orthogonal(self):
        assert cosine([1, 0], [0, 1]) == pytest.approx(0.0)

    def test_opposite(self):
        assert cosine([1, 0], [-1, 0]) == pytest.approx(-1.0)

    def test_length_mismatch_is_zero(self):
        assert cosine([1, 2], [1, 2, 3]) == 0.0

    def test_zero_vector(self):
        assert cosine([0, 0], [1, 1]) == 0.0


class TestMisc:
    def test_clamp(self):
        assert clamp(1.5) == 1.0
        assert clamp(-0.5) == 0.0
        assert clamp(0.4) == 0.4

    def test_slugify(self):
        assert slugify("Greek Yoghurt!") == "greek-yoghurt"
        assert slugify("") == "item"

    def test_truncate(self):
        assert truncate("hello world", 8) == "hello..."
        assert truncate("short", 40) == "short"


class TestCanonicalName:
    def test_packaging_is_dropped(self):
        assert canonical_name("milk carton") == "milk"
        assert canonical_name("Egg Carton") == "egg"
        assert canonical_name("bag of spinach") == "spinach"

    def test_plurals_are_normalised(self):
        assert canonical_name("eggs") == "egg"
        assert canonical_name("berries") == "berry"

    def test_synonyms(self):
        assert canonical_name("yoghurt") == "yogurt"

    def test_empty(self):
        assert canonical_name("") == ""
        assert canonical_name(None) == ""


class TestSameItem:
    def test_milk_carton_is_milk(self):
        assert same_item("milk carton", "milk") is True
        assert same_item("milk", "milk carton") is True

    def test_egg_carton_is_eggs(self):
        assert same_item("egg carton", "eggs") is True

    def test_yoghurt_is_yogurt(self):
        assert same_item("yoghurt", "yogurt") is True

    def test_different_items(self):
        assert same_item("milk carton", "spinach") is False
        assert same_item("", "milk") is False
