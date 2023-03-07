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
keymap = dict()
keymap[9] = 0
keymap[4] = 1
keymap[19] = 2
keymap[14] = 3
keymap[18] = 4
keymap[13] = 5
keymap[12] = 6
keymap[17] = 7
keymap[11] = 8
keymap[16] = 9
keymap[10] = 10
keymap[15] = 11
keymap[3] = 12
keymap[2] = 13
keymap[1] = 14
keymap[0] = 15
keymap[8] = 16
keymap[7] = 17
keymap[6] = 18
keymap[5] = 19


def midi2str(midi):
    note = midi[0]
    return t1b1[note % 12] + str(int(note / 12) - 2)


def prepare_but(pin):
    p = digitalio.DigitalInOut(pin)
    p.direction = digitalio.Direction.INPUT
    p.pull = digitalio.Pull.UP
    return lambda: p.value


keyboard = keypad.KeyMatrix(row_pins=(board.GP6, board.GP7, board.GP8, board.GP9), column_pins=(
    board.GP10, board.GP11, board.GP12, board.GP13, board.GP14), columns_to_anodes=False)

i2c = io.I2C(board.GP21, board.GP20)
oled = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c, addr=0x3C)
uart_midi = io.UART(board.GP4, board.GP5, baudrate=32250)

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
midi_hardware = adafruit_midi.MIDI(midi_out=uart_midi, out_channel=1)

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
recording = False
step_mode = False

data = []

for i in range(tracks):
    data.append([])
    for j in range(steps):
        data[i].append((-1, 0))


def reset_track(t):
    data[t].clear()
    for j in range(steps):
        data[t].append((-1, 0))


print("Initialized...")
while True:
    msg = midi.receive()
    redraw = False
    current_time = time.monotonic()
    up.update()
    down.update()

    if isinstance(msg, NoteOn) and msg.velocity != 0:
        print(msg)
        if recording:
            data[track][step] = (
                msg.note, 127 if full_velocity else msg.velocity)
            redraw = True

    target_step_time = 60.0 / tempo

    if not step_mode and current_time - last_step_time > target_step_time:
        for t in data:
            n = t[step]

            if n[0] != -1:
                n = NoteOff(n[0], n[1])
                midi.send(n)
                midi_hardware.send(n)

        last_step_time = current_time
        redraw = True
        step += 1
        if step >= steps:
            step -= steps

        for t in data:
            n = t[step]

            if n[0] != -1:
                n = NoteOn(n[0], n[1])
                midi.send(n)
                midi_hardware.send(n)

    if up.fell:
        tempo += 1
    elif down.fell:
        tempo -= 1

    while True:
        e = keyboard.events.get()
        if e == None:
            break

        key = keymap[e.key_number]

        if key < 12:
            if e.pressed:
                n = NoteOn(key + 60, 127)
                midi.send(n)
                midi_hardware.send(n)

                if recording:
                    data[track][step] = (key + 60, 127)
                    redraw = True
            else:
                n = NoteOff(key + 60, 0)
                midi.send(n)
                midi_hardware.send(n)
        elif e.pressed:
            print(key - 11)
            redraw = True

            if key == 12:
                if not step_mode:
                    recording = not recording
                else:
                    step_mode = False
                    last_step_time = current_time
            if key == 16:
                reset_track(track)
            if key == 13:
                if not step_mode:
                    step_mode = True
                else:
                    step += 1
                    if step >= steps:
                        step -= steps
            if key == 15:
                if not recording:
                    tempo += 1
                else:
                    track += 1
            if key == 19:
                if not recording:
                    tempo -= 1
                else:
                    track -= 1

            if key == 15 or key == 19:
                if not recording:
                    if tempo < 0:
                        tempo = 0
                    elif tempo > 240:
                        tempo = 240
                else:
                    if track < 0:
                        track = tracks - 1
                    elif track >= tracks:
                        track = 0

    if redraw:
        oled.fill(0)
        oled.text("BPM: {}".format(tempo), 0, 0, 1)
        oled.text("STP: {}/{}".format(step + 1, steps), 0, 10, 1)
        oled.text("TRK: {}/{}".format(track + 1, tracks), 0, 20, 1)
        if data[track][step][0] == -1:
            oled.text("Note: -", 0, 30, 1)
        else:
            oled.text("Note: {}".format(midi2str(data[track][step])), 0, 30, 1)
        if recording:
            oled.text("REC", 100, 0, 1)
        if step_mode:
            oled.text("ST", 100, 10, 1)
        oled.show()
