import usb_midi
import adafruit_ssd1306
import digitalio

import board
import busio as io
import time
import keypad
import asyncio

_ext_sync_pin = digitalio.DigitalInOut(board.GP22)
_ext_sync_pin.direction = digitalio.Direction.INPUT
_ext_sync_pin.pull = digitalio.Pull.UP

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


def nt(num):
    return (num, 127, 0, 0)


def e1m1():
    return [nt(28), nt(40), nt(52), nt(28), nt(40), nt(50), nt(28), nt(40), nt(48), nt(28), nt(40), nt(46), nt(28), nt(40), nt(47), nt(48)]


def prepare_but(pin):
    p = digitalio.DigitalInOut(pin)
    p.direction = digitalio.Direction.INPUT
    p.pull = digitalio.Pull.UP
    return lambda: p.value


async def wait(ms):
    await asyncio.sleep_ms(int(ms))


async def wait_for_trigger(interval_ms=1):
    global _ext_sync_pin, _step_mode
    previous_value = _ext_sync_pin.value
    while True:
        current_value = _ext_sync_pin.value
        if (not current_value and previous_value) or not _step_mode:
            print("Ext trigger...")
            break
        await asyncio.sleep_ms(interval_ms)
        previous_value = current_value


keyboard = keypad.KeyMatrix(row_pins=(board.GP6, board.GP7, board.GP8, board.GP9), column_pins=(
    board.GP10, board.GP11, board.GP12, board.GP13, board.GP14), columns_to_anodes=False, interval=0.02)

i2c = io.I2C(board.GP21, board.GP20)
oled = adafruit_ssd1306.SSD1306_I2C(128, 64, i2c, addr=0x3C)
uart_midi = io.UART(board.GP4, board.GP5, baudrate=32250)
usb_midi_out = usb_midi.ports[1]

oled.fill(0)
oled.show()

_tempo = 120
_steps = 16
_step = 0
_step_progress = 0
_notes_per_beat = 2

_track = 0
_tracks = 4
_octave = 5

_last_step_time = 0
_full_velocity = True
_recording = False
_step_mode = False
_redraw = True

_data = []
_channels = []

for i in range(_tracks):
    _data.append([])
    _channels.append(0)
    for j in range(_steps):
        _data[i].append((-1, 0, 0, 0))

_data[0] = e1m1()
print(_data)


def reset_track(t):
    for j in range(_steps):
        _data[t][j] = ((-1, 0, 0, 0))


midilock = asyncio.Lock()
datalock = asyncio.Lock()


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
    async with midilock:
        uart_midi.write(msg)
        usb_midi_out.write(msg)


async def send_note_off(note, ch=0):
    note_off_status = (0x80 | (ch))
    msg = bytearray([note_off_status, note, 0])
    async with midilock:
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


async def send_note_doublet(note, vel, duration, ch=0):
    await send_note_on(note, vel, ch)
    await asyncio.sleep_ms(int(duration / 2 * 0.9))
    await send_note_off(note, ch)
    await asyncio.sleep_ms(int(duration * 0.1))
    await send_note_on(note, vel, ch)
    await asyncio.sleep_ms(int(duration / 2 * 0.9))
    await send_note_off(note, ch)


async def all_notes_off():
    tasks = []
    for i in range(_tracks):
        for j in range(_steps):
            if not _data[i][j][0] == -1:
                tasks.append(send_note_off(_data[i][j][0], _channels[i]))
    await asyncio.gather(*tasks)


async def get_display_data():
    async with datalock:
        return (_tempo, _octave, _step, _steps, _track, _tracks, _recording, _step_mode, _channels[_track], _data[_track][_step], _notes_per_beat, _redraw)


async def get_application_data():
    async with datalock:
        return (_tempo, _octave, _step, _steps, _track, _tracks, _recording, _step_mode, _channels[_track], _notes_per_beat)


async def update_application_data(tempo, octave, recording, step_mode, track, channel, notes_per_beat):
    global _tempo, _octave, _step_mode, _track, _recording, _channels, _notes_per_beat
    async with datalock:
        _tempo = tempo
        _octave = octave
        _step_mode = step_mode
        _track = track
        _channels[track] = channel
        _notes_per_beat = notes_per_beat
        _recording = recording


async def get_step_data(track, step):
    global _data
    async with datalock:
        return _data[track][step]


async def set_step_data(track, step, step_data):
    global _data
    async with datalock:
        _data[track][step] = step_data


async def next_step():
    global _step, _steps
    async with datalock:
        _step += 1
        if _step >= _steps:
            _step -= _steps


async def update_display():
    global _redraw
    while True:
        tempo, octave, step, steps, track, tracks, recording, step_mode, current_channel, step_data, notes_per_beat, redraw = await get_display_data()
        if recording:
            oled.fill(0)
            oled.text("BPM: {} NPB: {}".format(
                tempo, 2 ** notes_per_beat), 0, 0, 1)
            oled.text("OCT: {}".format(octave), 0, 10, 1)
            oled.text("STP: {}/{}".format(step + 1, steps), 0, 20, 1)
            oled.text("TRK: {}/{} (CH{})".format(track + 1,
                                                 tracks, current_channel + 1), 0, 30, 1)
            if step_data[0] == -1:
                oled.text("Note: -", 0, 40, 1)
            else:
                oled.text("Note: {}".format(midi2str(step_data)), 0, 40, 1)
            if recording:
                oled.text("REC", 100, 0, 1)
            if step_mode:
                oled.text("ST", 100, 10, 1)
            oled.show()
            await asyncio.sleep_ms(100)
        elif redraw:
            oled.fill(0)
            oled.text("BPM: {} NPB: {}".format(
                tempo, 2 ** notes_per_beat), 0, 0, 1)
            oled.text("PLA", 100, 0, 1)
            if step_mode:
                oled.text("ST", 100, 10, 1)
            oled.show()
            _redraw = False
            await asyncio.sleep_ms(100)
        else:
            await asyncio.sleep_ms(100)


async def handle_input():
    modifier1_pressed = False
    modifier2_pressed = False
    global _redraw
    while True:
        tempo, octave, step, steps, track, tracks, recording, step_mode, current_channel, notes_per_beat = await get_application_data()
        while True:
            e = keyboard.events.get()
            if e == None:
                break

            key = keymap[e.key_number]

            if key < 12:
                if e.pressed:
                    await send_note_on(key + octave * 12, 127)

                    if recording:
                        await set_step_data(track, step, (key + octave * 12, 127, 0, 0))
                else:
                    await send_note_off(key + octave * 12)
                    pass

            elif e.pressed:
                if not recording:
                    _redraw = True

                if key == 12:
                    if modifier1_pressed:
                        reset_track(track)
                    else:
                        if not step_mode:
                            recording = not recording
                        else:
                            step_mode = False
                elif key == 13:
                    if not step_mode:
                        step_mode = True
                    else:
                        await next_step()
                elif key == 14:
                    if modifier1_pressed:
                        notes_per_beat += 1
                        if notes_per_beat > 4:
                            notes_per_beat = 0
                    else:
                        if recording:
                            n, v, l, m = await get_step_data(track, step)
                            l += 1
                            if l > 4:
                                l = 0

                            await set_step_data(track, step, (n, v, l, m))
                elif key == 15:
                    if modifier1_pressed:
                        octave += 1
                    elif modifier2_pressed:
                        current_channel += 1
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
                        n, v, l, m = await get_step_data(track, step)
                        m += 1
                        if m > 2:
                            m = 0

                        await set_step_data(track, step, (n, v, l, m))
                elif key == 19:
                    if modifier1_pressed:
                        octave -= 1
                    elif modifier2_pressed:
                        current_channel -= 1
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
                        if current_channel < 0:
                            current_channel = 15
                        elif current_channel > 15:
                            current_channel = 0
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

        await update_application_data(tempo, octave, recording, step_mode, track, current_channel, notes_per_beat)
        await asyncio.sleep_ms(10)


async def sequencer_routine():
    while True:
        tempo, octave, step, steps, track, tracks, recording, step_mode, current_channel, notes_per_beat = await get_application_data()
        tasks = []

        if recording:
            await asyncio.sleep_ms(33)
            continue

        target_step_time = 60000 // tempo // (2 ** notes_per_beat)

        for i in range(tracks):
            step_data = await get_step_data(i, step)
            if not step_data[0] == -1:
                if step_data[3] == 1:
                    tasks.append(send_note_doublet(step_data[0], step_data[1], int(
                        target_step_time / (2 ** step_data[2]))))
                elif step_data[3] == 2:
                    tasks.append(send_note_triplet(step_data[0], step_data[1], int(
                        target_step_time / (2 ** step_data[2]))))
                else:
                    tasks.append(send_note(step_data[0], step_data[1], int(
                        target_step_time / (2 ** step_data[2]))))

        await next_step()
        if not step_mode:
            tasks.append(wait(target_step_time))
        else:
            tasks.append(wait_for_trigger())
        await asyncio.gather(*tasks)


async def main():
    input_task = asyncio.create_task(handle_input())
    display_task = asyncio.create_task(update_display())
    sequencer_task = asyncio.create_task(sequencer_routine())

    await asyncio.gather(sequencer_task, display_task, input_task)

asyncio.run(main())
