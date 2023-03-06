import usb_midi
import adafruit_ssd1306
import adafruit_bus_device
import adafruit_register
from adafruit_debouncer import Debouncer
import digitalio

import board
import busio as io
import time
import keypad

import adafruit_midi

from adafruit_midi.midi_message import note_parser

from adafruit_midi.note_on import NoteOn
from adafruit_midi.note_off import NoteOff
from adafruit_midi.control_change import ControlChange
from adafruit_midi.pitch_bend import PitchBend

t1b1 = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def midi2str(midi):
    note = midi[0]
    return t1b1[note % 12] + str(int(note / 12) - 2)


def prepare_but(pin):
    p = digitalio.DigitalInOut(pin)
    p.direction = digitalio.Direction.INPUT
    p.pull = digitalio.Pull.UP
    return lambda: p.value


keyboard = keypad.KeyMatrix(row_pins=(board.GP6, board.GP7, board.GP8, board.GP9), column_pins=(
    board.GP10, board.GP11, board.GP12, board.GP13, board.GP14))

i2c = io.I2C(board.GP21, board.GP20)
oled = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c, addr=0x3C)

up = Debouncer(prepare_but(board.GP2))
down = Debouncer(prepare_but(board.GP3))

midi_channel = 1
print(usb_midi.ports)
midi = adafruit_midi.MIDI(
    midi_in=usb_midi.ports[0],
    midi_out=usb_midi.ports[1],
    out_channel=0,
    in_channel="ALL",
)

msg = midi.receive()

oled.fill(0)
oled.show()

tempo = 100
steps = 16
step = 0

track = 0
tracks = 4

last_step_time = 0
full_velocity = True

data = []

for i in range(tracks):
    data.append([])
    for j in range(steps):
        data[i].append((-1, 0))

print("Initialized...")
while True:
    msg = midi.receive()
    redraw = False
    current_time = time.monotonic()
    up.update()
    down.update()

    if isinstance(msg, NoteOn) and msg.velocity != 0:
        data[track][step] = (msg.note, 127 if full_velocity else msg.velocity)
        print(msg)
        redraw = True

    target_step_time = 60.0 / tempo

    if current_time - last_step_time > target_step_time:
        for t in data:
            n = t[step]

            if n[0] != -1:
                midi.send(NoteOff(n[0], n[1]))

        last_step_time = current_time
        redraw = True
        step += 1
        if step >= steps:
            step -= steps

        for t in data:
            n = t[step]

            if n[0] != -1:
                midi.send(NoteOn(n[0], n[1]))

    if up.fell:
        tempo += 1
    elif down.fell:
        tempo -= 1

    if up.fell or down.fell:
        redraw = True
        if tempo < 0:
            tempo = 0
        elif tempo > 240:
            tempo = 240

    while True:
        e = keyboard.events.get()
        if e == None:
            break

        if e.key_number < 12:
            print(midi2str((e.key_number, 127)))
        else:
            print(e.key_number - 11)

    if redraw:
        oled.fill(0)
        oled.text("BPM: {}".format(tempo), 0, 0, 1)
        oled.text("STP: {}/{}".format(step + 1, steps), 0, 10, 1)
        oled.text("TRK: {}/{}".format(track + 1, tracks), 0, 20, 1)
        if data[track][step][0] == -1:
            oled.text("Note: -", 0, 30, 1)
        else:
            oled.text("Note: {}".format(midi2str(data[track][step])), 0, 30, 1)
        oled.show()
