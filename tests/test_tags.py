"""Unit tests for tag normalization (SWIT-25).

Tag search uses exact JSONB containment, so casing differences made tags
silently unfindable. normalize_tags is applied at every tool boundary;
these tests pin its contract.
"""

from chat_recall_prod.tags import normalize_tags


class TestNormalizeTags:
    def test_lowercases(self):
        assert normalize_tags(["CAD-1728", "Handoff"]) == ["cad-1728", "handoff"]

    def test_strips_whitespace(self):
        assert normalize_tags(["  kyde  ", "\tposthog\n"]) == ["kyde", "posthog"]

    def test_dedupes_preserving_first_occurrence_order(self):
        assert normalize_tags(["B", "a", "b", "A"]) == ["b", "a"]

    def test_drops_empty_and_whitespace_only(self):
        assert normalize_tags(["", "  ", "real"]) == ["real"]

    def test_none_passthrough(self):
        assert normalize_tags(None) is None

    def test_empty_list_becomes_none(self):
        # Callers use `if tags:` and store NULL for no-tags; an empty result
        # must not flip that to an empty JSON array.
        assert normalize_tags([]) is None
        assert normalize_tags(["", "  "]) is None

    def test_non_string_elements_dropped(self):
        assert normalize_tags(["ok", None, 42, "ALSO"]) == ["ok", "also"]  # type: ignore[list-item]

    def test_already_normalized_unchanged(self):
        tags = ["cad-1728", "apple-watch", "heart-rate"]
        assert normalize_tags(tags) == tags
