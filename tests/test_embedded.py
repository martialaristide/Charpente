"""Bare-metal firmware: settings, flags, images, sizes, flashing, planning. No hardware and no compiler needed;
the real builds (zig freestanding Cortex-M and AVR) are described in docs/plans/phase-4d.md."""
import struct
from pathlib import Path

import pytest
from helpers import GCC

from charpente import cross, embedded, flags, platforms, toolchains
from charpente.core.planner import plan_workspace
from charpente.dsl.model import OS, Kind, Language, Target, Workspace
from charpente.errors import ChError
from charpente.toolchains import Toolchain

ARM_GCC = Toolchain(name="arm-none-eabi", c_compiler="arm-none-eabi-gcc", cxx_compiler="arm-none-eabi-g++",
                    archiver="arm-none-eabi-ar", linker="arm-none-eabi-g++", targets=toolchains._CORTEX_M,
                    cross_only=True, extras=(("objcopy", "arm-none-eabi-objcopy"),))
ZIG = Toolchain(name="zig", c_compiler="/z/zig", cxx_compiler="/z/zig", archiver="/z/zig", linker="/z/zig",
                c_args=("cc",), cxx_args=("c++",), ar_args=("ar",), ld_args=("c++",), targets=toolchains._ZIG_PLATFORMS,
                extras=(("objcopy", "/z/zig"), ("objcopy_args", "objcopy")))


def specialised(tc, name):
    return cross.specialise(tc, platforms.get(name))


# ------------------------------------------------------------------ settings
def test_settings_defaults_and_validation():
    s = embedded.settings_from("fw", {})
    assert s.entry == "Reset_Handler" and s.specs == "nano" and not s.exceptions
    for raw, fragment in (({"colour": 1}, "unknown setting"), ({"entry": "not a symbol"}, "C symbol"),
                          ({"float_abi": "fast"}, "float_abi"), ({"specs": "x"}, "specs"),
                          ({"flash": "magic"}, "flash must be"), ({"mcu": "atmega 328"}, "not a valid name")):
        with pytest.raises(ChError) as exc:
            embedded.settings_from("fw", raw)
        assert exc.value.code == "CH8006" and fragment in str(exc.value)
    assert embedded.settings_from("fw", {"flash_args": "-x"}).flash_args == ("-x",)


# ------------------------------------------------------------------ flags
def test_gnu_arm_flags_follow_the_platform_cpu():
    tc = specialised(ARM_GCC, "cortexm4-arm")
    s = embedded.settings_from("fw", {})
    assert embedded.cpu_flags(tc, s) == ["-mcpu=cortex-m4", "-mthumb", "-mfloat-abi=hard", "-mfpu=fpv4-sp-d16"]
    m0 = specialised(ARM_GCC, "cortexm0-arm")
    assert embedded.cpu_flags(m0, s) == ["-mcpu=cortex-m0", "-mthumb", "-mfloat-abi=soft"]      # no FPU flag when soft
    override = embedded.settings_from("fw", {"cpu": "cortex-m4", "float_abi": "softfp", "fpu": "fpv4-sp-d16"})
    assert "-mfloat-abi=softfp" in embedded.cpu_flags(m0, override)


def test_zig_takes_its_cpu_from_the_triple_and_a_cpu_flag():
    tc = specialised(ZIG, "cortexm7-arm")
    assert tc.cxx_args == ("c++", "-target", "thumb-freestanding-eabihf")
    assert embedded.cpu_flags(tc, embedded.settings_from("fw", {})) == ["-mcpu=cortex_m7"]


def test_avr_needs_its_part_name():
    tc = specialised(ZIG, "avr-avr")
    assert tc.c_args == ("cc", "-target", "avr-freestanding")
    with pytest.raises(ChError) as exc:
        embedded.cpu_flags(tc, embedded.settings_from("fw", {}))
    assert "mcu" in str(exc.value)
    assert embedded.cpu_flags(tc, embedded.settings_from("fw", {"mcu": "atmega328p"})) == ["-mmcu=atmega328p"]


def test_compile_flags_are_freestanding_and_cxx_drops_exceptions_unless_asked():
    tc = specialised(ARM_GCC, "cortexm3-arm")
    s = embedded.settings_from("fw", {})
    c = embedded.compile_flags(tc, s, cxx=False)
    assert {"-ffreestanding", "-ffunction-sections", "-fdata-sections"} <= set(c) and "-fno-exceptions" not in c
    cxx = embedded.compile_flags(tc, s, cxx=True)
    assert {"-fno-exceptions", "-fno-rtti"} <= set(cxx)
    assert "-fno-exceptions" not in embedded.compile_flags(tc, embedded.settings_from("fw", {"exceptions": True}), True)


def test_link_flags_differ_between_gnu_and_zig():
    root = Path("/proj")
    s = embedded.settings_from("fw", {"linker_script": "link.ld", "entry": "Start"})
    gnu = embedded.link_flags(specialised(ARM_GCC, "cortexm4-arm"), s, root, Path("out.map"))
    assert "-nostartfiles" in gnu and "--specs=nano.specs" in gnu and "-Wl,-Map=out.map" in gnu
    assert gnu[gnu.index("-T") + 1] == str(root / "link.ld") and "-Wl,-e,Start" in gnu and "-Wl,--gc-sections" in gnu
    zig = embedded.link_flags(specialised(ZIG, "cortexm4-arm"), s, root, Path("out.map"))
    assert "-nostdlib" in zig and not any("Map" in a for a in zig) and "--specs=nano.specs" not in zig
    assert "--specs=nano.specs" not in embedded.link_flags(specialised(ARM_GCC, "cortexm4-arm"),
                                                           embedded.settings_from("fw", {"specs": "none"}), root, None)


def test_is_baremetal_only_for_microcontroller_platforms():
    assert embedded.is_baremetal(specialised(ARM_GCC, "cortexm4-arm"))
    assert not embedded.is_baremetal(GCC) and not embedded.is_baremetal(specialised(ZIG, "linux-arm64"))


# ------------------------------------------------------------------ images
def test_objcopy_command_lines():
    gnu = specialised(ARM_GCC, "cortexm4-arm")
    assert embedded.objcopy_argv(gnu, "bin", Path("a.elf"), Path("a.bin")) == [
        "arm-none-eabi-objcopy", "-O", "binary", "a.elf", "a.bin"]
    assert embedded.objcopy_argv(gnu, "hex", Path("a.elf"), Path("a.hex"))[1:3] == ["-O", "ihex"]
    zig = specialised(ZIG, "cortexm4-arm")
    assert embedded.objcopy_argv(zig, "hex", Path("a.elf"), Path("a.hex")) == ["/z/zig", "objcopy", "-O", "hex", "a.elf", "a.hex"]
    with pytest.raises(ChError):
        embedded.objcopy_argv(GCC, "bin", Path("a.elf"), Path("a.bin"))


def _elf32(sections):
    """A minimal 32-bit little-endian ELF whose section table is `sections` = [(type, flags, size)]."""
    header_size, sh_size = 52, 40
    shoff = header_size
    header = bytearray(b"\x7fELF" + bytes([1, 1, 1]) + bytes(9))
    header += struct.pack("<HHIIIIIHHHHHH", 2, 40, 1, 0, 0, shoff, 0, header_size, 0, 0, sh_size, len(sections), 0)
    table = b"".join(struct.pack("<IIIIIIIIII", 0, kind, flags, 0, 0, size, 0, 0, 1, 0) for kind, flags, size in sections)
    return bytes(header) + table


def test_elf_sizes_classify_like_the_size_command(tmp_path):
    elf = tmp_path / "a.elf"
    elf.write_bytes(_elf32([(0, 0, 0), (1, 0x6, 100), (1, 0x2, 40), (1, 0x3, 8), (8, 0x3, 24), (1, 0x0, 999)]))
    sizes = embedded.elf_sizes(elf)
    assert (sizes.text, sizes.data, sizes.bss) == (140, 8, 24)         # the non-alloc section (999) is ignored
    assert sizes.flash == 148 and sizes.ram == 32


def test_elf_sizes_refuses_other_formats(tmp_path):
    bad = tmp_path / "x.bin"
    bad.write_bytes(b"not an elf at all")
    with pytest.raises(ChError) as exc:
        embedded.elf_sizes(bad)
    assert exc.value.code == "CH8008"
    elf64 = tmp_path / "x64.elf"
    elf64.write_bytes(b"\x7fELF\x02\x01\x01" + bytes(60))
    with pytest.raises(ChError):
        embedded.elf_sizes(elf64)


def test_memory_regions_and_the_size_report():
    script = "MEMORY { FLASH (rx) : ORIGIN = 0x08000000, LENGTH = 256K\n RAM (rwx) : ORIGIN = 0x20000000, LENGTH = 0x10000 }"
    assert embedded.memory_regions(script) == {"FLASH": 262144, "RAM": 65536}
    assert embedded.memory_regions("SECTIONS { }") == {}
    report = embedded.size_report(embedded.Sizes(text=1000, data=24, bss=100), {"FLASH": 2048, "RAM": 1024})
    assert "FLASH: 1024 / 2048 bytes (50%)" in report and "RAM: 124 / 1024 bytes (12%)" in report
    assert embedded.parse_size("1M") == 1048576 and embedded.parse_size("nope") is None


# ------------------------------------------------------------------ flashing
def test_flash_commands_are_argument_lists():
    elf, image = Path("/b/fw.elf"), Path("/b/fw.hex")
    assert embedded.flash_argv("openocd", elf, ["-f", "a.cfg"]) == [
        "openocd", "-f", "a.cfg", "-c", "program {/b/fw.elf} verify reset exit"]
    assert embedded.flash_argv("pyocd", elf, ["-t", "stm32"]) == ["pyocd", "flash", "-t", "stm32", str(elf)]
    assert embedded.flash_argv("probe-rs", elf, []) == ["probe-rs", "download", str(elf)]
    assert embedded.flash_argv("avrdude", elf, ["-p", "m328p"], image=image)[-2:] == ["-U", f"flash:w:{image}:i"]
    assert embedded.flash_argv("esptool", elf, [], image=image)[-3:] == ["write_flash", "0x0", str(image)]
    assert embedded.flash_argv("dfu-util", elf, [], image=image)[-2:] == ["-D", str(image)]
    for tool in ("avrdude", "esptool", "dfu-util"):
        with pytest.raises(ChError):
            embedded.flash_argv(tool, elf, [])
    with pytest.raises(ChError):
        embedded.flash_argv("magic", elf, [])


# ------------------------------------------------------------------ planning
def _firmware_workspace(tmp_path, **settings):
    (tmp_path / "main.c").write_text("x")
    ws = Workspace(name="W", location=tmp_path)
    ws.add_target(Target(name="fw", kind=Kind.FIRMWARE, language=Language.C, standard="c11",
                         source_patterns=["*.c"], location=tmp_path,
                         platform_settings={"embedded": {"linker_script": "link.ld", **settings}}))
    return ws


def test_a_firmware_plan_links_an_elf_and_derives_bin_and_hex(tmp_path):
    tc = specialised(ARM_GCC, "cortexm4-arm")
    plan = plan_workspace(_firmware_workspace(tmp_path), tc, OS.BAREMETAL)
    assert not plan.errors
    link = next(a for a in plan.graph.actions.values() if a.kind == "link")
    assert [p.suffix for p in link.outputs] == [".elf", ".map"]
    assert any(a == "-T" for a in link.argv) and "-nostartfiles" in link.argv
    images = [a for a in plan.graph.actions.values() if a.kind == "custom"]
    assert sorted(a.outputs[0].suffix for a in images) == [".bin", ".hex"]
    assert all(a.inputs == link.outputs[:1] and a.argv[0] == "arm-none-eabi-objcopy" for a in images)
    compile_action = next(a for a in plan.graph.actions.values() if a.kind == "compile")
    assert "-mcpu=cortex-m4" in compile_action.argv and "-ffreestanding" in compile_action.argv


def test_zig_firmware_has_no_map_file(tmp_path):
    plan = plan_workspace(_firmware_workspace(tmp_path), specialised(ZIG, "cortexm0-arm"), OS.BAREMETAL)
    link = next(a for a in plan.graph.actions.values() if a.kind == "link")
    assert [p.suffix for p in link.outputs] == [".elf"]


def test_firmware_is_refused_outside_bare_metal(tmp_path):
    assert plan_workspace(_firmware_workspace(tmp_path), GCC, OS.LINUX).errors["fw"].code == "CH3007"


# ------------------------------------------------------------------ platforms and detection
def test_microcontroller_platforms_and_who_can_build_them():
    for name in ("cortexm0-arm", "cortexm3-arm", "cortexm4-arm", "cortexm7-arm", "cortexm33-arm", "avr-avr"):
        platform = platforms.get(name)
        assert platform.family == "embedded" and platform.os == "baremetal"
        assert cross.can_target(ZIG, platform)
    assert not cross.can_target(ARM_GCC, platforms.get("avr-avr"))
    assert platforms.get("esp32-xtensa").tier == 3 and "not integrated" in platforms.get("esp32-xtensa").needs


def test_vendor_toolchains_are_detected_and_never_native():
    which = lambda n: f"/opt/{n}" if n.startswith(("arm-none-eabi", "avr-")) else None          # noqa: E731
    found = {t.name: t for t in toolchains.detect(OS.LINUX, which)}
    assert {"arm-none-eabi", "avr-gcc"} <= set(found)
    assert found["arm-none-eabi"].cross_only and dict(found["arm-none-eabi"].extras)["objcopy"] == "/opt/arm-none-eabi-objcopy"
    with pytest.raises(ChError):
        toolchains.pick_default(OS.LINUX, which)


def test_output_names_for_firmware():
    tc = specialised(ARM_GCC, "cortexm4-arm")
    assert flags.output_filename(Target(name="fw", kind=Kind.FIRMWARE), OS.BAREMETAL, tc) == "fw.elf"
    assert flags.side_outputs(Target(name="fw", kind=Kind.FIRMWARE), OS.BAREMETAL, Path("o/fw.elf"), tc) == [Path("o/fw.map")]


# ------------------------------------------------------------------ UF2
def test_uf2_blocks_carry_the_image_address_and_family():
    from charpente import uf2

    image = bytes(range(256)) * 2 + b"tail"
    blob = uf2.bin_to_uf2(image, 0x10000000, uf2.FAMILIES["rp2040"])
    assert len(blob) == 3 * 512
    blocks = uf2.parse_uf2(blob)
    assert [b[0] for b in blocks] == [0x10000000, 0x10000100, 0x10000200]
    assert [b[2] for b in blocks] == [0, 1, 2] and {b[3] for b in blocks} == {3} and {b[4] for b in blocks} == {0xE48BFF56}
    assert b"".join(b[1] if i < 2 else b[1][:4] for i, b in enumerate(blocks)) == image
    assert uf2.bin_to_uf2(b"", 0, 1) == b""
    with pytest.raises(ValueError):
        uf2.bin_to_uf2(b"x", 2 ** 33, 1)
    with pytest.raises(ValueError):
        uf2.parse_uf2(b"short")
    with pytest.raises(ValueError):
        uf2.parse_uf2(b"\x00" * 512)


def test_uf2_runs_as_a_program_and_settings_are_validated(tmp_path):
    from charpente import uf2

    src = tmp_path / "a.bin"
    src.write_bytes(b"\x01" * 300)
    assert uf2.main([str(src), str(tmp_path / "a.uf2"), "--base", "0x08000000", "--family", "stm32f4"]) == 0
    assert len(uf2.parse_uf2((tmp_path / "a.uf2").read_bytes())) == 2
    for raw in ({"uf2_base": "0x1000"}, {"uf2_family": "rp2040"}, {"uf2_base": "zzz", "uf2_family": "rp2040"},
                {"uf2_base": "0x1000", "uf2_family": "notafamily"}):
        with pytest.raises(ChError):
            embedded.settings_from("fw", raw)
    s = embedded.settings_from("fw", {"uf2_base": "0x10000000", "uf2_family": "rp2040"})
    argv = embedded.uf2_argv(Path("a.bin"), Path("a.uf2"), s)
    assert argv[1:3] == ["-m", "charpente.uf2"] and argv[-4:] == ["--base", "0x10000000", "--family", "rp2040"]


def test_a_uf2_setting_adds_a_cached_conversion_action(tmp_path):
    ws = _firmware_workspace(tmp_path, uf2_base="0x10000000", uf2_family="rp2040")
    plan = plan_workspace(ws, specialised(ZIG, "cortexm0-arm"), OS.BAREMETAL)
    suffixes = sorted(a.outputs[0].suffix for a in plan.graph.actions.values() if a.kind == "custom")
    assert suffixes == [".bin", ".hex", ".uf2"]
