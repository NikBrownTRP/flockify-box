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
            ButtonHandler(
                gpio_pin=GPIO_PREV_TRACK,
                short_press_callback=lambda pin: self.state_machine.prev_track(),
            ),
            ButtonHandler(
                gpio_pin=GPIO_NEXT_MODE,
                short_press_callback=lambda pin: self.state_machine.next_mode(),
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
