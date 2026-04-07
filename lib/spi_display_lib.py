#!/usr/bin/env python3
"""
SPI Display Library for 1.83" 240x280 display on Raspberry Pi 5
Production-ready library without test cases
"""

import spidev
import lgpio
import time
from PIL import Image
import numpy as np

class SPIDisplay:
    """Display driver for 1.83 inch SPI display (240x280) with ST7789 controller"""
    
    def __init__(self, width=240, height=280, dc_pin=25, rst_pin=27, bl_pin=18, 
                 spi_bus=0, spi_device=0, spi_speed=10000000):
        """
        Initialize display
        
        Args:
            width: Display width in pixels (default: 240)
            height: Display height in pixels (default: 280)
            dc_pin: Data/Command GPIO pin (default: 25)
            rst_pin: Reset GPIO pin (default: 27)
            bl_pin: Backlight GPIO pin (default: 18)
            spi_bus: SPI bus number (default: 0)
            spi_device: SPI device number (default: 0)
            spi_speed: SPI clock speed in Hz (default: 10000000)
        """
        self.width = width
        self.height = height
        self.dc_pin = dc_pin
        self.rst_pin = rst_pin
        self.bl_pin = bl_pin

        # Open GPIO chip exposing the 40-pin header.
        # On current Raspberry Pi OS (Bookworm/Trixie) kernels, the RP1 chip
        # is labelled "pinctrl-rp1" at /dev/gpiochip0 (verified with gpiodetect).
        self.gpio_chip = lgpio.gpiochip_open(0)
        
        # Setup GPIO pins as outputs
        lgpio.gpio_claim_output(self.gpio_chip, self.dc_pin)
        lgpio.gpio_claim_output(self.gpio_chip, self.rst_pin)
        lgpio.gpio_claim_output(self.gpio_chip, self.bl_pin)
        
        # Setup PWM for backlight (1kHz frequency - more compatible)
        self.pwm_freq = 1000
        self.pwm_duty = 100  # Start at 100%
        lgpio.tx_pwm(self.gpio_chip, self.bl_pin, self.pwm_freq, self.pwm_duty)
        
        # Setup SPI
        self.spi = spidev.SpiDev()
        self.spi.open(spi_bus, spi_device)
        self.spi.max_speed_hz = spi_speed
        self.spi.mode = 0
    
    def reset(self):
        """Hardware reset the display"""
        lgpio.gpio_write(self.gpio_chip, self.rst_pin, 1)
        time.sleep(0.01)
        lgpio.gpio_write(self.gpio_chip, self.rst_pin, 0)
        time.sleep(0.01)
        lgpio.gpio_write(self.gpio_chip, self.rst_pin, 1)
        time.sleep(0.12)
    
    def write_cmd(self, cmd):
        """Write command to display"""
        lgpio.gpio_write(self.gpio_chip, self.dc_pin, 0)
        self.spi.writebytes([cmd])
    
    def write_data(self, data):
        """Write data to display"""
        lgpio.gpio_write(self.gpio_chip, self.dc_pin, 1)
        if isinstance(data, int):
            self.spi.writebytes([data])
        else:
            # Convert to list and ensure all values are Python ints
            data_list = [int(x) for x in data] if hasattr(data, '__iter__') else [data]
            self.spi.writebytes(data_list)
    
    def init(self):
        """Initialize ST7789 display controller"""
        self.reset()
        
        # Sleep out
        self.write_cmd(0x11)
        time.sleep(0.12)
        
        # Memory Data Access Control - orientation setting
        self.write_cmd(0x36)
        self.write_data(0x00)
        
        # Interface Pixel Format - 16bit color (RGB565)
        self.write_cmd(0x3A)
        self.write_data(0x05)
        
        # Porch Setting
        self.write_cmd(0xB2)
        self.write_data([0x0C, 0x0C, 0x00, 0x33, 0x33])
        
        # Gate Control
        self.write_cmd(0xB7)
        self.write_data(0x35)
        
        # VCOM Setting
        self.write_cmd(0xBB)
        self.write_data(0x19)
        
        # LCM Control
        self.write_cmd(0xC0)
        self.write_data(0x2C)
        
        # VDV and VRH Command Enable
        self.write_cmd(0xC2)
        self.write_data(0x01)
        
        # VRH Set
        self.write_cmd(0xC3)
        self.write_data(0x12)
        
        # VDV Set
        self.write_cmd(0xC4)
        self.write_data(0x20)
        
        # Frame Rate Control in Normal Mode
        self.write_cmd(0xC6)
        self.write_data(0x0F)
        
        # Power Control 1
        self.write_cmd(0xD0)
        self.write_data([0xA4, 0xA1])
        
        # Positive Voltage Gamma Control
        self.write_cmd(0xE0)
        self.write_data([0xD0, 0x04, 0x0D, 0x11, 0x13, 0x2B, 0x3F, 0x54,
                        0x4C, 0x18, 0x0D, 0x0B, 0x1F, 0x23])
        
        # Negative Voltage Gamma Control
        self.write_cmd(0xE1)
        self.write_data([0xD0, 0x04, 0x0C, 0x11, 0x13, 0x2C, 0x3F, 0x44,
                        0x51, 0x2F, 0x1F, 0x1F, 0x20, 0x23])
        
        # Display Inversion On
        self.write_cmd(0x21)
        
        # Display On
        self.write_cmd(0x29)
        time.sleep(0.02)
    
    def set_window(self, x0, y0, x1, y1):
        """
        Set active drawing window
        
        Args:
            x0: Start column
            y0: Start row
            x1: End column
            y1: End row
        """
        # Apply offsets for proper alignment
        x_offset = 0
        y_offset = 5  # Shift image down by 5 pixels for this panel
        
        x0 += x_offset
        x1 += x_offset
        y0 += y_offset
        y1 += y_offset
        
        # Column Address Set
        self.write_cmd(0x2A)
        self.write_data([x0 >> 8, x0 & 0xFF, x1 >> 8, x1 & 0xFF])
        
        # Row Address Set
        self.write_cmd(0x2B)
        self.write_data([y0 >> 8, y0 & 0xFF, y1 >> 8, y1 & 0xFF])
        
        # Memory Write
        self.write_cmd(0x2C)
    
    def display_image(self, image):
        """
        Display a PIL Image on the screen
        
        Args:
            image: PIL Image object (will be resized if needed)
        """
        if image.size != (self.width, self.height):
            image = image.resize((self.width, self.height), Image.Resampling.LANCZOS)
        
        # Convert to RGB565
        rgb_image = image.convert('RGB')
        pixels = np.array(rgb_image)
        
        # Convert RGB888 to RGB565
        r = (pixels[:,:,0] >> 3).astype(np.uint16) << 11
        g = (pixels[:,:,1] >> 2).astype(np.uint16) << 5
        b = (pixels[:,:,2] >> 3).astype(np.uint16)
        rgb565 = r | g | b
        
        # Convert to bytes (big endian)
        data = []
        for row in rgb565:
            for pixel in row:
                data.append((pixel >> 8) & 0xFF)
                data.append(pixel & 0xFF)
        
        self.set_window(0, 0, self.width - 1, self.height - 1)
        
        # Send in chunks to avoid SPI buffer issues
        chunk_size = 4096
        for i in range(0, len(data), chunk_size):
            self.write_data(data[i:i+chunk_size])
    
    def clear(self, color=(0, 0, 0)):
        """
        Clear screen to specified color
        
        Args:
            color: RGB tuple (default: black)
        """
        img = Image.new('RGB', (self.width, self.height), color)
        self.display_image(img)
    
    def set_backlight(self, brightness):
        """
        Control backlight brightness using PWM
        
        Args:
            brightness: 0-100 (0 = off, 100 = full brightness)
        """
        brightness = max(0, min(100, brightness))  # Clamp to 0-100
        self.pwm_duty = brightness
        lgpio.tx_pwm(self.gpio_chip, self.bl_pin, self.pwm_freq, self.pwm_duty)
    
    def cleanup(self):
        """Clean up resources"""
        # Turn off PWM
        lgpio.tx_pwm(self.gpio_chip, self.bl_pin, self.pwm_freq, 0)
        self.spi.close()
        lgpio.gpiochip_close(self.gpio_chip)
    
    def __enter__(self):
        """Context manager entry"""
        self.init()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit"""
        self.cleanup()


# Example usage
if __name__ == "__main__":
    from PIL import ImageDraw
    
    # Using context manager (recommended)
    with SPIDisplay() as display:
        # Test different brightness levels
        for brightness in [100, 75, 50, 25, 10]:
            print(f"Setting brightness to {brightness}%")
            display.set_backlight(brightness)
            time.sleep(1)
        
        # Set to comfortable brightness
        display.set_backlight(80)
        
        # Clear to black
        display.clear((0, 0, 0))
        time.sleep(1)
        
        # Create and display image
        img = Image.new('RGB', (240, 280), (255, 255, 255))
        draw = ImageDraw.Draw(img)
        draw.rectangle([10, 10, 230, 270], outline=(255, 0, 0), width=5)
        draw.text((50, 120), "Hello Display!", fill=(0, 0, 255))
        display.display_image(img)
        time.sleep(3)
    
    # Or manual initialization
    # display = SPIDisplay()
    # display.init()
    # display.set_backlight(50)  # 50% brightness
    # display.clear((0, 0, 0))
    # display.cleanup()
