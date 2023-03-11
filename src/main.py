import usb_midi
import adafruit_ssd1306
import digitalio

import board
import busio as io
import time
import keypad
import asyncio

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
    l = midi[2]
    m = midi[3]
    return "{} ({}) M{}".format(t1b1[note % 12] + str(int(note / 12) - 2), 2 ** l, m)


def prepare_but(pin):
    p = digitalio.DigitalInOut(pin)
    p.direction = digitalio.Direction.INPUT
    p.pull = digitalio.Pull.UP
    return lambda: p.value


keyboard = keypad.KeyMatrix(row_pins=(board.GP6, board.GP7, board.GP8, board.GP9), column_pins=(
    board.GP10, board.GP11, board.GP12, board.GP13, board.GP14), columns_to_anodes=False)

i2c = io.I2C(board.GP21, board.GP20)
oled = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c, addr=0x3C)
uart_midi = io.UART(board.GP4, board.GP5, baudrate=32250, timeout=0.001)
usb_midi_out = usb_midi.ports[1]

oled.fill(0)
oled.show()

tempo = 120
steps = 16
step = 0
step_progress = 0
notes_per_beat = 4

track = 0
tracks = 4
octave = 5

last_step_time = 0
full_velocity = True
recording = False
step_mode = False
modifier1_pressed = False
modifier2_pressed = False

data = []
channels = []

for i in range(tracks):
    data.append([])
    channels.append(0)
    for j in range(steps):
        data[i].append((-1, 0, 0, 0))


def reset_track(t):
    for j in range(steps):
        data[t][j] = ((-1, 0, 0, 0))


lock = asyncio.Lock()


def _send_note_on(note, vel, ch=0):
    note_on_status = (0x90 | (ch))
    msg = bytearray([note_on_status, note, vel])
    uart_midi.write(msg)
    usb_midi_out.write(msg)


def _send_note_off(note, ch=0):
    note_off_status = (0x80 | (ch))
    msg = bytearray([note_off_status, note, 0])
    uart_midi.write(msg)
    usb_midi_out.write(msg)


async def send_note_on(note, vel, ch=0):
    note_on_status = (0x90 | (ch))
    msg = bytearray([note_on_status, note, vel])
    async with lock:
        uart_midi.write(msg)
        usb_midi_out.write(msg)


async def send_note_off(note, ch=0):
    note_off_status = (0x80 | (ch))
    msg = bytearray([note_off_status, note, 0])
    async with lock:
        uart_midi.write(msg)
        usb_midi_out.write(msg)


async def send_note(note, vel, duration, ch=0):
    await send_note_on(note, vel, ch)
    await asyncio.sleep_ms(duration)
    await send_note_off(note, ch)


async def send_note_triplet(note, vel, duration, ch=0):
    await send_note_on(note, vel, ch)
    await asyncio.sleep_ms(int(duration / 3 * 0.9))
    await send_note_off(note, ch)
    await asyncio.sleep_ms(int(duration * 0.1))
    await send_note_on(note, vel, ch)
    await asyncio.sleep_ms(int(duration / 3 * 0.9))
    await send_note_off(note, ch)
    await asyncio.sleep_ms(int(duration * 0.1))
    await send_note_on(note, vel, ch)
    await asyncio.sleep_ms(int(duration / 3 * 0.9))
    await send_note_off(note, ch)
    await asyncio.sleep_ms(int(duration * 0.1))


def all_notes_off():
    for i in range(tracks):
        for j in range(steps):
            if not data[i][j][0] == -1:
                asyncio.run(send_note_off(data[i][j][0], channels[i]))


print("Initialized...")
while True:
    redraw = False
    current_time = time.monotonic()

    # if isinstance(msg, NoteOn) and msg.velocity != 0:
    #     print(msg)
    #     if recording:
    #         data[track][step] = (
    #             msg.note, 127 if full_velocity else msg.velocity, 0)
    #         redraw = True

    target_step_time = 60.0 / tempo / notes_per_beat

    if not step_mode:
        if current_time - last_step_time > target_step_time:
            last_step_time = current_time
            redraw = True
            step += 1
            if step >= steps:
                step -= steps

            for t in data:
                n = t[step]

                if n[0] != -1:
                    if n[3] == 1:
                        asyncio.run(
                            send_note(n[0], n[1], int(1000 * target_step_time * 1.2), channels[track]))
                    elif n[3] == 2:
                        asyncio.run(
                            send_note_triplet(n[0], n[1], int(1000 * target_step_time), channels[track]))
                    else:
                        asyncio.run(
                            send_note(n[0], n[1], int(1000 * target_step_time / (2 ** n[2])), channels[track]))

    while True:
        e = keyboard.events.get()
        if e == None:
            break

        key = keymap[e.key_number]

        if key < 12:
            if e.pressed:
                asyncio.run(send_note_on(key + octave * 12, 127))

                if recording:
                    data[track][step] = (key + octave * 12, 127, 0, 0)
                    redraw = True
            else:
                asyncio.run(send_note_off(key + octave * 12))
                pass

        elif e.pressed:
            print(key - 11)
            redraw = True

            if key == 12:
                if modifier1_pressed:
                    reset_track(track)
                else:
                    if not step_mode:
                        recording = not recording
                    else:
                        step_mode = False
                        last_step_time = current_time
            elif key == 13:
                if not step_mode:
                    step_mode = True
                else:
                    step += 1
                    if step >= steps:
                        step -= steps
            elif key == 14:
                if recording:
                    n, v, l, m = data[track][step]
                    l += 1
                    if l > 4:
                        l = 0

                    data[track][step] = (n, v, l, m)
            elif key == 15:
                if modifier1_pressed:
                    octave += 1
                elif modifier2_pressed:
                    channels[track] += 1
                elif not recording:
                    tempo += 1
                else:
                    track += 1
            elif key == 16:
                modifier1_pressed = True
            elif key == 17:
                modifier2_pressed = True
            elif key == 18:
                if recording:
                    n, v, l, m = data[track][step]
                    m += 1
                    if m > 2:
                        m = 0

                    data[track][step] = (n, v, l, m)
            elif key == 19:
                if modifier1_pressed:
                    octave -= 1
                elif modifier2_pressed:
                    channels[track] -= 1
                elif not recording:
                    tempo -= 1
                else:
                    track -= 1

            if key == 15 or key == 19:
                if modifier1_pressed:
                    if octave < 0:
                        octave = 9
                    elif octave > 9:
                        octave = 0
                elif modifier2_pressed:
                    if channels[track] < 0:
                        channels[track] = 15
                    elif channels[track] > 15:
                        channels[track] = 0
                elif not recording:
                    if tempo < 0:
                        tempo = 0
                    elif tempo > 240:
                        tempo = 240
                else:
                    if track < 0:
                        track = tracks - 1
                    elif track >= tracks:
                        track = 0
        elif e.released:
            if key == 16:
                modifier1_pressed = False
            if key == 17:
                modifier2_pressed = False

    if redraw:
        oled.fill(0)
        oled.text("BPM: {} OCT: {}".format(tempo, octave), 0, 0, 1)
        oled.text("STP: {}/{}".format(step + 1, steps), 0, 10, 1)
        oled.text("TRK: {}/{} (CH{})".format(track + 1,
                  tracks, channels[track] + 1), 0, 20, 1)
        if data[track][step][0] == -1:
            oled.text("Note: -", 0, 30, 1)
        else:
            oled.text("Note: {}".format(midi2str(data[track][step])), 0, 30, 1)
        if recording:
            oled.text("REC", 100, 0, 1)
        if step_mode:
            oled.text("ST", 100, 10, 1)
        oled.show()
