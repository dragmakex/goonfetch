from __future__ import annotations

import base64
from contextlib import contextmanager
from io import BytesIO
import os
from pathlib import Path
import select
import subprocess
import sys
import tempfile
import termios
from time import monotonic, sleep
import tty
from typing import Iterable

from PIL import Image as pillow_image, ImageSequence
from rich.console import Console
from textual_image.renderable.tgp import Image


ASCII_CELL_ASPECT = 0.55
KITTY_IMAGE_ID = 31337
KITTY_CHUNK_SIZE = 16384



def graphics_supported() -> bool:
    return bool(
        os.environ.get("KITTY_WINDOW_ID")
        or os.environ.get("TERM_PROGRAM") == "ghostty"
        or os.environ.get("TERM", "").startswith("xterm-kitty")
    )



def _fit_cells(size: tuple[int, int], rc: tuple[int, int]) -> tuple[int, int]:
    maw, mah = rc
    maw -= 3
    mah += 1
    w_o, h_o = size
    if h_o * ASCII_CELL_ASPECT / mah > w_o / maw:
        w, h = int(w_o * mah / h_o / ASCII_CELL_ASPECT), mah
    else:
        w, h = maw, int(h_o * maw / w_o * ASCII_CELL_ASPECT)
    return max(w, 1), max(h, 1)



def print_kitty(imbytes: BytesIO, rc: tuple[int, int]) -> tuple[int, int]:
    imag = pillow_image.open(imbytes).convert("RGBA")
    return print_kitty_image(imag, rc)



def print_kitty_image(imag: pillow_image.Image, rc: tuple[int, int]) -> tuple[int, int]:
    console = Console()
    w, h = _fit_cells(imag.size, rc)
    console.print(Image(imag, width=w + 3, height=h))
    return w, h



def _encode_png_bytes(image: pillow_image.Image) -> bytes:
    buf = BytesIO()
    image.save(buf, format="PNG")
    return buf.getvalue()



def _tty_write(data: str) -> None:
    sys.stdout.write(data)
    sys.stdout.flush()



def _kitty_write(params: dict[str, str | int], payload: bytes = b"") -> None:
    encoded = base64.b64encode(payload).decode("ascii") if payload else ""
    params_str = ",".join(f"{key}={value}" for key, value in params.items())

    if not encoded:
        _tty_write(f"\x1b_G{params_str};\x1b\\")
        return

    first = True
    for start in range(0, len(encoded), KITTY_CHUNK_SIZE):
        chunk = encoded[start : start + KITTY_CHUNK_SIZE]
        more = 1 if start + KITTY_CHUNK_SIZE < len(encoded) else 0
        if first:
            chunk_prefix = f"{params_str},m={more}"
            first = False
        else:
            chunk_prefix = f"m={more}"
        _tty_write(f"\x1b_G{chunk_prefix};{chunk}\x1b\\")



def _kitty_delete_image(image_id: int) -> None:
    _kitty_write({"a": "d", "d": "I", "i": image_id})



def _prepare_frame(frame: pillow_image.Image, rc: tuple[int, int]) -> tuple[pillow_image.Image, int, int]:
    frame_rgba = frame.convert("RGBA")
    cols, rows = _fit_cells(frame_rgba.size, rc)
    target_px = (max(cols * 10, 1), max(rows * 20, 1))
    prepared = frame_rgba.copy()
    prepared.thumbnail(target_px, pillow_image.Resampling.LANCZOS)
    return prepared, cols, rows



def _kitty_display_png(png_bytes: bytes, image_id: int, cols: int, rows: int, width: int, height: int) -> None:
    _kitty_write(
        {
            "a": "T",
            "f": 100,
            "i": image_id,
            "q": 2,
            "s": width,
            "v": height,
            "c": cols + 3,
            "r": rows,
        },
        payload=png_bytes,
    )



def _reserve_animation_space(rows: int) -> None:
    _tty_write("\x1b[s")
    if rows > 1:
        _tty_write("\n" * (rows - 1))
    _tty_write("\x1b[u")



def _finish_animation(rows: int, image_id: int) -> None:
    _tty_write("\x1b[u")
    _kitty_delete_image(image_id)
    if rows > 0:
        _tty_write(f"\x1b[{rows}B")



@contextmanager
def _raw_stdin_enabled():
    if not sys.stdin.isatty():
        yield False
        return

    fd = sys.stdin.fileno()
    old_attrs = termios.tcgetattr(fd)
    try:
        tty.setcbreak(fd)
        yield True
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old_attrs)



def _quit_requested(stdin_enabled: bool) -> bool:
    if not stdin_enabled:
        return False
    ready, _, _ = select.select([sys.stdin], [], [], 0)
    if not ready:
        return False
    char = sys.stdin.read(1)
    return char.lower() == "q"



def _sleep_until_next_frame(delay: float, stdin_enabled: bool) -> bool:
    deadline = monotonic() + max(delay, 0.02)
    while monotonic() < deadline:
        if _quit_requested(stdin_enabled):
            return True
        sleep(min(0.02, max(deadline - monotonic(), 0)))
    return False



def _play_frames_direct(frames: Iterable[tuple[pillow_image.Image, float]], rc: tuple[int, int]) -> tuple[int, int]:
    last_size = (1, 1)
    reserved = False
    image_id = KITTY_IMAGE_ID
    iterator = iter(frames)

    with _raw_stdin_enabled() as stdin_enabled:
        try:
            for frame, delay in iterator:
                prepared, cols, rows = _prepare_frame(frame, rc)
                if not reserved:
                    _reserve_animation_space(rows)
                    reserved = True
                last_size = (cols, rows)
                png_bytes = _encode_png_bytes(prepared)
                _tty_write("\x1b[u")
                _kitty_display_png(
                    png_bytes,
                    image_id=image_id,
                    cols=cols,
                    rows=rows,
                    width=prepared.width,
                    height=prepared.height,
                )
                if _sleep_until_next_frame(delay, stdin_enabled):
                    break
        finally:
            close = getattr(iterator, "close", None)
            if callable(close):
                close()
            if reserved:
                _finish_animation(last_size[1], image_id)

    return last_size



def animate_gif(imbytes: BytesIO, rc: tuple[int, int], loops: int = 0) -> tuple[int, int]:
    imag = pillow_image.open(imbytes)

    def frame_iter() -> Iterable[tuple[pillow_image.Image, float]]:
        if loops <= 0:
            while True:
                for frame in ImageSequence.Iterator(imag):
                    delay_ms = frame.info.get("duration", imag.info.get("duration", 100))
                    yield frame.copy(), delay_ms / 1000
        else:
            for _ in range(loops):
                for frame in ImageSequence.Iterator(imag):
                    delay_ms = frame.info.get("duration", imag.info.get("duration", 100))
                    yield frame.copy(), delay_ms / 1000

    return _play_frames_direct(frame_iter(), rc)



def _video_dimensions(path: str) -> tuple[int, int]:
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0:s=x",
            path,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    width_s, height_s = proc.stdout.strip().split("x", maxsplit=1)
    return int(width_s), int(height_s)



def play_video(path: str, rc: tuple[int, int], fps: int = 12, loops: int = 0) -> tuple[int, int]:
    width, height = _video_dimensions(path)

    def single_pass() -> Iterable[tuple[pillow_image.Image, float]]:
        frame_size = width * height * 3
        proc = subprocess.Popen(
            [
                "ffmpeg",
                "-loglevel",
                "error",
                "-stream_loop",
                "-1" if loops <= 0 else "0",
                "-i",
                path,
                "-an",
                "-vf",
                f"fps={max(fps, 1)}",
                "-f",
                "rawvideo",
                "-pix_fmt",
                "rgb24",
                "-",
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            if proc.stdout is None:
                raise RuntimeError("ffmpeg did not provide frame output")
            while True:
                data = proc.stdout.read(frame_size)
                if not data or len(data) < frame_size:
                    break
                yield pillow_image.frombytes("RGB", (width, height), data), 1 / max(fps, 1)
        finally:
            if proc.stdout is not None:
                proc.stdout.close()
            if proc.stderr is not None:
                proc.stderr.close()
            proc.wait()

    def frame_iter() -> Iterable[tuple[pillow_image.Image, float]]:
        if loops <= 0:
            yield from single_pass()
        else:
            for _ in range(loops):
                yield from single_pass()

    return _play_frames_direct(frame_iter(), rc)



def extract_video_first_frame(path: str) -> bytes:
    proc = subprocess.run(
        [
            "ffmpeg",
            "-loglevel",
            "error",
            "-i",
            path,
            "-frames:v",
            "1",
            "-f",
            "image2pipe",
            "-vcodec",
            "png",
            "-",
        ],
        check=True,
        capture_output=True,
    )
    return proc.stdout



def save_temp_media(content: bytes, suffix: str) -> str:
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix or ".bin") as handle:
        handle.write(content)
        return handle.name



def suffix_from_url(url: str) -> str:
    return Path(url.split("?", 1)[0]).suffix.lower()
