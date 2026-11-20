"""Focus guard: detect when Meet overlay/PiP or attached docs distract from a Meet call."""

import re

BROWSERS = ("Google Chrome", "Safari", "Arc", "Firefox", "Microsoft Edge", "Brave Browser")
OWN_APPS = ("Vince", "Python")
DOC_TITLE = re.compile(r"Google (Docs|Sheets|Slides)", re.I)
# shortcut: coarse PiP size guess without window titles, tune if false positives
PIP_MAX_W, PIP_MAX_H = 640, 400


def has_meet(event):
    urls = list(event.get("urls") or []) + [event.get("url") or ""]
    return any("meet.google.com" in u for u in urls)


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
    preflight = getattr(Quartz, "CGPreflightScreenCaptureAccess", None)
    has_titles = bool(preflight()) if preflight else False
    screen = AppKit.NSScreen.mainScreen().frame().size if AppKit.NSScreen.mainScreen() else None
    size = (screen.width, screen.height) if screen else (0, 0)
    return windows, front, has_titles, size


def is_distracted(windows, frontmost, has_titles, screen, event, app_meet=""):
    """True if, during a Meet event, Meet floats over work or an attached doc is frontmost."""
    if not has_meet(event):
        return False
    meet_app = (app_meet or "").rstrip("/").rsplit("/", 1)[-1].removesuffix(".app")
    others = [w for w in windows if w["owner"] not in OWN_APPS]
    for w in others:
        if w["layer"] <= 0 and not (meet_app and w["owner"] == meet_app and _covers(w, screen)):
            continue
        if has_titles:
            t = w["title"].lower()
            if "meet" in t or "picture in picture" in t or "picture-in-picture" in t:
                return True
        elif (w["owner"] in BROWSERS or w["owner"] == meet_app) and 0 < w["w"] <= PIP_MAX_W and 0 < w["h"] <= PIP_MAX_H:
            return True
        elif meet_app and w["owner"] == meet_app and _covers(w, screen) and frontmost != meet_app:
            return True
    if has_titles:
        attachments = [a.lower() for a in event.get("attachments") or [] if a]
        front = next((w for w in others if w["owner"] == frontmost and w["layer"] == 0 and w["title"]), None)
        if front:
            t = front["title"].lower()
            if DOC_TITLE.search(front["title"]) or any(a in t for a in attachments):
                return True
    return False


def _covers(w, screen):
    return screen[0] > 0 and w["w"] >= 0.9 * screen[0] and w["h"] >= 0.9 * screen[1]
