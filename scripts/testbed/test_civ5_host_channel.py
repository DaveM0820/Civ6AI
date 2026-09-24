from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parent))

from civ5_host_channel import (
    APPLY_PENDING_LUA,
    build_apply_lines,
    civ5_apply_pending_dirs,
    clear_pending_apply_lua,
    inject_apply_lines,
    write_pending_apply_lua,
)


def test_write_pending_apply_skips_mod_vfs():
    with tempfile.TemporaryDirectory() as tmp:
        civ5ai = Path(tmp) / "civ5ai"
        expansion2 = Path(tmp) / "Expansion2" / "UI" / "InGame"
        expansion2.mkdir(parents=True)
        mod_lua = Path(tmp) / "MODS" / "Civ5Ai" / "Lua"
        mod_lua.mkdir(parents=True)
        with __import__("unittest.mock").mock.patch(
            "civ5_host_channel.civ5_apply_pending_dirs",
            return_value=[civ5ai],
        ):
            write_pending_apply_lua('{"commands":[]}', "sess", 1, 2)
        assert (civ5ai / APPLY_PENDING_LUA).is_file()
        text = (civ5ai / APPLY_PENDING_LUA).read_text(encoding="utf-8")
        assert "Civ5Ai_ApplyPendingMeta" in text
        assert "player = 1" in text
        assert "turn = 2" in text
        assert not (expansion2 / APPLY_PENDING_LUA).exists()
        assert not (mod_lua / APPLY_PENDING_LUA).exists()


def test_clear_pending_apply_lua_removes_host_file():
    with tempfile.TemporaryDirectory() as tmp:
        civ5ai = Path(tmp) / "civ5ai"
        civ5ai.mkdir()
        pending = civ5ai / APPLY_PENDING_LUA
        pending.write_text("pending\n", encoding="utf-8")
        with __import__("unittest.mock").mock.patch(
            "civ5_host_channel.civ5_apply_pending_dirs",
            return_value=[civ5ai],
        ):
            clear_pending_apply_lua()
        assert not pending.exists()


def test_civ5_apply_pending_dirs_never_lists_mod_lua():
    for directory in civ5_apply_pending_dirs():
        text = str(directory).replace("\\", "/").lower()
        assert text.endswith("/runtime")
        assert "/mods/civ5ai/runtime" in text
        assert "/lua" not in text
        assert "overrides" not in text
        assert "expansion2" not in text


def test_build_apply_lines_prefix():
    lines = build_apply_lines('{"commands":[]}', "sess", 1, 0)
    assert len(lines) == 1
    assert lines[0].startswith("CIV5AI|apply|full|1|0|sess|")


def test_inject_apply_lines_does_not_import_civ6():
    import civ5_host_channel as module

    captured = {}

    def fake_inject(lines):
        captured["lines"] = list(lines)
        return True

    module.inject_civ5_inbox_lines = fake_inject
    assert inject_apply_lines(["CIV5AI|apply|end|abc"]) is True
    assert captured["lines"] == ["CIV5AI|apply|end|abc"]
    assert "civ6_ui_automation" not in sys.modules


if __name__ == "__main__":
    test_write_pending_apply_skips_mod_vfs()
    test_clear_pending_apply_lua_removes_host_file()
    test_civ5_apply_pending_dirs_never_lists_mod_lua()
    test_build_apply_lines_prefix()
    test_inject_apply_lines_does_not_import_civ6()
    print("ok")
