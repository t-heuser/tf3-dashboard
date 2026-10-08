# Linux support — plan

Goal: the companion (collector + server + launcher) runs on Linux with the same code as on Windows. Updates touch
one code base; the platform-specific parts are a thin shell shim and the folder detection.

Targets, in priority order:

1. Windows build of TF3 (GOG) run through **Heroic** (native package, not Flatpak) under Wine / GE-Proton — the
   author's setup (CachyOS).
2. **Native Linux** build of TF3 (GOG via Heroic or the standalone GOG installer, and Steam).
3. Steam build under Proton, Heroic Flatpak, Lutris, Bottles, plain Wine — best effort, cheap globs only.

The **mod needs no change**: it runs inside the game (native or under Wine) and only uses the game API.

## What is Windows-only today

| Area | File(s) | Windows-only part |
|---|---|---|
| Launchers | `run_dashboard*.cmd`, `_collector.cmd`, `_server.cmd`, `_python.cmd` | all logic: Python lookup, port check (netstat), first-start icon extraction, retry loop, browser, Windows Terminal panes |
| Userdata detection | `collector/tf3paths.py` | registry, `%APPDATA%`; the Linux branch knows native Steam and `~/.local/share` only, **nothing about Wine/Proton prefixes or Heroic** |
| Game install (icons) | `dashboard/extract_icons.py` `find_game()` | Epic manifests, GOG registry; nothing for Heroic or GOG Linux installers |
| Log cross-check | `tf3paths._same_path` / `game_log` | under Wine `stdout.txt` reports `C:\users\…\AppData\Roaming\…`; compared against a Linux path it is always a "mismatch" (false red error) |
| User-facing text | `tf3paths.not_found_hint` / `sync_warning`, `dashboard/static/i18n.js` (en/fr/de), `app.js` (~line 397) | hard-coded `run_dashboard.cmd`, `%APPDATA%`, `C:\TF3-Dashboard` |
| Release build | `build_release.cmd` | PowerShell only |

Platform-neutral already: collector, server, Lua parser, SQLite schema, frontend, `console.py` (ANSI on POSIX).

## Principle

Move every piece of logic out of the `.cmd` files into Python. The shell scripts on both platforms become shims
("find Python, exec a .py"). Platform differences live only in `tf3paths.py` (where things are) and in a handful of
strings (what to tell the user).

## Phase 1 — userdata detection (`collector/tf3paths.py`)

The core of the work (~40 % of the change).

- **`wine_prefixes()`** -> `(store, prefix)` for:
  - Heroic native: every `~/.config/heroic/GamesConfig/*.json` (`winePrefix`), plus the default prefix glob
    `~/Games/Heroic/Prefixes/*/*`. Identify the TF3 entry through `~/.config/heroic/gog_store/installed.json`
    (GOG), `~/.config/heroic/legendaryConfig/legendary/installed.json` (Epic), `sideload_apps/library.json`.
  - Heroic Flatpak: the same files under `~/.var/app/com.heroicgameslauncher.hgl/config/heroic/`.
  - Steam/Proton: `<each Steam library>/steamapps/compatdata/3493540/pfx`.
  - `$WINEPREFIX`, Lutris (`~/Games/*`), Bottles (`~/.local/share/bottles/bottles/*`). Bounded globs only, never
    a recursive walk of `$HOME`.
  - For each prefix: glob `drive_c/users/*/AppData/Roaming/Transport Fever 3` (covers `steamuser` for
    Proton/GE-Proton and `$USER` for plain Wine).
- **Native Linux userdata**: keep `$XDG_DATA_HOME` (default `~/.local/share`)`/Transport Fever 3`, add the obvious
  variants (`TransportFever3`, `~/.config/Transport Fever 3`). The exact folder of the native GOG build is
  **not verified yet** — see "To verify". The game log cross-check (below) catches a wrong guess.
- **Steam roots**: add Flatpak (`~/.var/app/com.valvesoftware.Steam/.local/share/Steam`) and Snap
  (`~/snap/steam/common/.local/share/Steam`). Native Steam `userdata/<id>/3493540/local` is already scanned.
  Factor out `steam_libraries()` (roots + `libraryfolders.vdf`), shared with `extract_icons.py`.
- **`wine_to_host(win_path, prefix)`**: resolve `X:\…` through `<prefix>/dosdevices/x:` symlinks (fallback
  `C:` -> `drive_c`, `Z:` -> `/`). `game_log()` translates the "User data folder:" line with it when the log was
  found inside a prefix, so the cross-check works under Wine.
- Replace the `str(p).lower()` dedupe keys and the `\\` hack in `_same_path` with
  `os.path.normcase(os.path.realpath(p))` (correct on both platforms; Linux is case-sensitive).
- Store labels for the checklist: `Heroic (Wine)`, `Steam (Proton)`, `GOG (native)`, `Steam (native)`, ...
- "Most recent `live.lua` wins" when several candidates exist; new tie-breaker when no `live.lua` exists yet:
  the most recent `crash_dump/stdout.txt` (the prefix the game actually ran in). `ensure_export_dir` creates
  `dashboard_export` in every root found.
- Introduce `data_dir()` (= ROOT for now) and route `db/`, `config.json`, `icons/` through it. No behaviour change;
  it keeps the door open for a packaged install (phase 6).

## Phase 2 — game install for icons (`dashboard/extract_icons.py`)

- Heroic `gog_store/installed.json` / legendary `installed.json` -> `install_path` (a Linux path, also for Windows
  builds installed through Heroic).
- GOG Linux installers put the game in `<install>/game/`: `_is_game()` checks `<p>` and `<p>/game`.
- Usual native folders: `~/GOG Games/Transport Fever 3`, `~/Games/Transport Fever 3`.
- Steam (native or Proton): `steam_libraries()` from phase 1, unchanged logic.
- Fallback for Wine setups without launcher metadata: `<prefix>/drive_c/{Program Files,Program Files (x86)}/**`
  one level deep (GOG Galaxy / GOG Games folders).
- Open question: whether the native build ships the same `base/content/gui.zip` / `game_mechanics.zip` layout
  (very likely, same engine) — see "To verify".

## Phase 3 — platform-aware text

- `/api/diag` additionally returns `platform`, `launcher` (`run_dashboard.cmd` / `run_dashboard.sh`) and
  `example_export_dir` (built from what detection actually found, e.g. the Heroic prefix path).
- `i18n.js`: replace the hard-coded strings by `{launcher}`, `{ex}`, `{move_to}` placeholders, all three
  languages. `app.js` uses `diag.example_export_dir` instead of the `%APPDATA%` literal.
- `tf3paths.not_found_hint()` / `sync_warning()` branch on `sys.platform`; the Linux hint lists Heroic, native
  GOG and Steam paths. `config.example.json` gets Linux examples next to the Windows ones.

## Phase 4 — one launcher (`launch.py`, new)

Takes over what `_server.cmd`, `_collector.cmd` and `run_dashboard.cmd` do:

1. port check (socket connect to `127.0.0.1:<port>`; replaces netstat);
2. icon extraction when `icons/_manifest.json` is missing;
3. collector + server as subprocesses, output prefixed (`[collector]` / `[server]`), colours kept;
4. restart a crashed child with backoff (replaces the `pause / goto :run` loop);
5. `webbrowser.open(url)` once the port answers (`xdg-open` on Linux);
6. Ctrl+C / SIGTERM stops both.

`--only collector|server` runs a single child with the same checks and retry.

- **Windows**: `run_dashboard.cmd` keeps the Windows Terminal two-pane UX; each pane runs
  `launch.py --only …`. The classic-console fallback runs `launch.py` without arguments. `_python.cmd` stays (it
  finds the bundled Python). `_server.cmd` / `_collector.cmd` shrink to one line or disappear.
- **Linux**: `run_dashboard.sh` (POSIX sh, ~15 lines): pick `python3` / `python` >= 3.10, set
  `PYTHONDONTWRITEBYTECODE=1`, `exec python3 launch.py "$@"`; without Python print a per-distro install hint.
  `run_dashboard_demo.sh` and `collector/run_collector.sh` likewise.
- No bundled Python on Linux: every relevant distro ships >= 3.10 with `sqlite3` (CachyOS: 3.13).

Optional, cheap: `launch.py --install-desktop` writes `~/.local/share/applications/tf3-dashboard.desktop`
(menu entry). Auto-start is phase 5.

## Phase 5 — auto-start

Two modes, both built on the same `launch.py` primitives, user picks one (or both — starting is idempotent).

### Primitives (`launch.py`)

- `--background`: detach and return immediately (a launcher hook must never delay the game). Linux:
  `subprocess.Popen(..., start_new_session=True)`, stdin from `/dev/null`, so the children leave the launcher's
  process group and survive Heroic/Steam cleaning up the game's process tree. Windows:
  `DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP`, `pythonw.exe` from the bundled Python (no console window).
- Logs in background mode: `data_dir()/logs/collector.log`, `server.log`, size-capped and rotated
  (`logging.handlers.RotatingFileHandler`, or plain truncate-on-start, whichever stays smaller). `console.py`
  already prints plain text when stdout is not a terminal.
- Pidfile `data_dir()/run/launch.pid` (supervisor PID + port). **Idempotent start**: if the PID is alive and the
  port answers, `--background` does nothing (exit 0). Stale pidfile -> removed. This also lets a launcher hook
  and the login mode coexist without a second instance.
- `--stop`: SIGTERM to the supervisor (Windows: `taskkill /PID … /T`), which stops both children cleanly, then
  removes the pidfile. Optional `--stop --delay N` (default ~10 s) so the collector ingests the last snapshot
  and the player can still glance at the dashboard after quitting.
- `--status`: running or not, PID, port, URL, log paths, last snapshot age (from `tf3paths.diag()`).
- `--open-on-game`: open the browser only when `live.lua` becomes fresh (age < 2x fast interval), once per
  game session (re-armed when `live.lua` has been stale for > 2 min). Without it: open right after start, as today.
  Browser opening runs in the user's session environment (`DISPLAY` / `WAYLAND_DISPLAY` inherited).

### Mode A — with the game (launcher hooks), primary on Linux

Start when the game starts, stop when it exits.

- **Heroic** (native and Flatpak; native Linux and Wine builds alike): game settings ▸ Advanced ▸ *Scripts* —
  "before launch" `…/run_dashboard.sh --background --open-on-game`, "after exit" `…/run_dashboard.sh --stop`.
  `launch.py --install-autostart heroic` prints the exact lines with absolute paths; it does **not** edit
  Heroic's `GamesConfig/*.json` (Heroic may rewrite the file while it runs and silently drop our change).
  The Flatpak Heroic sandbox cannot see the companion folder by default -> document the
  `flatpak override --user --filesystem=<companion folder> com.heroicgameslauncher.hgl` line.
- **Steam (Linux)**: launch options
  `…/run_dashboard.sh --background --open-on-game; %command%; …/run_dashboard.sh --stop`.
  `--install-autostart steam` prints it. Works for the native build and Proton alike (the part before `%command%`
  runs before the runtime container starts).
- **Windows**: Steam launch options cannot chain commands, GOG Galaxy / Epic have no hooks -> mode B on Windows.
  Heroic on Windows has the same *Scripts* setting; `.cmd` shim `run_dashboard.cmd --background …` covers it.

### Mode B — at login (always on), primary on Windows

The companion idles cheaply until the game writes snapshots: the collector already waits for `live.lua`, the
server costs nothing when nobody polls. Combined with `--open-on-game`, the browser appears when a map is loaded.

- **Linux**: `--install-autostart login` writes `~/.config/autostart/tf3-dashboard.desktop`
  (`Exec=…/run_dashboard.sh --background --open-on-game`). XDG autostart, honoured by KDE/GNOME/most DEs;
  chosen over a `systemd --user` unit because it runs inside the graphical session (browser env vars present
  without `import-environment` tricks). Window managers without XDG autostart: README shows the one line to add.
- **Windows**: `--install-autostart login` writes `TF3 Dashboard.cmd` into the Startup folder
  (`shell:startup`, `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`). No registry Run key, no Task
  Scheduler: visible to the user and deleted like any file.
- `--uninstall-autostart` removes what `--install-autostart login` wrote (and prints how to remove launcher hooks).

### Not in scope

Watching for the game process (psutil-free process polling differs per OS and is fragile under Wine) — the
`live.lua` freshness already says "a map is loaded", which is what matters.

## Phase 6 — release build (`tools/build_release.py`)

- Python (`urllib`, `zipfile`, `tarfile`), runs on Windows, Linux and macOS.
- Outputs:
  - `TF3-Dashboard-<v>-windows.zip`: as today (embedded Python, CRLF forced on `.cmd`);
  - `TF3-Dashboard-<v>-linux.tar.gz`: no Python, LF, `+x` on `.sh` (tar keeps the exec bit, zip often loses it);
  - `tf3_dashboard_export-rev<N>.zip`: unchanged.
- `build_release.cmd` becomes a shim calling it. `.gitattributes`: `*.sh text eol=lf`.
- README: install section split Windows / Linux; DETAILS.md: launcher and detection sections updated.

## Phase 7 — deferred: AUR package

Only if wanted. Needs `data_dir()` to switch to `$XDG_DATA_HOME/tf3-dashboard` for non-portable installs and the
server to serve icons from there (the app currently writes into its own folder, which breaks in `/usr/share`).
Then a PKGBUILD is trivial.

## Order and size

1 -> 2 -> 3 -> 4 -> 5 -> 6 (7 deferred). After phases 1–3, `python3 collector/collector.py` +
`python3 dashboard/server.py` already work completely on Linux; 4–6 are convenience and distribution. Estimate:
600–850 changed/added lines, most in phases 1 and 5.

No automated tests in this round. Manual acceptance on CachyOS:

1. `python3 collector/tf3paths.py` lists the Heroic prefix (Windows build) and/or the native folder, and the
   game log cross-check is green.
2. `./run_dashboard.sh` with a loaded map: snapshots arrive, icons are extracted, the browser opens.
3. Remote control: a command from the dashboard is executed by the game (`cmd.lua` written on Linux, read by the
   game — under Wine and natively).
4. Same for the native Linux build.
5. Auto-start mode A via Heroic scripts: game start -> companion in background, browser opens when the map is
   loaded, game exit -> companion stops after the delay; starting twice does not create a second instance.
6. Auto-start mode B: log out / in -> companion running, idle until a map is loaded.
7. Windows regression: `run_dashboard.cmd` (Windows Terminal and classic console), Startup-folder auto-start,
   release zip.

## Risks

- **Wine file semantics**: the game writes `live.lua` through Wine; the collector polls the mtime and already
  tolerates half-written reads (retry in `collector.py`, around line 842). `cmd.lua` is written with
  `os.replace` = atomic POSIX rename, which the game under Wine sees whole. Medium-high confidence, by reasoning.
- **Several installs at once** (native + Wine, as on the author's machine): the most recent `live.lua` wins, as
  today with several Steam accounts. Acceptable.
- **Steam build under Proton**: unclear whether it writes to the real `Steam/userdata/<id>/3493540/local`
  (through the Steam API) or inside `compatdata`. Both are scanned, so either works.

- **Launcher process cleanup**: Heroic and Steam (reaper / pressure-vessel) may kill everything started from a
  launch hook when the game exits, possibly including a new session. If `start_new_session` is not enough, fall
  back to a double fork + `setsid`, or recommend mode B. Low-medium confidence that the simple version works for
  Steam; medium-high for Heroic.
- **Heroic "after exit" when the game crashes**: if Heroic skips the script, the companion keeps running (harmless,
  idle) and the next "before launch" is a no-op thanks to the idempotent start.

## To verify on the author's machine (before / during phase 1)

- `ls ~/.config/heroic/` and the TF3 entry of `GamesConfig/<appName>.json` (`winePrefix`) and
  `gog_store/installed.json` (`install_path`, `platform`).
- Native build: the "User data folder:" line of its `crash_dump/stdout.txt` (where is userdata really?), and
  whether `base/content/gui.zip` exists in the install folder (directly or under `game/`).
- Heroic version and the exact name/location of the *Scripts* setting (before launch / after exit) in the game
  settings.
