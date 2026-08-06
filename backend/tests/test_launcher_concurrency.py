from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_macos_launchers_serialize_before_touching_runtime_state():
    for relative_path in ("desktop/start-council.sh", "desktop/start-bundled.sh"):
        launcher = (ROOT / relative_path).read_text(encoding="utf-8")

        assert "STARTUP_LOCK_FILE=" in launcher
        assert "/usr/bin/shlock" in launcher
        assert "acquire_startup_lock" in launcher
        assert "release_startup_lock" in launcher

        acquire_call = launcher.index("acquire_startup_lock\n")
        token_initialization = launcher.index("umask 077")
        assert acquire_call < token_initialization


def test_native_launcher_does_not_enter_a_privacy_protected_source_directory():
    controller = (
        ROOT / "macos/CouncilNative/Sources/CouncilNative/ServiceController.swift"
    ).read_text(encoding="utf-8")

    assert "process.currentDirectoryURL = FileManager.default.temporaryDirectory" in controller
    assert "process.currentDirectoryURL = script.deletingLastPathComponent()" not in controller
