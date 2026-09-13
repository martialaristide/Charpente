from pathlib import Path

from charpente import installer
from charpente.dsl.model import Kind, Target, Workspace


def _target(name="MyApp"):
    return Target(name=name, kind=Kind.EXECUTABLE)


# =============================================================================
#  Windows -- Inno Setup script generation
# =============================================================================
def test_inno_script_contains_app_identity_and_paths():
    t = _target()
    script = installer.inno_setup_script(
        Workspace(name="W"), t, Path("build/Release/MyApp"), Path("dist"),
        version="1.2.3", exe_name="MyApp.exe",
    )
    assert "AppName=MyApp" in script
    assert "AppVersion=1.2.3" in script
    assert "OutputBaseFilename=MyApp-setup" in script
    assert r'Source: "build\Release\MyApp\*"' in script
    assert r'Filename: "{app}\MyApp.exe"' in script


def test_inno_script_is_valid_ini_like_sections():
    t = _target()
    script = installer.inno_setup_script(
        Workspace(name="W"), t, Path("build"), Path("dist"), exe_name="MyApp.exe",
    )
    for section in ("[Setup]", "[Files]", "[Icons]", "[Run]"):
        assert section in script


def test_iscc_args_shape():
    args = installer.iscc_args(Path("dist/setup.iss"))
    assert args[0] == "iscc"
    assert str(Path("dist/setup.iss")) in args


# =============================================================================
#  Linux -- .deb staging
# =============================================================================
def test_debian_control_fields():
    t = _target(name="MyApp")
    control = installer.debian_control(t, version="2.0.0", maintainer="Jane <jane@example.com>")
    assert "Package: myapp" in control  # debian package names are conventionally lowercase
    assert "Version: 2.0.0" in control
    assert "Maintainer: Jane <jane@example.com>" in control
    assert "Architecture: amd64" in control


def test_stage_debian_package_lays_out_control_and_binary(tmp_path):
    t = _target(name="MyApp")
    exe = tmp_path / "MyApp"
    exe.write_bytes(b"fake binary")
    staging = tmp_path / "staging"

    installer.stage_debian_package(staging, t, exe, version="1.0.0", maintainer="a <a@b.com>")

    control_file = staging / "DEBIAN" / "control"
    assert control_file.exists()
    assert "Package: myapp" in control_file.read_text()

    installed_bin = staging / "usr" / "local" / "bin" / "MyApp"
    assert installed_bin.exists()
    assert installed_bin.read_bytes() == b"fake binary"


def test_dpkg_deb_args_shape():
    args = installer.dpkg_deb_args(Path("staging"), Path("dist/myapp.deb"))
    assert args[:2] == ["dpkg-deb", "--build"]
    assert str(Path("staging")) in args
    assert str(Path("dist/myapp.deb")) in args


# =============================================================================
#  macOS -- pkgbuild staging
# =============================================================================
def test_pkgbuild_args_shape():
    t = _target(name="MyApp")
    args = installer.pkgbuild_args(Path("staging"), Path("dist/MyApp.pkg"), t, version="1.2.3")
    assert args[0] == "pkgbuild"
    assert "--root" in args
    assert "--identifier" in args
    assert args[args.index("--identifier") + 1] == "com.charpente.myapp"
    assert "--version" in args
    assert args[args.index("--version") + 1] == "1.2.3"
    assert str(Path("dist/MyApp.pkg")) in args


def test_stage_macos_package_lays_out_binary_under_target_name(tmp_path):
    t = _target(name="MyApp")
    exe = tmp_path / "MyApp"
    exe.write_bytes(b"fake binary")
    staging = tmp_path / "staging"

    installer.stage_macos_package(staging, t, exe)

    installed_bin = staging / "MyApp" / "MyApp"
    assert installed_bin.exists()
    assert installed_bin.read_bytes() == b"fake binary"
