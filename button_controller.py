"""
Button controller for Flockify Box.
Maps physical GPIO buttons to state machine actions.
"""

from lib.rpi_button_script import ButtonHandler


# GPIO pin assignments (buttons connect GPIO to GND, internal pull-up, active low)
GPIO_VOLUME_UP = 5
GPIO_VOLUME_DOWN = 6
GPIO_NEXT_TRACK = 16
GPIO_PREV_TRACK = 26
GPIO_NEXT_MODE = 12

# Long-press threshold for buttons that have both short- and long-press
# actions. 700 ms feels responsive but won't trigger on a firm tap.
LONG_PRESS_SEC = 0.7


class ButtonController:
    """Manages physical button inputs and routes them to the state machine."""

    def __init__(self, state_machine):
        self.state_machine = state_machine

        self.buttons = [
            ButtonHandler(
                gpio_pin=GPIO_VOLUME_UP,
                short_press_callback=lambda pin: self.state_machine.volume_up(),
            ),
            ButtonHandler(
                gpio_pin=GPIO_VOLUME_DOWN,
                short_press_callback=lambda pin: self.state_machine.volume_down(),
            ),
            ButtonHandler(
                gpio_pin=GPIO_NEXT_TRACK,
                short_press_callback=lambda pin: self.state_machine.next_track(),
            ),
            # Prev track: short = soft prev (rewinds current track via
            # go-librespot /player/prev), long = hard prev (skips to the
            # actual previous track regardless of current playback position).
            ButtonHandler(
                gpio_pin=GPIO_PREV_TRACK,
                hold_time=LONG_PRESS_SEC,
                short_press_callback=lambda pin: self.state_machine.prev_track(),
                hold_callback=lambda pin: self.state_machine.prev_track_hard(),
            ),
            # Next mode: short = next playlist, long = previous playlist.
            ButtonHandler(
                gpio_pin=GPIO_NEXT_MODE,
                hold_time=LONG_PRESS_SEC,
                short_press_callback=lambda pin: self.state_machine.next_mode(),
                hold_callback=lambda pin: self.state_machine.prev_mode(),
            ),
        ]

    def start(self):
        """Start all button handlers."""
        for button in self.buttons:
            button.start()

    def stop(self):
        """Stop all button handlers."""
        for button in self.buttons:
            button.stop()
