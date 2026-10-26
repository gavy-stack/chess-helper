# Chess Helper

A training tool for practicing against chess bots offline. Enter the bot's moves
on the board, and Stockfish suggests your best next move with a green arrow.
Includes drag-and-drop pieces, wooden-style sound effects, undo, and pawn promotion choices.

**For practice against bots only. Do not use it in live games against people or on sites with fair-play rules.**

## Setup (Windows)

1. Install Python 3.
2. Install the chess library: `py -m pip install -r requirements.txt`
3. Download Stockfish from https://stockfishchess.org/download and place it so this path exists:
   `stockfish/stockfish/stockfish-windows-x86-64-universal.exe`
4. Run: `py chess_helper.py`

## Optional

- Put `move.wav`, `capture.wav` and `promotion.wav` in a `sounds` folder to replace the generated sounds.
- Put your own `ChessHelper.ico` next to `chess_helper.py` for a custom window icon.