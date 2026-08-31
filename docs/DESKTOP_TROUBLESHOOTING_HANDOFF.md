# Handoff — Compendium Desktop won't launch on some devices

**For:** a fresh Claude thread helping Rachel (non-technical, Windows,
GitHub Desktop) get the Compendium desktop app running on another household device.
**Repo:** `Rachel-Inman-88/Vixinman_Household_Compendium` · app is Flask + SQLite + Jinja,
packaged for Windows with PyInstaller. **Please read this whole doc before advising.**

---

## The symptom (Rachel's words)

> "We can find the exe file, and when we try to run it we get a typical Windows
> 'are you sure you want to run this software' warning, but when we push it to
> 'run anyway' the command prompt briefly flashes on-screen and then nothing
> happens."

The Windows SmartScreen warning ("Windows protected your PC" → *More info → Run
anyway*) is **expected** for an unsigned in-house app — that part is fine. The
real problem is the **console window flashing and vanishing**: that means the
program **started and then crashed during startup**, and the console closed
before the error could be read. This is *not* "nothing happened" — it's an
error you can't see yet. The whole job is to surface that error and fix its
cause.

Note it reportedly works on the **build machine** but fails on **other
devices** — that pattern points hard at causes #1 and #2 below (something
present on the build PC but missing on a clean target).

---

## How the package is built (so you know what "should" happen)

- Entry point: **`desktop/run_compendium.py`** — sets the data folder to
  `C:\Users\<name>\Compendium`, imports the Flask `app`, runs `init_db()`, picks a
  free localhost port, starts the dev server, and opens the browser. On success
  the **console stays open** (the server blocks) and the browser opens Compendium.
- Recipe: **`desktop/compendium.spec`** — PyInstaller **one-folder** build
  (`COLLECT`, `console=True`). Output is `dist/Compendium/` containing
  **`Compendium.exe` PLUS an `_internal/` folder** (bundled Python, Flask, the
  Jinja `templates/`, and `schema.sql`). **The exe cannot run without its
  `_internal/` folder sitting next to it.**
- Build script: **`desktop/Build-Compendium-Windows.bat`** (run on Windows).
- Data (the SQLite DB + uploads) lives OUTSIDE the app, in
  `C:\Users\<name>\Compendium`, so updates don't wipe data.
- Full user guide: **`desktop/README-DESKTOP.md`**.

---

## First: SEE the error (two ways — do at least one)

### Option A — no rebuild needed: run it from a Command Prompt
This keeps the window open so the crash text is visible.
1. On the failing device, open the folder that contains `Compendium.exe`.
2. Click the address bar of that File Explorer window, type `cmd`, press Enter
   (a Command Prompt opens **in that folder**).
3. Type `Compendium.exe` and press Enter.
4. **The error/traceback now stays on screen.** Copy all of it — that text is
   the single most useful thing for diagnosis.

### Option B — rebuild with the crash-logging launcher (already in the repo)
As of **Piece 11.1**, `desktop/run_compendium.py` was hardened so that any startup
crash is (a) written to **`C:\Users\<name>\Compendium\compendium-startup-error.log`**
and (b) shown in a window that **waits for a keypress** instead of closing.
Steps: in GitHub Desktop **Pull origin**, re-run
`desktop/Build-Compendium-Windows.bat`, reship the new `Compendium` folder, and have
the teammate double-click it again. Now the window stays open with the error,
and the same text is saved in that log file to send back.

Whichever option: **get the actual error text.** Everything below is about
matching that text to a cause.

---

## Most likely causes, ranked — with checks and fixes

### 1. Only `Compendium.exe` was copied, not the whole `Compendium` folder  ← most common
A one-folder PyInstaller build needs `Compendium.exe` **and** its `_internal/`
folder together. If someone right-clicked just the exe and copied/emailed only
that (or made a shortcut and sent the shortcut), it crashes instantly.
- **Check:** on the failing device, is there an **`_internal`** folder in the
  same directory as `Compendium.exe`? If not, this is it.
- **Fix:** transfer the **entire `Compendium` folder** (zip the whole folder, send
  the zip, Extract All on the other end, then run the exe from inside the
  extracted folder). Don't run it from *inside* the .zip preview either.

### 2. Missing Microsoft Visual C++ Runtime on a clean device  ← common on "other devices"
A frozen Python app needs the MSVC runtime DLLs. The build PC has them (Python
installed them); a fresh Windows install may not.
- **Check:** the error mentions `VCRUNTIME140.dll`, `api-ms-win-crt-*.dll`, or
  "DLL load failed while importing ...".
- **Fix:** install the **Microsoft Visual C++ Redistributable (x64)** on the
  target device (Microsoft's "vc_redist.x64.exe"), then retry.

### 3. Antivirus quarantined part of the app after "Run anyway"
Some AV deletes/locks files in a brand-new unsigned folder even after the user
clicks through SmartScreen.
- **Check:** does the AV history/quarantine show `Compendium.exe` or files under
  `_internal`? Does the folder still contain all its files after the flash?
- **Fix:** restore from quarantine and whitelist the `Compendium` folder (it's
  first-party software). Longer term, code-signing avoids this.

### 4. Can't create the data folder / permissions
`run_compendium.py` writes to `C:\Users\<name>\Compendium`. On a locked-down/roaming
profile this can fail.
- **Check:** error mentions `PermissionError` or a path under `\Users\...\Compendium`.
- **Fix:** ensure the user profile is writable; as a test, the data dir can be
  redirected by setting the `COMPENDIUM_DATA_DIR` environment variable to a
  writable path before launch.

### 5. Architecture / Windows-version mismatch
Built on 64-bit Windows but run on 32-bit, or a much older Windows.
- **Check:** error like "not a valid Win32 application", or it won't start at
  all with no Python traceback.
- **Fix:** confirm target devices are 64-bit Windows 10/11; rebuild per target
  arch if truly needed.

---

## What to collect and send back (so the next fix is one round-trip)

- [ ] The **full error text** from Option A or the contents of
      `compendium-startup-error.log` from Option B.
- [ ] Is there an **`_internal`** folder next to `Compendium.exe` on the failing
      device? (yes/no)
- [ ] **Windows version** of the failing device (Win10/Win11, 64-bit?).
- [ ] Which **antivirus** is running.
- [ ] Does it run on the **build machine** itself? (Confirms the build is good
      and it's a transfer/target-environment issue.)
- [ ] **How the app was moved** to the other device (zipped whole folder? just
      the exe? shared drive? shortcut?).

---

## Guardrails for whoever picks this up

- The app itself is verified working — this is a **packaging/deployment**
  problem, not an application bug. Don't start changing app features.
- The single highest-value action is **getting the startup error text**
  (Option A or B). Don't guess a fix before seeing it.
- Rachel is non-technical and on Windows via GitHub Desktop. Give exact,
  click-by-click steps. Avoid asking her to use developer tooling beyond
  "open a Command Prompt in this folder and type one command."
- Relevant files to look at: `desktop/run_compendium.py`, `desktop/compendium.spec`,
  `desktop/Build-Compendium-Windows.bat`, `desktop/README-DESKTOP.md`, and `app.py`
  (top of file: `BASE_DIR` / `DATA_DIR` / `sys._MEIPASS` handling).
