from focus_guard import is_distracted

SCREEN = (1440, 900)
MEET = {"url": "https://meet.google.com/abc", "urls": [], "attachments": ["Q4 plan"]}
NO_MEET = {"url": "", "urls": [], "attachments": []}


def win(owner, title="", layer=0, w=800, h=600):
    return {"owner": owner, "title": title, "layer": layer, "w": w, "h": h}


def d(ws, front, titles=True, event=MEET, app_meet=""):
    return is_distracted(ws, front, titles, SCREEN, event, app_meet)


def test_no_meet_event():
    assert not d([], "iTerm2", event=NO_MEET)


def test_other_app_front():
    assert d([win("iTerm2", "zsh")], "iTerm2")


def test_meet_app_front_ok():
    assert not d([win("Google Meet", "abc")], "Google Meet", app_meet="/x/Google Meet.app")


def test_chrome_meet_tab_ok():
    assert not d([win("Google Chrome", "Meet - abc-defg")], "Google Chrome")


def test_chrome_docs_ok():
    assert not d([win("Google Chrome", "Budget - Google Sheets")], "Google Chrome")
    assert not d([win("Google Chrome", "Spese - Fogli Google")], "Google Chrome")


def test_chrome_attachment_ok():
    assert not d([win("Google Chrome", "Q4 plan v2")], "Google Chrome")


def test_chrome_other_site_distracted():
    assert d([win("Google Chrome", "Release 3.5.1 - GitHub")], "Google Chrome")


def test_meeting_title_not_meet():
    assert d([win("Google Chrome", "Meeting notes - Notion")], "Google Chrome")


def test_chrome_without_titles_not_flagged():
    assert not d([win("Google Chrome", "")], "Google Chrome", titles=False)


def test_own_app_ignored():
    assert not d([win("Vince", "Settings")], "Vince")
