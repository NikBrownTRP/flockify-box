#!/usr/bin/env python3
"""
Raspberry Pi 5 Button Controller Library
Reusable button handler with short press and hold detection
"""

import gpiod
from gpiod.line import Bias, Value
import time
import threading

CHIP_PATH = "/dev/gpiochip4"  # GPIO chip on Raspberry Pi 5
POLL_INTERVAL = 0.01  # 10ms polling interval
DEBOUNCE_TIME = 0.05  # 50ms debounce time


class ButtonHandler:
    """Handles a single button with press and hold detection"""
    
    def __init__(self, gpio_pin, hold_time=2.0, short_press_callback=None, hold_callback=None):
        """
        Initialize button handler
        
        Args:
            gpio_pin: GPIO pin number (BCM numbering)
            hold_time: Time in seconds to detect a hold (default: 2.0)
            short_press_callback: Function to call on short press
            hold_callback: Function to call on hold
        """
        self.gpio_pin = gpio_pin
        self.hold_time = hold_time
        self.short_press_callback = short_press_callback
        self.hold_callback = hold_callback
        
        self.button_press_time = None
        self.hold_detected = False
        self.hold_timer = None
        self.running = False
        self.thread = None
        self.request = None
        self.button_is_pressed = False  # Track current button state
        self.lock = threading.Lock()  # Thread safety lock
        self.last_change_time = 0  # For debouncing
    
    def _on_hold(self):
        """Internal callback when hold is detected"""
        with self.lock:
            if self.button_is_pressed and self.button_press_time is not None:
                self.hold_detected = True
                if self.hold_callback:
                    self.hold_callback(self.gpio_pin)
    
    def _start_hold_timer(self):
        """Starts timer to detect button hold"""
        self.hold_timer = threading.Timer(self.hold_time, self._on_hold)
        self.hold_timer.daemon = True
        self.hold_timer.start()
    
    def _cancel_hold_timer(self):
        """Cancels the hold timer"""
        if self.hold_timer:
            self.hold_timer.cancel()
            self.hold_timer = None
    
    def _monitor_button(self):
        """Main monitoring loop"""
        # Read initial state and set our tracking flag
        last_value = self.request.get_value(self.gpio_pin)
        self.button_is_pressed = (last_value == Value.ACTIVE)
        
        while self.running:
            current_value = self.request.get_value(self.gpio_pin)
            
            if current_value != last_value:
                # Debounce: ignore changes that happen too quickly
                current_time = time.time()
                if current_time - self.last_change_time < DEBOUNCE_TIME:
                    time.sleep(POLL_INTERVAL)
                    continue
                
                self.last_change_time = current_time
                
                # Button pressed (INACTIVE to ACTIVE)
                if current_value == Value.ACTIVE:
                    with self.lock:
                        self.button_is_pressed = True
                        self.button_press_time = time.time()
                        self.hold_detected = False
                        self._start_hold_timer()
                
                # Button released (ACTIVE to INACTIVE)
                elif current_value == Value.INACTIVE:
                    with self.lock:
                        self.button_is_pressed = False
                        self._cancel_hold_timer()
                        
                        if self.button_press_time and not self.hold_detected:
                            # Short press
                            if self.short_press_callback:
                                self.short_press_callback(self.gpio_pin)
                        
                        self.button_press_time = None
                        self.hold_detected = False
                
                last_value = current_value
            
            time.sleep(POLL_INTERVAL)
    
    def start(self):
        """Start monitoring the button"""
        if self.running:
            return
        
        # Request GPIO line
        self.request = gpiod.request_lines(
            CHIP_PATH,
            consumer=f"button_gpio{self.gpio_pin}",
            config={
                self.gpio_pin: gpiod.LineSettings(
                    direction=gpiod.line.Direction.INPUT,
                    bias=Bias.PULL_UP,
                    active_low=True  # Invert the logic
                )
            }
        )
        
        self.running = True
        self.thread = threading.Thread(target=self._monitor_button)
        self.thread.daemon = True
        self.thread.start()
    
    def stop(self):
        """Stop monitoring the button"""
        self.running = False
        self._cancel_hold_timer()
        if self.thread:
            self.thread.join(timeout=1.0)
        if self.request:
            self.request.release()
            self.request = None


# Example callback functions
def on_button_short_press(gpio_pin):
    """Called when button is pressed briefly"""
    print(f"GPIO {gpio_pin}: Short press detected!")
    print(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")

def on_button_hold(gpio_pin):
    """Called when button is held down"""
    print(f"GPIO {gpio_pin}: Button HOLD detected!")
    print(f"Timestamp: {time.strftime('%Y-%m-%d %H:%M:%S')}")


# Example usage
if __name__ == "__main__":
    print("Button Controller - Multiple Buttons Example")
    print("Press Ctrl+C to exit\n")
    
    # Create button handlers for multiple GPIO pins
    button1 = ButtonHandler(
        gpio_pin=17,
        hold_time=2.0,
        short_press_callback=on_button_short_press,
        hold_callback=on_button_hold
    )
    
    button2 = ButtonHandler(
        gpio_pin=27,
        hold_time=2.0,
        short_press_callback=on_button_short_press,
        hold_callback=on_button_hold
    )
    
    # Start monitoring all buttons
    button1.start()
    button2.start()
    
    print(f"Monitoring GPIO 17 and GPIO 27")
    print(f"Hold time: 2.0 seconds\n")
    
    try:
        # Keep the main thread running
        while True:
            time.sleep(0.1)
    except KeyboardInterrupt:
        print("\nCleaning up and exiting...")
    finally:
        button1.stop()
        button2.stop()
