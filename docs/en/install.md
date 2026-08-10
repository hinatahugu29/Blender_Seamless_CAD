# Installation

Seamless CAD installs like any other Blender add-on, from a `.zip`. There is
nothing else to install — the geometry kernel and every library it needs are
inside that zip.

If you just want to start modelling, do the four steps below and go to the
[Quick Start](quickstart.md). The rest of this page is for when something does
not go the way it should.

## Requirements

| | |
|---|---|
| Blender | 4.2 or newer. Tested on 4.2, 4.3, 4.4 and 5.1 |
| Windows | 10 or 11, 64-bit. This is the released product |
| macOS | Apple Silicon, macOS 11+. [Testing build](testing-builds.md), not on sale |
| Linux | x86-64, glibc 2.34+. [Testing build](testing-builds.md), not on sale |
| Disk | About 135 MB once installed |

No separate CAD software, no CAD licence, and no runtime to install alongside.
The Microsoft Visual C++ runtime is bundled too, so you do not need to install
that either.

## Install

1. In Blender, open `Edit > Preferences > Add-ons`
2. From the **∨** menu at the top right of that panel, choose
   **Install from Disk…**
3. Select the `CAD_<version>_install.zip` file you were given
4. Enable the add-on in the list

Then press <kbd>N</kbd> in the 3D viewport to open the sidebar. A **Seamless**
tab appears there. That tab is the whole interface.

<!-- TODO(image): Preferences > Add-ons with the "Install from Disk…" menu open -->

> **This ships as a classic add-on, not as a Blender Extension.** The zip
> contains no `blender_manifest.toml`, so drag-and-drop onto the Blender window
> and the Extensions repository listing do not apply to it. Use
> **Install from Disk…**.

## Where it lands

Knowing this is useful when updating or when reporting a problem. The installed
folder is named `CAD_8_1_5_1` **regardless of the version in the filename** — the
directory name has not been renamed as versions advanced.

| | |
|---|---|
| Windows | `%APPDATA%\Blender Foundation\Blender\<version>\scripts\addons\CAD_8_1_5_1` |
| macOS | `~/Library/Application Support/Blender/<version>/scripts/addons/CAD_8_1_5_1` |
| Linux | `~/.config/blender/<version>/scripts/addons/CAD_8_1_5_1` |

Two consequences:

- **Updating overwrites in place.** Installing a newer zip replaces the same
  folder, so you do not accumulate old copies — but you also cannot have two
  versions installed side by side in one Blender.
- **The folder name is not the version.** Read the version from
  `Edit > Preferences > Add-ons`, or from the zip filename you installed. Do not
  read it from the folder.

## First start

Open the **Seamless** tab and press **Start Seamless CAD**.

This launches the geometry kernel — a separate executable that does the actual
CAD computation — and creates your first part. The first start takes a moment
because a process is starting up. Later sessions reuse it.

Blender and the kernel talk over a **local TCP socket on `127.0.0.1`, port
8080**. Nothing leaves your machine. If your firewall asks, you can safely deny
it access to public networks; only the loopback connection matters.

> **Port 8080 is fixed and there is no setting for it.** If another program is
> already listening on 8080 — a web dev server is the usual culprit — the add-on
> assumes it is a leftover kernel from a previous session and tries to use it.
> CAD operations then fail with no obvious cause. It logs one line about this,
> so if nothing computes, check whether 8080 is taken, free it, and re-enable
> the add-on.

The kernel is told Blender's process ID and shuts itself down if Blender
disappears, so a crash does not normally leave the port occupied.

## Updating

1. Install the new zip the same way as above
2. Restart Blender

Restarting matters more than it does for pure-Python add-ons: the old kernel
process and the loaded native libraries are not swapped out by re-enabling the
add-on alone.

Files you have already saved keep working — the Feature Tree is stored in the
`.blend` file, not in the add-on.

## Uninstalling

In `Edit > Preferences > Add-ons`, expand Seamless CAD and use **Remove**.

A `.blend` file saved with CAD parts still opens afterwards; the proxies and
collections remain as ordinary Blender objects, but nothing recomputes and the
**Seamless** tab is gone. Anything you want to keep independently of the add-on
should be [baked or exported](import-export.md) first.

## If the tab does not appear

**No Seamless tab in the sidebar.**
The add-on is installed but not enabled, or Blender is older than 4.2. Check the
checkbox in `Edit > Preferences > Add-ons`.

**The tab is there but empty below the workspace panel.**
That is normal before a part exists. Press **Start Seamless CAD**, or pick a
part from the **Active CAD Workspace** dropdown.

**The tab is there and nothing ever computes.**
The kernel is not running. `Edit > Preferences > Add-ons`, expand Seamless CAD,
and look at **CAD Engine: Running / Not running** — that reads the real process
state. See [Troubleshooting](troubleshooting.md).

## See also

- [Quick Start](quickstart.md)
- [Testing builds for macOS and Linux](testing-builds.md)
- [Troubleshooting](troubleshooting.md)
