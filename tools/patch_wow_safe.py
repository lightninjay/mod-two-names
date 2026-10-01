#!/usr/bin/env python3
"""
Safe Wow.exe patcher for mod-two-names (3.3.5a build 12340).

Differences from the repo's patchers:
  * Applies ONLY the ValidateName patch (space support). The second repo patch
    (EditBox::InsertChar length unlock) is NOT applied: with two separate
    12-letter boxes it isn't needed, and it edits a routine shared by every
    edit box in the client (including the login screen's).
  * Verifies the exe before touching it: PE layout must map VA 0x6B0F90 to
    file offset 0x2B0390, and the bytes there must be the documented original
    (55 8B EC 8B 45 08). Anything else -> refuses, changes nothing.
  * Keeps a one-time backup and supports --restore.
  * --status is read-only and dumps both patch sites so you can compare.

Usage:
  python patch_wow_safe.py Wow.exe              (status, read-only)
  python patch_wow_safe.py Wow.exe --apply
  python patch_wow_safe.py Wow.exe --restore
"""
import argparse, hashlib, os, shutil, struct, sys

VALIDATE_VA = 0x006B0F90
VALIDATE_OFF = 0x2B0390
VALIDATE_ORIG = bytes.fromhex("558BEC8B4508")   # push ebp; mov ebp,esp; mov eax,[ebp+8]
VALIDATE_NEW = bytes.fromhex("B857000000C3")    # mov eax,0x57; ret
INPUTCHAR_OFF = 0x564F23                        # repo patch #2 site (dump only)
BACKUP_SUFFIX = ".bak_two_names_safe"


def parse_pe(data):
    if data[:2] != b"MZ":
        raise ValueError("not a PE file (no MZ header)")
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    if data[pe:pe + 4] != b"PE\0\0":
        raise ValueError("PE signature missing")
    nsec = struct.unpack_from("<H", data, pe + 6)[0]
    optsz = struct.unpack_from("<H", data, pe + 20)[0]
    opt = pe + 24
    magic = struct.unpack_from("<H", data, opt)[0]
    if magic != 0x10B:
        raise ValueError("not a 32-bit PE (expected 3.3.5a Wow.exe)")
    image_base = struct.unpack_from("<I", data, opt + 28)[0]
    secs = []
    sec = opt + optsz
    for i in range(nsec):
        name, vsize, va, rawsz, rawptr = struct.unpack_from("<8sIIII", data, sec + 40 * i)
        secs.append((name.rstrip(b"\0").decode(errors="replace"), vsize, va, rawsz, rawptr))
    return image_base, secs


def va_to_off(va, image_base, secs):
    rva = va - image_base
    for name, vsize, sva, rawsz, rawptr in secs:
        if sva <= rva < sva + max(vsize, rawsz):
            return rva - sva + rawptr
    return None


def hexs(b):
    return " ".join(f"{x:02X}" for x in b)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("exe")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--restore", action="store_true")
    a = ap.parse_args()

    if not os.path.isfile(a.exe):
        sys.exit(f"[error] {a.exe} not found")
    bak = a.exe + BACKUP_SUFFIX

    if a.restore:
        if not os.path.isfile(bak):
            sys.exit(f"[error] no backup at {bak}")
        shutil.copyfile(bak, a.exe)
        print(f"[ok] restored {a.exe} from {bak}")
        return

    data = bytearray(open(a.exe, "rb").read())
    print(f"file      : {a.exe}")
    print(f"size      : {len(data)} bytes")
    print(f"sha256    : {hashlib.sha256(data).hexdigest()}")
    try:
        base, secs = parse_pe(data)
    except ValueError as e:
        sys.exit(f"[refuse] {e}")
    print(f"imagebase : 0x{base:08X}")
    for s in secs:
        print(f"  section {s[0]:8s} va=0x{s[2]:08X} vsize=0x{s[1]:X} raw=0x{s[4]:X} rawsize=0x{s[3]:X}")

    mapped = va_to_off(VALIDATE_VA, base, secs)
    print(f"VA 0x{VALIDATE_VA:08X} maps to file offset: "
          f"{'0x%X' % mapped if mapped is not None else 'UNMAPPED'} (patch tools assume 0x{VALIDATE_OFF:X})")
    layout_ok = (mapped == VALIDATE_OFF)
    cur = bytes(data[VALIDATE_OFF:VALIDATE_OFF + 6])
    print(f"ValidateName site bytes : {hexs(cur)}")
    print(f"InputChar site bytes    : {hexs(data[INPUTCHAR_OFF:INPUTCHAR_OFF + 16])}  (repo patch #2 site, not touched)")

    if cur == VALIDATE_ORIG:
        state = "original"
    elif cur == VALIDATE_NEW:
        state = "already patched"
    else:
        state = "UNKNOWN"
    print(f"ValidateName state      : {state}")
    if not layout_ok:
        print("[warn] this exe's layout differs from the stock 12340 layout the offsets were written for.")

    if not a.apply:
        print("\n(read-only status; use --apply to patch)")
        return
    if not layout_ok or state == "UNKNOWN":
        sys.exit("[refuse] exe does not match the expected stock layout/bytes; nothing was changed.")
    if state == "already patched":
        print("[ok] already patched; nothing to do.")
        return
    if not os.path.isfile(bak):
        shutil.copyfile(a.exe, bak)
        print(f"[backup] {bak}")
    data[VALIDATE_OFF:VALIDATE_OFF + 6] = VALIDATE_NEW
    open(a.exe, "wb").write(data)
    print("[ok] ValidateName patched (spaces accepted). Length-unlock patch intentionally NOT applied.")


if __name__ == "__main__":
    main()
