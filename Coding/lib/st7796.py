from machine import Pin
from time import sleep_ms
import framebuf

class ST7796(framebuf.FrameBuffer):
    def __init__(self, spi, cs, dc, rst, width=480, height=320):
        self.width, self.height = width, height
        self.spi, self.cs, self.dc, self.rst = spi, cs, dc, rst
        self.cs.init(self.cs.OUT, value=1)
        self.dc.init(self.dc.OUT, value=1)
        self.rst.init(self.rst.OUT, value=1)
        self.buffer = bytearray(width * height * 2)
        super().__init__(self.buffer, width, height, framebuf.RGB565)
        self._init_display()

    def _cmd(self, c):
        self.cs(1); self.dc(0); self.cs(0)
        self.spi.write(bytearray([c])); self.cs(1)

    def _data(self, d):
        self.cs(1); self.dc(1); self.cs(0)
        self.spi.write(bytearray([d]) if isinstance(d, int) else d)
        self.cs(1)

    def _init_display(self):
        self.rst(0); sleep_ms(50); self.rst(1); sleep_ms(150)

        self._cmd(0x01)              # Software reset
        sleep_ms(120)
        self._cmd(0x11)              # Sleep exit
        sleep_ms(120)

        self._cmd(0xF0); self._data(0xC3)   # Command set unlock, part 1
        self._cmd(0xF0); self._data(0x96)   # Command set unlock, part 2

        self._cmd(0x36); self._data(0x28)   # MADCTL: landscape + BGR
        self._cmd(0x3A); self._data(0x55)   # 16-bit color

        self._cmd(0xB4); self._data(0x01)   # Column inversion

        self._cmd(0xB6)
        for d in [0x80, 0x02, 0x3B]:
            self._data(d)

        self._cmd(0xE8)
        for d in [0x40, 0x8A, 0x00, 0x00, 0x29, 0x19, 0xA5, 0x33]:
            self._data(d)

        self._cmd(0xC1); self._data(0x06)
        self._cmd(0xC2); self._data(0xA7)
        self._cmd(0xC5); self._data(0x18)
        sleep_ms(120)

        self._cmd(0xE0)
        for d in [0xF0,0x09,0x0B,0x06,0x04,0x15,0x2F,0x54,0x42,0x3C,0x17,0x14,0x18,0x1B]:
            self._data(d)
        self._cmd(0xE1)
        for d in [0xE0,0x09,0x0B,0x06,0x04,0x03,0x2B,0x43,0x42,0x3B,0x16,0x14,0x17,0x1B]:
            self._data(d)
        sleep_ms(120)

        self._cmd(0xF0); self._data(0x3C)   # Command set lock, part 1
        self._cmd(0xF0); self._data(0x69)   # Command set lock, part 2
        sleep_ms(120)

        self._cmd(0x29)              # Display on
        self._cmd(0x21)              # Display inversion ON — corrects color mapping

    def show(self):
        self._cmd(0x2A); self._data(bytearray([0x00,0x00,0x01,0xDF]))
        self._cmd(0x2B); self._data(bytearray([0x00,0x00,0x01,0x3F]))
        self._cmd(0x2C)
        self.cs(1); self.dc(1); self.cs(0)

        chunk_size = 4096
        total = len(self.buffer)
        tmp = bytearray(chunk_size)
        offset = 0
        while offset < total:
            n = min(chunk_size, total - offset)
            for i in range(0, n, 2):
                tmp[i] = self.buffer[offset + i + 1]
                tmp[i + 1] = self.buffer[offset + i]
            self.spi.write(memoryview(tmp)[:n])
            offset += n

        self.cs(1)