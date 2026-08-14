# Compendium Desktop — build & share guide

This turns Compendium into a **double-click desktop app** each teammate runs on
their own PC, with their **own private copy of the data**. Great for beta
testing: everyone works independently, and you gather their notes later.

There are two parts: **you build it once** (Part A), then **each teammate
just runs it** (Part B). Teammates do **not** need Python or any setup.

---

## Part A — Build the app (you, once)

You'll do this on your Windows PC — the same one where you already run
`python app.py`, so you already have what's needed.

1. In GitHub Desktop, **Pull origin** so you have the latest Compendium. Run it
   once (`python app.py`) and check the footer — it shows the current
   **Version** (e.g. **Version 14.2**). That number is what you'll confirm in
   the rebuilt app and what beta testers report back to you.
2. Open the project folder on your computer, then open the **`desktop`**
   folder inside it.
3. **Double-click `Build-Compendium-Windows.bat`.**
   - A black window opens and works for a few minutes (it downloads a
     packaging tool the first time, then builds the app).
   - When it says **DONE!**, you can close the window.
4. Back in the project folder, open the new **`dist`** folder. Inside is a
   **`Compendium`** folder — that's the finished app.
5. **Right-click the `Compendium` folder → Send to → Compressed (zipped)
   folder.** That `Compendium.zip` is what you send to your team.

> If the build ever fails, copy the red text from the black window and send
> it to me — that tells me exactly what to fix.
>
> **"Access is denied" during the build?** That means a copy of Compendium was
> still running and had its own files locked. Close every open **Compendium
> window** (the black console windows) and any Explorer window sitting in
> `dist\Compendium`, then run the build again. The script now tries to close a
> running Compendium and clear the old `dist`/`build` folders for you first, so
> this should be rare.

---

## Part B — Give it to a teammate (each person)

Send them `Compendium.zip` (email, Teams, a shared drive — whatever you use).
Tell them:

1. **Right-click `Compendium.zip` → Extract All…** Put the folder somewhere
   easy, like the Desktop. (Don't run it from *inside* the zip — extract
   first.)
2. Open the extracted **`Compendium`** folder and **double-click `Compendium.exe`.**
3. The first time, Windows may show a blue **"Windows protected your PC"**
   box (because the app isn't from the Microsoft Store). Click
   **More info → Run anyway.** This is expected for an in-house tool.
4. A black window appears and Compendium **opens in their web browser**. That's
   it — they're using Compendium.

**To make a desktop shortcut** (so they don't dig into the folder each
time): right-click `Compendium.exe` → **Send to → Desktop (create shortcut)**.
Rename the shortcut "Compendium" if they like.

**To quit Compendium:** close the black window.

---

## Bringing existing data into the app (first launch only)

If you already have Compendium data — a `job_creator.db` and its `uploads`
folder from the web/dev version or from another machine — Compendium can adopt
it automatically the **very first time** it starts (before any account is
created):

1. Make a folder named **`Compendium-Import`** and put your `job_creator.db`
   inside it. If you also have an **`uploads`** folder, drop that in
   alongside the database.
2. Place that `Compendium-Import` folder **next to `Compendium.exe`** (in the same
   extracted `Compendium` folder), *or* in your **Downloads** folder.
3. Start `Compendium.exe`. The black window prints **"Imported your existing
   database…"** and your clients, jobs, employees and logins are all there.

This runs **only once** — as soon as `C:\Users\<you>\Compendium\job_creator.db`
exists, Compendium uses that and never overwrites it, so re-launching is always
safe. (Advanced: point the environment variable `COMPENDIUM_IMPORT` at a `.db`
file or a folder to import from somewhere else.) A one-line record of what
was imported is written to `C:\Users\<you>\Compendium\compendium-import.log`.

---

## Good to know

- **Everyone's data is separate.** Each person's database and uploaded
  files are saved in a personal folder: `C:\Users\<their name>\Compendium`
  (the black window prints the exact path). Nothing is shared between
  teammates — exactly what we want for independent beta testing.
- **Backing up / collecting data:** that `Compendium` folder (which contains
  `job_creator.db` and the `uploads` folder) *is* their data. To hand you
  their work, they can zip and send that folder.
- **Sending an update later:** rebuild (Part A), send the new `Compendium.zip`,
  and have them replace their old `Compendium` app folder with it. Their
  personal data folder is **untouched**, so nothing is lost.
- **Antivirus:** some antivirus tools are suspicious of brand-new,
  unsigned `.exe` files. If one blocks `Compendium.exe`, allow/whitelist it —
  it's your own software. (Down the road, a hosted server version avoids
  this entirely — see the roadmap.)

---

## Where this is heading (not built yet)

This desktop package is the **beta** step. The planned path from here:
a **private-server** version everyone opens in a browser (no install at
all), **per-employee assigned job tasks** with an **offline mode** that
syncs when reconnected, and then **Android** (and later **iPhone**) access.
Those build on the same web app, so this work isn't throwaway — it's the
foundation.
