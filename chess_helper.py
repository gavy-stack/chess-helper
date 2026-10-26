import os
import sys
import math
import wave
import struct
import random
import tempfile
import subprocess
import tkinter as tk
import chess
import chess.engine

try:
    import winsound          # built into Windows
except ImportError:
    winsound = None


# ---------- Finding files (works in VS Code AND inside the .exe) ----------
def resource_path(*parts):
    base = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base, *parts)


STOCKFISH_PATH = resource_path("stockfish", "stockfish", "stockfish-windows-x86-64-universal.exe")

# ---------- Settings ----------
SQUARE = 56
LIGHT, DARK = "#f0d9b5", "#b58863"
LAST_MOVE_COLOR = "#cdd26a"
SELECT_COLOR = "#f6f669"
SUGGEST_FROM = "#6abf69"
SUGGEST_TO = "#2e9e44"
HOVER_COLOR = "#ffffff"

PIECE_SYMBOLS = {"P": "♟", "N": "♞", "B": "♝", "R": "♜", "Q": "♛", "K": "♚"}
PROMO_CHOICES = [(chess.QUEEN, "Queen", "♛"), (chess.ROOK, "Rook", "♜"),
                 (chess.BISHOP, "Bishop", "♝"), (chess.KNIGHT, "Knight", "♞")]
PROMO_NAMES = {p: name for p, name, _ in PROMO_CHOICES}


# ---------- Sound effects ----------
RATE = 44100
SOUND_DIR = os.path.join(tempfile.gettempdir(), "chess_helper_sounds")


def tone(freq, duration, volume, noise=0.0, decay=20):
    """Simple fading tone (used for the promotion sound)."""
    samples = []
    for i in range(int(RATE * duration)):
        t = i / RATE
        envelope = math.exp(-decay * t)
        wave_part = math.sin(2 * math.pi * freq * t) * (1 - noise)
        noise_part = random.uniform(-1, 1) * noise
        samples.append(volume * envelope * (wave_part + noise_part))
    return samples


# Wood "modes": (pitch in Hz, loudness, how fast it fades). Tweak these to change the sound!
WOOD_MODES = [(170, 1.0, 45), (390, 0.6, 60), (720, 0.4, 85), (1180, 0.25, 120)]


def knock(pitch=1.0, click=0.6, length=0.18):
    """One wooden 'thock': a tiny click followed by fading wood tones."""
    rng = random.Random(7)
    n = int(RATE * length)
    out = []
    lowpassed = 0.0
    for i in range(n):
        t = i / RATE
        s = 0.0
        for freq, amp, decay in WOOD_MODES:
            s += amp * math.sin(2 * math.pi * freq * pitch * t) * math.exp(-decay * t)
        lowpassed += 0.3 * (rng.uniform(-1, 1) - lowpassed)      # softened noise = the click
        s += click * 3 * lowpassed * math.exp(-700 * t)
        out.append(s)
    return out


def mix(parts, peak):
    """Layer several sounds (each starting at its own time) into one."""
    total = max(int(offset * RATE) + len(s) for offset, s in parts)
    buf = [0.0] * total
    for offset, s in parts:
        start = int(offset * RATE)
        for i, v in enumerate(s):
            buf[start + i] += v
    biggest = max(abs(v) for v in buf) or 1.0
    return [v / biggest * peak for v in buf]


def save_wav(name, samples):
    path = os.path.join(SOUND_DIR, name + ".wav")
    data = b"".join(struct.pack("<h", int(max(-1.0, min(1.0, s)) * 32000)) for s in samples)
    with wave.open(path, "w") as f:
        f.setnchannels(1)
        f.setsampwidth(2)
        f.setframerate(RATE)
        f.writeframes(data)
    return path


def make_sounds():
    os.makedirs(SOUND_DIR, exist_ok=True)
    sounds = {}
    sounds["move"] = save_wav("move", mix([(0, knock(1.0, 0.6, 0.16))], 0.75))
    sounds["capture"] = save_wav(
        "capture", mix([(0, knock(1.0, 1.0, 0.2)), (0.05, knock(0.8, 0.8, 0.2))], 0.95))
    sounds["promotion"] = save_wav(
        "promotion", [s * 1.0 for s in (tone(523, 0.12, 0.6, decay=8) + tone(659, 0.12, 0.6, decay=8)
                                        + tone(784, 0.12, 0.6, decay=8) + tone(1047, 0.35, 0.6, decay=6))])
    # Optional: real recordings override the generated sounds.
    # Put move.wav / capture.wav / promotion.wav in a folder called "sounds" next to this file.
    for name in sounds:
        custom = resource_path("sounds", name + ".wav")
        if os.path.exists(custom):
            sounds[name] = custom
    return sounds


SOUNDS = make_sounds()


def play(name):
    if winsound:
        try:
            winsound.PlaySound(SOUNDS[name], winsound.SND_FILENAME | winsound.SND_ASYNC)
        except Exception:
            pass


# ---------- Start the engine ----------
engine = chess.engine.SimpleEngine.popen_uci(
    STOCKFISH_PATH, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
board = chess.Board()
my_color = None
suggested_move = None
selected = None

# Dragging / animation state
dragging = False
drag_from = None
drag_x = drag_y = 0
press_was_selected = False
hidden_square = None      # a square whose piece is currently "floating" (so we don't draw it twice)
busy = False              # True while thinking or animating (ignores clicks)


# ---------- Board <-> screen position ----------
def square_to_cell(sq):
    f, r = chess.square_file(sq), chess.square_rank(sq)
    if my_color == chess.WHITE:
        return f, 7 - r
    return 7 - f, r


def cell_to_square(col, row):
    if my_color == chess.WHITE:
        return chess.square(col, 7 - row)
    return chess.square(7 - col, row)


def cell_center(sq):
    col, row = square_to_cell(sq)
    return col * SQUARE + SQUARE // 2, row * SQUARE + SQUARE // 2


def square_at(x, y):
    """The board square under a screen position, or None if outside the board."""
    col, row = int(x // SQUARE), int(y // SQUARE)
    if 0 <= col < 8 and 0 <= row < 8:
        return cell_to_square(col, row)
    return None


# ---------- Drawing ----------
def fill_square(sq, color):
    col, row = square_to_cell(sq)
    canvas.create_rectangle(col * SQUARE, row * SQUARE,
                            (col + 1) * SQUARE, (row + 1) * SQUARE,
                            fill=color, outline="")


def draw_piece(piece, x, y, tag=None, size=30, shadow=False):
    symbol = PIECE_SYMBOLS[piece.symbol().upper()]
    font = ("Segoe UI Symbol", size)
    tags = (tag,) if tag else ()
    if shadow:   # makes a lifted piece look like it's floating
        canvas.create_text(x + 4, y + 7, text=symbol, font=font, fill="#6b5232", tags=tags)
    for dx, dy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
        canvas.create_text(x + dx, y + dy, text=symbol, font=font, fill="black", tags=tags)
    canvas.create_text(x, y, text=symbol, font=font,
                       fill="white" if piece.color == chess.WHITE else "#222222", tags=tags)


def draw_board():
    canvas.delete("all")

    for sq in chess.SQUARES:
        is_light = (chess.square_file(sq) + chess.square_rank(sq)) % 2 == 1
        fill_square(sq, LIGHT if is_light else DARK)

    if board.move_stack:
        last = board.move_stack[-1]
        fill_square(last.from_square, LAST_MOVE_COLOR)
        fill_square(last.to_square, LAST_MOVE_COLOR)
    if suggested_move:
        fill_square(suggested_move.from_square, SUGGEST_FROM)
        fill_square(suggested_move.to_square, SUGGEST_TO)
    if selected is not None:
        fill_square(selected, SELECT_COLOR)

    for sq in chess.SQUARES:
        col, row = square_to_cell(sq)
        if row == 7:
            canvas.create_text(col * SQUARE + SQUARE - 8, row * SQUARE + SQUARE - 8,
                               text=chess.FILE_NAMES[chess.square_file(sq)],
                               font=("Arial", 8), fill="#555555")
        if col == 0:
            canvas.create_text(col * SQUARE + 8, row * SQUARE + 8,
                               text=str(chess.square_rank(sq) + 1),
                               font=("Arial", 8), fill="#555555")

    for sq in chess.SQUARES:
        piece = board.piece_at(sq)
        if piece and sq != hidden_square and not (dragging and sq == drag_from):
            x, y = cell_center(sq)
            draw_piece(piece, x, y)

    if selected is not None:
        for m in board.legal_moves:
            if m.from_square == selected:
                x, y = cell_center(m.to_square)
                canvas.create_oval(x - 6, y - 6, x + 6, y + 6, fill="#555555", outline="")

    if suggested_move:
        x1, y1 = cell_center(suggested_move.from_square)
        x2, y2 = cell_center(suggested_move.to_square)
        canvas.create_line(x1, y1, x2, y2, width=7, fill="#1b7f2f",
                           arrow=tk.LAST, arrowshape=(16, 18, 7))

    # outline of the square the dragged piece is hovering over
    canvas.create_rectangle(-100, -100, -90, -90, outline=HOVER_COLOR, width=3, tags="hover")

    if dragging:
        update_hover()
        draw_piece(board.piece_at(drag_from), drag_x, drag_y, tag="drag", size=36, shadow=True)


def update_hover():
    sq = square_at(drag_x, drag_y)
    if sq is None:
        canvas.coords("hover", -100, -100, -90, -90)
    else:
        col, row = square_to_cell(sq)
        canvas.coords("hover", col * SQUARE + 2, row * SQUARE + 2,
                      (col + 1) * SQUARE - 2, (row + 1) * SQUARE - 2)


# ---------- Animation ----------
def animate(piece, start, end, done, steps=10, delay=14):
    """Slide a floating piece from start to end, then call done()."""
    canvas.delete("drag")
    draw_piece(piece, start[0], start[1], tag="drag", size=36, shadow=True)
    pos = [start[0], start[1]]

    def step(i):
        t = i / steps
        t = 1 - (1 - t) ** 3                       # starts fast, settles gently
        nx = start[0] + (end[0] - start[0]) * t
        ny = start[1] + (end[1] - start[1]) * t
        canvas.move("drag", nx - pos[0], ny - pos[1])
        pos[0], pos[1] = nx, ny
        if i < steps:
            root.after(delay, lambda: step(i + 1))
        else:
            done()

    step(1)


# ---------- Promotion dialog ----------
def ask_promotion(prompt):
    choice = {"piece": None}
    win = tk.Toplevel(root)
    win.title("Promotion")
    win.resizable(False, False)
    win.transient(root)

    tk.Label(win, text=prompt, font=("Arial", 12, "bold")).pack(padx=20, pady=(15, 5))
    row = tk.Frame(win)
    row.pack(padx=15, pady=10)

    def pick(p):
        choice["piece"] = p
        win.destroy()

    for piece_type, name, symbol in PROMO_CHOICES:
        tk.Button(row, text=symbol + "\n" + name, font=("Segoe UI Symbol", 14),
                  width=7, height=3,
                  command=lambda p=piece_type: pick(p)).pack(side="left", padx=4)

    win.update_idletasks()
    x = root.winfo_x() + (root.winfo_width() - win.winfo_width()) // 2
    y = root.winfo_y() + (root.winfo_height() - win.winfo_height()) // 2
    win.geometry("+%d+%d" % (x, y))
    win.grab_set()
    root.wait_window(win)
    return choice["piece"]


# ---------- Game flow ----------
def move_text(move):
    text = chess.square_name(move.from_square) + " → " + chess.square_name(move.to_square)
    if move.promotion:
        text += " (" + PROMO_NAMES[move.promotion] + ")"
    return text


def make_move(move):
    if move.promotion:
        play("promotion")
    elif board.is_capture(move):
        play("capture")
    else:
        play("move")
    board.push(move)


def refresh():
    global suggested_move, busy
    moves_label.config(text="Moves so far: " + chess.Board().variation_san(board.move_stack))

    if board.is_game_over():
        suggested_move = None
        busy = False
        status_label.config(text="Game over.")
        suggestion_label.config(text="Result: " + board.result(), fg="red")
        played_button.config(state="disabled")
        draw_board()
        return

    if board.turn == my_color:
        status_label.config(text="YOUR TURN. Play the suggestion, or drag your own move.")
        suggestion_label.config(text="Thinking...", fg="gray")
        suggested_move = None
        busy = True
        draw_board()
        root.update()
        result = engine.play(board, chess.engine.Limit(time=1.0))
        suggested_move = result.move
        busy = False
        suggestion_label.config(text="Best move: " + move_text(suggested_move), fg="green")
        played_button.config(state="normal")
    else:
        suggested_move = None
        busy = False
        status_label.config(text="OPPONENT'S TURN. Drag the piece they moved to where it went.")
        suggestion_label.config(text="Waiting for opponent...", fg="gray")
        played_button.config(state="disabled")
    draw_board()


def build_move(frm, to):
    """Returns a legal move (asking about promotion if needed), or None."""
    moving = board.piece_at(frm)
    move = chess.Move(frm, to)
    if moving.piece_type == chess.PAWN and chess.square_rank(to) in (0, 7):
        if chess.Move(frm, to, promotion=chess.QUEEN) in board.legal_moves:
            prompt = "Promote your pawn to:" if board.turn == my_color \
                else "What did the opponent's pawn become?"
            piece_type = ask_promotion(prompt)
            if piece_type is None:
                return None
            move = chess.Move(frm, to, promotion=piece_type)
    return move if move in board.legal_moves else None


def finish_move(move):
    global hidden_square, busy
    hidden_square = None
    busy = False
    make_move(move)
    refresh()


def finish_back():
    global hidden_square, busy
    hidden_square = None
    busy = False
    draw_board()


def attempt_move(frm, to, start_xy):
    """Try to move a piece; slide it into place if legal, or back home if not."""
    global busy, hidden_square, selected
    piece = board.piece_at(frm)
    move = build_move(frm, to) if to is not None else None
    busy = True
    hidden_square = frm
    selected = None
    draw_board()
    if move is None:
        animate(piece, start_xy, cell_center(frm), finish_back)
    else:
        animate(piece, start_xy, cell_center(to), lambda: finish_move(move))


# ---------- Mouse handling ----------
def on_press(event):
    global selected, dragging, drag_from, drag_x, drag_y, press_was_selected
    if busy or my_color is None or board.is_game_over():
        return
    sq = square_at(event.x, event.y)
    if sq is None:
        return
    piece = board.piece_at(sq)
    own_piece = piece is not None and piece.color == board.turn

    # A piece is already selected and you clicked somewhere else: try that move
    if selected is not None and sq != selected and not own_piece:
        attempt_move(selected, sq, cell_center(selected))
        return

    if own_piece:
        press_was_selected = (selected == sq)
        selected = sq
        dragging = True
        drag_from = sq
        drag_x, drag_y = event.x, event.y
        canvas.config(cursor="fleur")
        draw_board()
    else:
        selected = None
        draw_board()


def on_motion(event):
    global drag_x, drag_y
    if not dragging:
        return
    canvas.move("drag", event.x - drag_x, event.y - drag_y)
    drag_x, drag_y = event.x, event.y
    update_hover()


def on_release(event):
    global dragging, selected
    if not dragging:
        return
    dragging = False
    canvas.config(cursor="")
    target = square_at(event.x, event.y)

    if target == drag_from:                  # it was just a click, not a drag
        if press_was_selected:
            selected = None
        draw_board()
        return

    attempt_move(drag_from, target, (event.x, event.y))


def play_suggestion():
    global busy, hidden_square, selected
    if busy or not suggested_move:
        return
    move = suggested_move
    piece = board.piece_at(move.from_square)
    busy = True
    hidden_square = move.from_square
    selected = None
    draw_board()
    animate(piece, cell_center(move.from_square), cell_center(move.to_square),
            lambda: finish_move(move), steps=14)


def undo_move():
    global selected
    if busy or my_color is None or not board.move_stack:
        return
    board.pop()
    selected = None
    refresh()


def start_game(color):
    global my_color, board, suggested_move, selected
    my_color = color
    board = chess.Board()
    suggested_move = None
    selected = None
    picker_frame.pack_forget()
    game_frame.pack(pady=10)
    refresh()


def new_game():
    global my_color
    if busy:
        return
    my_color = None
    game_frame.pack_forget()
    picker_frame.pack(pady=40)


def on_close():
    engine.quit()
    root.destroy()


# ---------- The window ----------
# Makes Windows show YOUR icon on the taskbar instead of Python's
try:
    import ctypes
    ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("gavri.chesshelper")
except Exception:
    pass

root = tk.Tk()
root.title("Chess Helper")
root.geometry("480x740")
root.protocol("WM_DELETE_WINDOW", on_close)

# Window icon (top-left corner of the app)
try:
    root.iconbitmap(resource_path("ChessHelper.ico"))
except Exception:
    pass

picker_frame = tk.Frame(root)
picker_frame.pack(pady=40)
tk.Label(picker_frame, text="Choose your side", font=("Arial", 16)).pack(pady=10)
tk.Button(picker_frame, text="Play as White", width=20, height=2,
          command=lambda: start_game(chess.WHITE)).pack(pady=5)
tk.Button(picker_frame, text="Play as Black", width=20, height=2,
          command=lambda: start_game(chess.BLACK)).pack(pady=5)

game_frame = tk.Frame(root)

status_label = tk.Label(game_frame, text="", font=("Arial", 11), wraplength=440)
status_label.pack(pady=3)

suggestion_label = tk.Label(game_frame, text="", font=("Arial", 20, "bold"), fg="green")
suggestion_label.pack(pady=5)

canvas = tk.Canvas(game_frame, width=SQUARE * 8, height=SQUARE * 8, highlightthickness=0)
canvas.pack(pady=5)
canvas.bind("<ButtonPress-1>", on_press)
canvas.bind("<B1-Motion>", on_motion)
canvas.bind("<ButtonRelease-1>", on_release)

buttons_frame = tk.Frame(game_frame)
buttons_frame.pack(pady=8)
played_button = tk.Button(buttons_frame, text="I played the suggestion", command=play_suggestion)
played_button.grid(row=0, column=0, padx=4)
tk.Button(buttons_frame, text="Undo", width=8, command=undo_move).grid(row=0, column=1, padx=4)
tk.Button(buttons_frame, text="New game", width=10, command=new_game).grid(row=0, column=2, padx=4)

moves_label = tk.Label(game_frame, text="", wraplength=440, justify="left", font=("Arial", 10))
moves_label.pack(pady=5)

root.mainloop()