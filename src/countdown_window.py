import AppKit
import time
from datetime import datetime, timedelta
from Foundation import NSMakeRect, NSMakePoint
import pytz

import logging


class CountdownWindowDelegate(AppKit.NSObject):
    def windowWillClose_(self, notification):
        window = notification.object()
        if hasattr(window, "owner"):
            window.owner.handle_window_closed()


class CountdownWindow:
    def __init__(self, event, parent=None):
        self.parent = parent
        self.event = event
        # Create window delegate
        self.delegate = CountdownWindowDelegate.alloc().init()

        self.window = AppKit.NSWindow.alloc()
        screen = AppKit.NSScreen.mainScreen()
        screen_frame = screen.frame()
        window_width = 200.0
        window_height = 50.0
        frame = (
            (
                screen_frame.size.width / 2 - window_width / 2,
                screen_frame.size.height - window_height,
            ),
            (window_width, window_height),
        )
        self.window.initWithContentRect_styleMask_backing_defer_(
            frame,
            AppKit.NSWindowStyleMaskBorderless,  # Remove title bar
            AppKit.NSBackingStoreBuffered,
            False,
        )
        # Make window movable by dragging anywhere
        self.window.setMovableByWindowBackground_(True)

        self.parent = parent

        # Set window properties for transparency and rounded corners
        self.window.setBackgroundColor_(AppKit.NSColor.clearColor())
        self.window.setOpaque_(False)

        # Create a visual effect view for the background
        visual_effect = AppKit.NSVisualEffectView.alloc().initWithFrame_(
            self.window.contentView().bounds()
        )
        visual_effect.setAutoresizingMask_(
            AppKit.NSViewWidthSizable | AppKit.NSViewHeightSizable
        )
        visual_effect.setWantsLayer_(True)
        visual_effect.layer().setCornerRadius_(10.0)  # Set corner radius
        visual_effect.layer().setMasksToBounds_(True)

        # Set the visual effect to be light and transparent
        visual_effect.setMaterial_(AppKit.NSVisualEffectMaterialLight)
        visual_effect.setBlendingMode_(AppKit.NSVisualEffectBlendingModeWithinWindow)
        visual_effect.setState_(AppKit.NSVisualEffectStateActive)

        # Replace the content view with our visual effect view
        self.window.contentView().addSubview_(visual_effect)
        self.visual_effect = visual_effect

        # Create and configure the countdown label
        content_view = self.visual_effect
        # Make the label height bigger to accommodate the font size
        label_height = 30
        label_width = window_width - 40  # Leave space for close button
        self.label = AppKit.NSTextField.alloc().initWithFrame_(
            NSMakeRect(
                10, (window_height - label_height) / 2, label_width, label_height
            )
        )
        self.label.setBezeled_(False)
        self.label.setDrawsBackground_(False)
        self.label.setEditable_(False)
        self.label.setSelectable_(False)
        self.label.setAlignment_(AppKit.NSTextAlignmentCenter)
        self.label.setFont_(AppKit.NSFont.boldSystemFontOfSize_(24))
        self.label.setTextColor_(AppKit.NSColor.blackColor())
        content_view.addSubview_(self.label)

        # Create and configure the event name label
        event_name_label_height = 20
        event_name_label = AppKit.NSTextField.alloc().initWithFrame_(
            NSMakeRect(10, -5, label_width, event_name_label_height)
        )
        event_name_label.setBezeled_(False)
        event_name_label.setDrawsBackground_(False)
        event_name_label.setEditable_(False)
        event_name_label.setSelectable_(False)
        event_name_label.setAlignment_(AppKit.NSTextAlignmentCenter)
        event_name_label.setFont_(AppKit.NSFont.systemFontOfSize_(10))
        event_name_label.setTextColor_(AppKit.NSColor.blackColor())
        event_name_label.setStringValue_(self.event["summary"])
        content_view.addSubview_(event_name_label)

        # Add close button
        button_size = 20
        close_button = AppKit.NSButton.alloc().initWithFrame_(
            NSMakeRect(
                window_width - button_size - 10,
                (window_height - button_size) / 2,
                button_size,
                button_size,
            )
        )
        close_button.setBezelStyle_(AppKit.NSBezelStyleCircular)
        close_button.setTitle_("×")
        # close_button.setFontColor_(AppKit.NSColor.blackColor())
        close_button.setTarget_(self)
        close_button.setAction_("close")
        attributes = {
            AppKit.NSForegroundColorAttributeName: AppKit.NSColor.blackColor(),
            AppKit.NSFontAttributeName: AppKit.NSFont.boldSystemFontOfSize_(16),
        }
        attributed_title = AppKit.NSAttributedString.alloc().initWithString_attributes_(
            "×", attributes
        )

        # Apply the styled title
        close_button.setAttributedTitle_(attributed_title)

        content_view.addSubview_(close_button)

        # Set initial background color (yellow)
        initial_color = AppKit.NSColor.colorWithRed_green_blue_alpha_(
            0.0, 0.0, 0.0, 0.95
        )  # Bright yellow
        self.visual_effect.layer().setBackgroundColor_(initial_color.CGColor())

        self.window.makeKeyAndOrderFront_(None)
        self.window.setLevel_(AppKit.NSFloatingWindowLevel)
        self.timer = None

    def start_countdown(self):
        self.timer = AppKit.NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
            1.0,
            self,
            "timerCallback:",
            {
                "end_time": self.event["end"],
                "start_time": self.event["start"],
            },
            True,
        )
        AppKit.NSRunLoop.currentRunLoop().addTimer_forMode_(
            self.timer, AppKit.NSRunLoopCommonModes
        )

    def timerCallback_(self, timer):
        start_time = timer.userInfo()["start_time"]
        end_time = timer.userInfo()["end_time"]
        time_to_use = start_time if start_time > datetime.now(pytz.utc) else end_time
        sign = None
        if time_to_use == start_time:
            sign = "+"
        now = datetime.now(pytz.utc)
        time_diff = time_to_use - now

        logging.debug(
            f"Time diff: {time_diff}, sign: {sign} time_to_use: {time_to_use}, now: {now}"
        )

        total_seconds = int(time_diff.total_seconds())
        minutes = abs(total_seconds) // 60
        seconds = abs(total_seconds) % 60

        # Update background color based on time
        if sign == "+":
            color = AppKit.NSColor.colorWithRed_green_blue_alpha_(
                155 / 255, 89 / 255, 182 / 255, 0.95
            )  # purple
        elif total_seconds < 0:
            # Red for expired
            color = AppKit.NSColor.colorWithRed_green_blue_alpha_(
                231 / 255, 76 / 255, 60 / 255, 1.0
            )  # Bright red
        elif total_seconds <= 300 and total_seconds > 60:  # Between 1 and 5 minutes
            color = AppKit.NSColor.colorWithRed_green_blue_alpha_(
                241 / 255, 196 / 255, 15 / 255, 1.0
            )  # Yellow
        elif total_seconds <= 60 and total_seconds > 0:  # Less than 1 minute
            color = AppKit.NSColor.colorWithRed_green_blue_alpha_(
                230 / 255, 126 / 255, 34 / 255, 1.0
            )  # Orange
        else:  # More than 5 minutes
            color = AppKit.NSColor.colorWithRed_green_blue_alpha_(
                46 / 255, 204 / 255, 113 / 255, 1.0
            )  # Green

        if not sign:
            sign = "-" if total_seconds < 0 else ""
        countdown_text = f"{sign}{minutes:01d}:{seconds:02d}"
        self.label.setStringValue_(countdown_text)

        self.visual_effect.layer().setBackgroundColor_(color.CGColor())

    def show(self):
        # Show the window
        self.window.makeKeyAndOrderFront_(self.window)

    def close(self):
        if self.timer:
            self.timer.invalidate()
            self.timer = None
        if self.window:
            self.window.close()
            self.window = None
        if self.parent and self.event and "id" in self.event:
            if self.event["id"] in self.parent.countdown_windows:
                self.parent.countdown_windows[self.event["id"]]["closed"] = True
