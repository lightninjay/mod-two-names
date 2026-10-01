#!/usr/bin/env python3
"""
mod-two-names: core hook patch for AzerothCore forks that lack the two MiscScript hooks
    CanNormalizePlayerName(std::string& name, bool& result)
    OnCheckPlayerName(std::string_view name, bool create, uint8& result)

What it does (only additive edits, nothing is removed from the core):
  MiscScript.h    - two hook enum values + two virtual methods (default: "not handled")
  MiscScript.cpp  - the two ScriptMgr dispatchers
  ScriptMgr.h     - the two dispatcher declarations
  ObjectMgr.cpp   - calls the hooks at the top of normalizePlayerName() and
                    ObjectMgr::CheckPlayerName(); adds #include "ScriptMgr.h" if missing

Usage (run from anywhere; the core root is auto-detected from this script's location):
    python3 apply_core_patch.py            apply
    python3 apply_core_patch.py --check    verify every anchor is found, change nothing
    python3 apply_core_patch.py --revert   undo the edits
    python3 apply_core_patch.py --core /path/to/azerothcore-wotlk    explicit core root

Safe to run twice (already-applied edits are skipped). Files are only written if every
edit in that file can be applied; on any missing anchor nothing at all is written.
After applying, do a full rebuild (ScriptMgr.h is included almost everywhere).
"""
import argparse, os, sys

MARK = "// mod-two-names"

# (relative path, list of edits). Each edit: (anchor, replacement, kind)
#   kind "replace": anchor text is replaced by replacement (replacement contains the anchor)
FILES = {}

FILES["src/server/game/Scripting/ScriptDefines/MiscScript.h"] = [
    ("#include <vector>\n",
     "#include <string>\n#include <string_view>\n#include <vector>\n"),
    ("    MISCHOOK_GET_DIALOG_STATUS,\n    MISCHOOK_END\n",
     "    MISCHOOK_GET_DIALOG_STATUS,\n"
     "    MISCHOOK_CAN_NORMALIZE_PLAYER_NAME,\n"
     "    MISCHOOK_ON_CHECK_PLAYER_NAME,\n"
     "    MISCHOOK_END\n"),
    ("    virtual void GetDialogStatus(Player* /*player*/, Object* /*questgiver*/) { }\n",
     "    virtual void GetDialogStatus(Player* /*player*/, Object* /*questgiver*/) { }\n"
     "\n"
     "    /**\n"
     "     * @brief Lets a script take over player name normalization (capitalization etc.).\n"
     "     *\n"
     "     * @param name   The name, normalized in place by the script when it handles the call\n"
     "     * @param result Set by the script: true if the name is valid, false if it must be rejected\n"
     "     * @return true if the script handled the call (core logic is skipped), false to fall through\n"
     "     */\n"
     "    [[nodiscard]] virtual bool CanNormalizePlayerName(std::string& /*name*/, bool& /*result*/) { return false; }\n"
     "\n"
     "    /**\n"
     "     * @brief Lets a script take over player name validation.\n"
     "     *\n"
     "     * @param name   The (already normalized) name to check\n"
     "     * @param create True when checking for character creation\n"
     "     * @param result Set by the script: a CHAR_NAME_* response code\n"
     "     * @return true if the script handled the call (core logic is skipped), false to fall through\n"
     "     */\n"
     "    [[nodiscard]] virtual bool OnCheckPlayerName(std::string_view /*name*/, bool /*create*/, uint8& /*result*/) { return false; }\n"),
]

FILES["src/server/game/Scripting/ScriptDefines/MiscScript.cpp"] = [
    ("MiscScript::MiscScript(char const* name, std::vector<uint16> enabledHooks)\n",
     "bool ScriptMgr::CanNormalizePlayerName(std::string& name, bool& result)\n"
     "{\n"
     "    CALL_ENABLED_BOOLEAN_HOOKS_WITH_DEFAULT_FALSE(MiscScript, MISCHOOK_CAN_NORMALIZE_PLAYER_NAME, script->CanNormalizePlayerName(name, result));\n"
     "}\n"
     "\n"
     "bool ScriptMgr::OnCheckPlayerName(std::string_view name, bool create, uint8& result)\n"
     "{\n"
     "    CALL_ENABLED_BOOLEAN_HOOKS_WITH_DEFAULT_FALSE(MiscScript, MISCHOOK_ON_CHECK_PLAYER_NAME, script->OnCheckPlayerName(name, create, result));\n"
     "}\n"
     "\n"
     "MiscScript::MiscScript(char const* name, std::vector<uint16> enabledHooks)\n"),
]

FILES["src/server/game/Scripting/ScriptMgr.h"] = [
    ("    void GetDialogStatus(Player* player, Object* questgiver);\n",
     "    void GetDialogStatus(Player* player, Object* questgiver);\n"
     "    bool CanNormalizePlayerName(std::string& name, bool& result);\n"
     "    bool OnCheckPlayerName(std::string_view name, bool create, uint8& result);\n"),
]

FILES["src/server/game/Globals/ObjectMgr.cpp"] = [
    ("bool normalizePlayerName(std::string& name)\n{\n    if (name.empty())\n",
     "bool normalizePlayerName(std::string& name)\n{\n"
     "    bool hookResult = false;\n"
     "    if (sScriptMgr->CanNormalizePlayerName(name, hookResult))\n"
     "        return hookResult;\n"
     "\n"
     "    if (name.empty())\n"),
    ("uint8 ObjectMgr::CheckPlayerName(std::string_view name, bool create)\n{\n    std::wstring wname;\n",
     "uint8 ObjectMgr::CheckPlayerName(std::string_view name, bool create)\n{\n"
     "    uint8 hookResult = CHAR_NAME_SUCCESS;\n"
     "    if (sScriptMgr->OnCheckPlayerName(name, create, hookResult))\n"
     "        return hookResult;\n"
     "\n"
     "    std::wstring wname;\n"),
]

INCLUDE_LINE = '#include "ScriptMgr.h" ' + MARK + "\n"


def read(path):
    with open(path, "rb") as f:
        raw = f.read().decode("utf-8")
    crlf = "\r\n" in raw
    return raw.replace("\r\n", "\n"), crlf


def write(path, text, crlf):
    if crlf:
        text = text.replace("\n", "\r\n")
    with open(path, "wb") as f:
        f.write(text.encode("utf-8"))


def locate(root, rel):
    """Exact path first; otherwise find a unique file with the same name under src/server."""
    path = os.path.join(root, *rel.split("/"))
    if os.path.isfile(path):
        return path
    base = os.path.basename(rel)
    hits = []
    for d, _, files in os.walk(os.path.join(root, "src", "server")):
        if base in files:
            hits.append(os.path.join(d, base))
    return hits[0] if len(hits) == 1 else None


def plan(root, revert, dry=False):
    """Returns (ok, {path: (newtext, crlf)}, messages)"""
    ok, out, msgs = True, {}, []
    for rel, edits in FILES.items():
        path = locate(root, rel)
        if path is None:
            msgs.append(f"MISSING FILE  {rel}")
            ok = False
            continue
        text, crlf = read(path)
        changed = False
        for anchor, repl in edits:
            first = anchor.splitlines()[0].strip()
            if revert:
                if repl in text:
                    text = text.replace(repl, anchor, 1); changed = True
                    msgs.append(f"reverted      {rel}: {first}")
                else:
                    msgs.append(f"not applied   {rel}: {first}")
            else:
                if repl in text:
                    msgs.append(f"already there {rel}: {first}")
                elif text.count(anchor) == 1:
                    text = text.replace(anchor, repl, 1); changed = True
                    msgs.append(f"{'would patch' if dry else 'patched'}   {rel}: {first}")
                else:
                    msgs.append(f"ANCHOR NOT FOUND ({text.count(anchor)} matches) {rel}: {first}")
                    ok = False
        if rel.endswith("ObjectMgr.cpp"):
            if revert:
                if INCLUDE_LINE in text:
                    text = text.replace(INCLUDE_LINE, "", 1); changed = True
                    msgs.append(f"reverted      {rel}: added #include")
            elif '#include "ScriptMgr.h"' not in text:
                lines = text.split("\n")
                idx = next((i for i, l in enumerate(lines) if l.startswith("#include")), None)
                if idx is None:
                    msgs.append(f"ANCHOR NOT FOUND {rel}: no #include line to attach to")
                    ok = False
                else:
                    lines.insert(idx + 1, INCLUDE_LINE.rstrip("\n"))
                    text = "\n".join(lines); changed = True
                    msgs.append(f"{'would patch' if dry else 'patched'}   {rel}: added #include \"ScriptMgr.h\"")
        if changed:
            out[path] = (text, crlf)
    return ok, out, msgs


def main():
    ap = argparse.ArgumentParser(description="mod-two-names core hook patch")
    ap.add_argument("--core", help="AzerothCore root (default: three levels above this script)")
    ap.add_argument("--check", action="store_true", help="verify anchors only, write nothing")
    ap.add_argument("--revert", action="store_true", help="undo the patch")
    a = ap.parse_args()
    root = a.core or os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", ".."))
    if not os.path.isfile(os.path.join(root, "src", "server", "game", "Globals", "ObjectMgr.cpp")):
        sys.exit(f"'{root}' does not look like an AzerothCore root (src/server/game/Globals/ObjectMgr.cpp not found).\n"
                 f"Use --core /path/to/azerothcore-wotlk")
    ok, out, msgs = plan(root, a.revert, a.check)
    print(f"Core root: {root}")
    print("\n".join("  " + m for m in msgs))
    if not ok:
        sys.exit("\nNothing was written: at least one edit could not be applied cleanly.\n"
                 "Send the ANCHOR/MISSING lines above and the affected file to whoever maintains this patch.")
    if a.check:
        print("\nCheck OK - all anchors found.")
        return
    for path, (text, crlf) in out.items():
        write(path, text, crlf)
    print(f"\nDone. {len(out)} file(s) written." if out else "\nNothing to do.")
    if out and not a.revert:
        print("Now do a FULL rebuild of the core (ScriptMgr.h changed).")


if __name__ == "__main__":
    main()
