# Required AzerothCore name hooks

Stock AzerothCore does not provide the `MiscScript` hooks used by this module:

- `CanNormalizePlayerName(std::string& name, bool& result)`
- `OnCheckPlayerName(std::string_view name, bool create, uint8& result)`

Without them, Visual Studio reports C3668 / E1455 on the two `override` methods.
The later LNK1181 error for `modules.lib` follows because the module did not compile.
Removing `override` does not fix this: the core would never call these methods.

## Install or upgrade

Update the module, then run these commands from the **AzerothCore source root**
(the directory containing `src`, `modules`, and the top-level `CMakeLists.txt`):

```sh
git -C modules/mod-two-names pull --ff-only
git apply --ignore-space-change --check modules/mod-two-names/patches/azerothcore-name-hooks.patch
git apply --ignore-space-change modules/mod-two-names/patches/azerothcore-name-hooks.patch
```

The commands work in PowerShell, Git Bash, and Linux shells with Git installed.
Re-run CMake Configure and Generate, then rebuild **game, modules, and worldserver**
in the same configuration (for example, Release/x64). Because the patch adds virtual
methods, rebuild all modules and deploy matching binaries together.

Apply the patch once per core checkout. To check whether it is already applied:

```sh
git apply --ignore-space-change --reverse --check modules/mod-two-names/patches/azerothcore-name-hooks.patch
```

A successful reverse check means the patch is present; do not apply it again.
If both checks fail, the core differs or has partial/custom hooks. Review the four
files listed in the patch and adapt the changes to that revision. Do not force the
patch or discard other core changes. The CMake check catches missing hook names;
the compiler still checks their exact signatures through `override`.

## What the patch changes

The patch adds two hook IDs, the `MiscScript` virtual methods, their `ScriptMgr`
dispatchers, and calls at the start of `normalizePlayerName` and
`ObjectMgr::CheckPlayerName`. A handler returns `true` when it has supplied a result.
With no handler, or with `TwoNames.Enable = 0`, the original core logic runs.

This server patch and the client name-entry patch solve separate requirements.
Follow the main README for the client patch and database length setup too.

Prepared against AzerothCore commit
`0781768d0ed1c75de7eb4ec14f03087e71fa9989`. Patch application and configuration
checks are verified separately from a full server build or in-game testing.

## Other Visual Studio diagnostics

The screenshot also reports E0065 in the core's `MapDefines.h`. That is a separate
IntelliSense diagnostic, not evidence of a module hook problem. After applying the
hooks and regenerating the solution, check the **Build** output. If a real compiler
error remains there, report its full message, core commit, and MSVC toolset version.
This patch does not modify `MapDefines.h`.
