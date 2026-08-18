# Testing builds for macOS and Linux

Seamless CAD is sold for Windows. macOS and Linux builds now exist, and they are
being handed out to testers.

They are **not** a product. They are not on sale, they have no release date, and
nothing here is a commitment that a release will follow.

If you are willing to run software that may not work at all, and to write down
carefully what happened when it doesn't, they are yours to try.

## What exists

| | |
|---|---|
| Linux | x86-64 |
| macOS | Apple Silicon (arm64) |
| macOS Intel | no build |

The add-on itself is the same code as the Windows release, file for file. Only
the geometry kernel — the separate executable that does the actual CAD
computation — is rebuilt per platform.

## Requirements

**Both:** Blender 4.2 or newer. Development and testing happen on 5.1.

**Linux:** glibc 2.34 or newer, and a C++ runtime providing GLIBCXX_3.4.30. In
practice that means Ubuntu 22.04, Debian 12, RHEL 9, or anything newer. X11,
fontconfig and freetype come from your system — Blender needs them too, so if
Blender runs you have them.

**macOS:** Apple Silicon, macOS 11 or newer. An Intel Mac will not run this
build at all.

## What has been verified, and what has not

Being specific about this matters more than usual here.

**Verified automatically, on every build:**

- The kernel compiles from source against OpenCASCADE 8.0.1
- Every shared library it needs is bundled, and resolves without help from the
  build machine's environment
- The kernel starts and answers on its port

**Reported by testers, depth unknown:**

- Both builds run inside Blender. A small number of reports, macOS and Linux,
  all of them positive

That is the first signal from real hardware there has been, and it is the good
kind. Treat it as encouraging rather than conclusive: **what those testers
actually did in the session was not recorded**, so it does not tell us which
features work. It rules out the worst case — that these builds simply do not
start — and little more than that.

**Still never verified:**

- Creating or editing geometry, beyond whatever those sessions happened to touch
- Viewport drawing, including whether the Metal backend works on macOS at all
- STEP and SVG import/export
- Anything to do with stability over a session
- Whether the macOS quarantine step below was needed

So a tester's report is still genuinely new information, and the more precisely
it says what was done, the more it is worth.

**Do not use these builds for work you would be upset to lose.** Save often, and
keep anything that matters in a separate file.

## Getting a build

Builds are not published for download; they are sent individually. Ask through
the product page and one will be sent to you.

## Installing

Same as the Windows version:

1. In Blender, open `Edit > Preferences > Add-ons > Install...`
2. Select the `.zip` you were sent
3. Enable the add-on
4. Press <kbd>N</kbd> in the 3D viewport. A **Seamless** tab appears.

Then follow the [Quick Start](quickstart.md).

### macOS: if nothing happens when you start a session

The kernel is signed, but only ad-hoc — it has not been through Apple's
notarisation, because that requires a paid Apple Developer membership that is
not funded yet. macOS may refuse to run it.

It may well work anyway: Blender extracts the zip itself, and files unpacked
that way do not normally inherit the quarantine flag that triggers the check.
Testers have reported macOS builds running, so it does appear to survive
Gatekeeper at least sometimes — but nobody has said whether they had to run the
command below first, so this is still open.

If the add-on loads but no geometry ever appears, clear the flag by hand:

```bash
xattr -dr com.apple.quarantine ~/Library/Application\ Support/Blender/*/scripts/addons/CAD_8_1_5_1
```

Then restart Blender. **Please report which of the two happened** — whether you
needed this command or not. It is one of the things we cannot determine from
here.

## Reporting

Careful reports are worth far more than many reports. What helps most:

- **What you did**, step by step, precisely enough that someone else could
  repeat it. "Added a box, set width to 30, added a cylinder, set it to
  subtract" beats "boolean is broken"
- **What happened**, and what you expected instead
- **Whether it happens again** from a fresh Blender file
- **Your setup**: OS and version, CPU (Apple Silicon or which distro), Blender
  version, and the add-on version from the zip filename

Two things make a report much easier to act on:

**The kernel log.** The geometry kernel writes to your temporary directory:

- Linux: `/tmp/seamless_cad_server_debug.log`
- macOS: `$TMPDIR/seamless_cad_server_debug.log`

**Blender's console output.** Start Blender from a terminal and the add-on's
messages appear there. On macOS that is
`/Applications/Blender.app/Contents/MacOS/Blender`.

If Blender crashes outright, say what you were doing at the moment it went. Even
"I don't know, I was dragging something" is useful — it narrows things down more
than nothing does.

Reports that the build simply does not start are just as valuable as reports
about modelling. And now that a few people have said "it runs", the useful
reports are the specific ones: which tools you used, and what they did.
