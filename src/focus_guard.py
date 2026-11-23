"""Focus guard: detect when Meet overlay/PiP or attached docs distract from a Meet call."""

import re

BROWSERS = ("Google Chrome", "Safari", "Arc", "Firefox", "Microsoft Edge", "Brave Browser")
OWN_APPS = ("Vince", "Python")
DOC_TITLE = re.compile(r"Google (Docs|Sheets|Slides)|Fogli Google|Documenti Google|Presentazioni Google", re.I)
MEET_TITLE = re.compile(r"^\W*Meet\b|meet\.google\.com", re.I)


def has_meet(event):
    urls = list(event.get("urls") or []) + [event.get("url") or ""]
    return any("meet.google.com" in u for u in urls)


def has_screen_access():
    """Screen Recording granted? Never prompts."""
    try:
        import Quartz
    except ImportError:
        return False
    preflight = getattr(Quartz, "CGPreflightScreenCaptureAccess", None)
    return bool(preflight()) if preflight else False


def snapshot():
    """Return (windows, frontmost_owner, has_titles, screen_size). Front-to-back windows.

    No permission prompt: titles are only present if Screen Recording is already granted.
    """
    try:
        import AppKit
        import Quartz
    except ImportError:
        return [], "", False, (0, 0)
    info = Quartz.CGWindowListCopyWindowInfo(
        Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
        Quartz.kCGNullWindowID,
    ) or []
    windows = []
    for w in info:
        b = w.get("kCGWindowBounds") or {}
        windows.append(
            {
                "owner": w.get("kCGWindowOwnerName") or "",
                "title": w.get("kCGWindowName") or "",
                "layer": int(w.get("kCGWindowLayer", 0)),
                "w": b.get("Width", 0),
                "h": b.get("Height", 0),
            }
        )
    app = AppKit.NSWorkspace.sharedWorkspace().frontmostApplication()
    front = str(app.localizedName()) if app else ""
    has_titles = has_screen_access()
    screen = AppKit.NSScreen.mainScreen().frame().size if AppKit.NSScreen.mainScreen() else None
    size = (screen.width, screen.height) if screen else (0, 0)
    return windows, front, has_titles, size


def is_distracted(windows, frontmost, has_titles, screen, event, app_meet=""):
    """True if, during a Meet event, the frontmost app is neither Meet nor an attached doc."""
    if not has_meet(event) or not frontmost or frontmost in OWN_APPS:
        return False
    meet_app = (app_meet or "").rstrip("/").rsplit("/", 1)[-1].removesuffix(".app")
    if frontmost == meet_app:
        return False
    if frontmost not in BROWSERS:
        return True
    # shortcut: without titles we can't tell which tab, so a browser is never flagged
    if not has_titles:
        return False
    front = next((w for w in windows if w["owner"] == frontmost and w["layer"] == 0 and w["title"]), None)
    if not front:
        return False
    title = front["title"]
    attachments = [a.lower() for a in event.get("attachments") or [] if a]
    ok = MEET_TITLE.search(title) or DOC_TITLE.search(title) or any(a in title.lower() for a in attachments)
    return not ok


