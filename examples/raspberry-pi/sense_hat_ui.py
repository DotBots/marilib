# this only works on raspberry pi
# to install the emulator sense_emu library:
# - sudo apt-get install python3-gi python3-gi-cairo
# - pip install sense-emu
# to install the real sense_hat library:
# - sudo apt-get install sense-hat

from sense_emu import SenseHat
import threading
import time

# ======================= Code for driving the sense hat =======================

s = SenseHat()
# s.set_rotation(90)
# ---------- colors ----------
r = [255, 0, 0]
w = [255, 255, 255]
g = [0, 128, 0]
y = [255, 255, 0]
b = [0, 0, 255]
p = [191, 0, 255]

# clear the screen to have a white background
s.clear(w)

# ---------- config ----------
nb_max = 102  # maximum number of nodes for this schedule -- will come from marilib
nb_row = 8  # number of pixels in a row
bg = w  # background of the bottom 6*6 area
nb_nodes_per_pixel = nb_max // nb_row

# ---------- shared state ----------
state_lock = threading.Lock()
node_changed = threading.Event()

nb_nodes = 0  # current nodes
prev_pixels = 0  # how many pixels were lit last time


# 6x6 font: each row is a 6-bit number (bit 5 = leftmost, bit 0 = rightmost)
font_6x6 = {
    " ": [0b000000, 0b000000, 0b000000, 0b000000, 0b000000, 0b000000],
    "0": [0b011110, 0b100001, 0b100001, 0b100001, 0b100001, 0b011110],
    "1": [0b001000, 0b011000, 0b001000, 0b001000, 0b001000, 0b111110],
    "2": [0b011110, 0b100001, 0b000010, 0b000100, 0b001000, 0b111111],
    "3": [0b011110, 0b100001, 0b000110, 0b000001, 0b100001, 0b011110],
    "4": [0b000100, 0b001100, 0b010100, 0b100100, 0b111111, 0b000100],
    "5": [0b111111, 0b100000, 0b111110, 0b000001, 0b100001, 0b011110],
    "6": [0b011110, 0b100000, 0b111110, 0b100001, 0b100001, 0b011110],
    "7": [0b111111, 0b000001, 0b000010, 0b000100, 0b001000, 0b010000],
    "8": [0b011110, 0b100001, 0b011110, 0b100001, 0b100001, 0b011110],
    "9": [0b011110, 0b100001, 0b100001, 0b111111, 0b000001, 0b011110],
}


def choose_color(multiplier: int):
    """
    Choose color of pixels depending on number of nodes  that joined
    """
    if multiplier > 8:
        return w
    if multiplier <= 3:
        return g
    if multiplier < 6:
        return y
    if multiplier <= 8:
        return r


def _set_top(x, color):
    s.set_pixel(x, 0, color)


def display_num_nodes():
    """
    update the top bar so that every (nb_nodes//nb_row) nodes that joined or left
    changes the bar by 1 pixel.
    example: if nb_max of nodes is 66 then 66//8 = 8 so every 8 nodes joining lights up one more pixel
    and every 8 nodes leaving resets 1 pixel
    """
    global prev_pixels

    with state_lock:
        current_nodes = nb_nodes
        old_pixels = prev_pixels

    new_pixels = current_nodes // nb_nodes_per_pixel
    # nodes have joined
    if new_pixels > old_pixels:
        # light pixels from old_pixels .. new_pixels-1
        for i in range(old_pixels, new_pixels):
            _set_top(i, choose_color(i + 1))

    # nodes left
    elif new_pixels < old_pixels:
        # clear pixels from new_pixels .. old_pixels-1
        for i in range(new_pixels, old_pixels):
            _set_top(i, bg)

    # update number of pixels
    with state_lock:
        prev_pixels = new_pixels


def display_num_nodes_thread():
    """
    Background thread: wait for node changes and update the top bar.
    """
    display_num_nodes()  # initial paint
    while True:
        node_changed.wait()
        node_changed.clear()
        display_num_nodes()


def number_to_columns(rows):
    """Convert 6 rows of 6-bit ints (a number) to a list of 6 columns of pixels
    (each column is a list of 6 booleans
    True=ON, False=OFF)."""
    cols = []
    for c in range(6):  # 0..5 (left->right)
        mask = 1 << (5 - c)
        col = [(rows[r] & mask) != 0 for r in range(6)]  # top->bottom
        cols.append(col)
    return cols


def text_to_columns(text):
    """Convert text to a list of columns with 1 blank column between the numbers."""
    stream = []
    for ch in text:
        rows = font_6x6.get(ch, font_6x6[" "])
        stream.extend(number_to_columns(rows))
        stream.append([False] * 6)  # spacing column
    return stream


def display_scrolling_message(text, fg, bg, speed, scrolling_times):
    """
    Scroll a 6x6 message across the Sense HAT.
    Draws ONLY on rows y=2..7 (leaves y=0 and y=1 unchanged).
    """
    text = " " + text
    cols = text_to_columns(text)
    cols.extend([[False] * 6 for _ in range(8)])  # right padding so it scrolls off

    width = 8
    for i in range(scrolling_times):
        for offset in range(len(cols)):
            for x in range(width):
                col_index = offset + x
                col = cols[col_index] if 0 <= col_index < len(cols) else [False] * 6

                # Map 6-tall column onto y = 2..7
                for y6 in range(6):
                    y = 2 + y6
                    s.set_pixel(x, y, fg if col[y6] else bg)
            time.sleep(speed)


def display_static_message(text, fg, bg):
    """
    Show a 6x6 message without scrolling.
    Draws only on rows y=2..7, rows 0 and 1 are not used
    """
    cols = text_to_columns(text)
    width = 8
    # draw 8 columns
    for x in range(width):
        src_index = x - 1  # shift right by 1 column
        if 0 <= src_index < len(cols):
            col = cols[src_index]
        else:
            col = [False] * 6  # blank when out of bounds

        for y6 in range(6):
            y = 2 + y6  # vertical position unchanged
            s.set_pixel(x, y, fg if col[y6] else bg)


def message_thread(
    static_text, scroll_text, fg_static, fg_scroll, bg, scroll_speed, scroll_repeats
):
    """
    alternates:
      1) draw static message; schedule
      2) scroll another message: network id (net_id) scroll_repeats times at scroll_speed
    Loops forever.
    """
    while True:
        display_static_message(static_text, fg_static, bg)
        time.sleep(3)
        display_scrolling_message(scroll_text, fg_scroll, bg, scroll_speed, scroll_repeats)
        time.sleep(0.2)


# ========================= functions just for testing =========================


def node_join(n: int):
    """
    Safely add n nodes and notify the drawer.
    """
    global nb_nodes
    with state_lock:
        nb_nodes = min(nb_nodes + n, nb_max)
    node_changed.set()


# just for testing
def node_leave(n: int):
    """
    Safely remove n nodes and notify the drawer.
    """
    global nb_nodes
    with state_lock:
        nb_nodes = max(nb_nodes - n, 0)
    node_changed.set()


# ================================ main function ===============================

if __name__ == "__main__":
    scroll = True
    speed = 0.1
    schedule = 5  # will come from marilib
    net_id = 1200  # will come from marilib
    scrolling_times = 3

    threading.Thread(target=display_num_nodes_thread, daemon=True).start()

    threading.Thread(
        target=message_thread,
        args=(str(schedule), str(net_id), b, p, w, speed, scrolling_times),
        daemon=True,
    ).start()

    # demo
    while True:
        time.sleep(0.8)
        node_join(24)  # +1 bar pixel
        time.sleep(0.8)
        node_leave(8)  # -1 bar pixel
