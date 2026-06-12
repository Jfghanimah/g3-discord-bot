from colors import normalize_hex, render_swatches, COLOR_ROLE_RE, PALETTE


class TestNormalizeHex:

    def test_plain_six_digit(self):
        assert normalize_hex("ff5733") == "FF5733"

    def test_with_hash_prefix(self):
        assert normalize_hex("#FF5733") == "FF5733"

    def test_three_digit_expands(self):
        assert normalize_hex("f53") == "FF5533"

    def test_three_digit_with_hash(self):
        assert normalize_hex("#abc") == "AABBCC"

    def test_whitespace_stripped(self):
        assert normalize_hex("  ff5733  ") == "FF5733"

    def test_black_nudged_off_discord_no_color_value(self):
        assert normalize_hex("000000") == "010101"
        assert normalize_hex("#000") == "010101"

    def test_invalid_inputs_rejected(self):
        for bad in ["", "red", "ff573", "ff57333", "gg5733", "#1234", "0xFF5733"]:
            assert normalize_hex(bad) is None, f"expected None for {bad!r}"


class TestColorRolePattern:

    def test_matches_managed_role_names(self):
        assert COLOR_ROLE_RE.match("#FF5733")
        assert COLOR_ROLE_RE.match("#010101")

    def test_ignores_other_roles(self):
        for name in ["Admin", "FF5733", "#ff5733", "#FF573", "#FF57334", "Team #FF5733"]:
            assert not COLOR_ROLE_RE.match(name), f"should not match {name!r}"

    def test_normalized_output_always_matches_role_pattern(self):
        # Every valid input must produce a role name the cleanup sweep recognizes
        for raw in ["ff5733", "#ABC", "000000", "123456"]:
            assert COLOR_ROLE_RE.match(f"#{normalize_hex(raw)}")


class TestPalette:

    def test_palette_hexes_are_valid_and_canonical(self):
        for hex_code in PALETTE:
            assert normalize_hex(hex_code) == hex_code, f"hex {hex_code} not canonical"


class TestRenderSwatches:

    def test_returns_valid_png_bytes(self):
        png = render_swatches([("FF5733", None)], columns=1)
        assert png[:8] == b"\x89PNG\r\n\x1a\n"

    def test_renders_palette_and_labeled_entries_without_error(self):
        # Includes pure white/black (outline path) and multi-column layout
        entries = [(hex_code, f"#{hex_code}  3 members") for hex_code in ("FFFFFF", "010101", "3498DB")]
        assert render_swatches(entries, columns=2)[:8] == b"\x89PNG\r\n\x1a\n"

    def test_empty_entries_does_not_crash(self):
        assert render_swatches([], columns=3)[:8] == b"\x89PNG\r\n\x1a\n"
