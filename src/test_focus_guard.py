from focus_guard import is_distracted

SCREEN = (1440, 900)
MEET = {"url": "https://meet.google.com/abc", "urls": [], "attachments": ["Q4 plan"]}
NO_MEET = {"url": "", "urls": [], "attachments": []}


def win(owner, title="", layer=0, w=800, h=600):
    return {"owner": owner, "title": title, "layer": layer, "w": w, "h": h}


def test_no_meet_event():
    ws = [win("Google Chrome", "Meet", layer=3, w=300, h=200)]
    assert not is_distracted(ws, "Google Chrome", True, SCREEN, NO_MEET)


def test_pip_with_titles():
    ws = [win("Google Chrome", "Meet - abc", layer=3, w=300, h=200)]
    assert is_distracted(ws, "Slack", True, SCREEN, MEET)


def test_pip_without_titles_size_guess():
    ws = [win("Google Chrome", "", layer=3, w=300, h=200)]
    assert is_distracted(ws, "Slack", False, SCREEN, MEET)


def test_docs_frontmost():
    ws = [win("Google Chrome", "Budget - Google Sheets")]
    assert is_distracted(ws, "Google Chrome", True, SCREEN, MEET)


def test_attachment_title_frontmost():
    ws = [win("Google Chrome", "Q4 plan v2")]
    assert is_distracted(ws, "Google Chrome", True, SCREEN, MEET)


def test_docs_without_titles_ignored():
    ws = [win("Google Chrome", "")]
    assert not is_distracted(ws, "Google Chrome", False, SCREEN, MEET)


def test_own_windows_ignored():
    ws = [win("Vince", "Meet", layer=3, w=200, h=50)]
    assert not is_distracted(ws, "Vince", True, SCREEN, MEET)


def test_normal_meet_window_ok():
    ws = [win("Google Chrome", "Meet - abc", layer=0)]
    assert not is_distracted(ws, "Google Chrome", True, SCREEN, MEET)
