#!/usr/bin/env python
from __future__ import annotations

import argparse
import base64
from collections.abc import Mapping
from dataclasses import dataclass
from io import BytesIO
import os
from pathlib import Path
import random
import shutil
import tomllib
import urllib.parse

import requests

from to_ascii import main as to_ascii
from to_kitty import (
    animate_gif,
    extract_video_first_frame,
    graphics_supported,
    play_video,
    print_kitty,
    save_temp_media,
    suffix_from_url,
)


def b64(s: str) -> str:
    return base64.b64encode(s.encode("ascii")).decode("ascii")


# https://github.com/ClaustAI/r34-api/blob/main/app.py
def ellips(s, mx):
    if len(s) > mx:
        return s[: mx - 3] + '...'
    return s


@dataclass
class ReturnObject:
    lowres_url: str
    highres_url: str
    page_url: str
    author: str
    tags: str
    score: str
    media_type: str = "image"
    file_ext: str = ""


LIMIT = 100
STATIC_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
GIF_EXTS = {".gif"}
VIDEO_EXTS = {".webm", ".mp4", ".mov", ".mkv", ".avi", ".m4v"}


class MediaPlaybackError(RuntimeError):
    pass



def raise_reqfail(resp, **text):
    if 'info' not in text:
        text['info'] = "API call returned unexpected response"
    text['statuscode'] = resp.status_code
    text['response'] = resp.text[:300]
    text['url_used'] = resp.url
    print(text)
    raise RuntimeError(text['info'] + " (see console output above error)")



def get(url, params):
    resp = requests.get(url, params=params, headers={"User-Agent": "goonfetch/0.1.x"})
    if resp.status_code != 200:
        raise_reqfail(resp)
    if resp.text == '':
        raise_reqfail(resp, info="No posts found from criteria.")
    try:
        dat = resp.json()
    except requests.exceptions.JSONDecodeError:
        raise_reqfail(resp, info="Response was not in JSON format.")
    if not dat:
        raise_reqfail(resp, info="No posts found from criteria.")
    return dat



def infer_media_type(url: str) -> tuple[str, str]:
    ext = suffix_from_url(url)
    if ext in GIF_EXTS:
        return "gif", ext
    if ext in VIDEO_EXTS:
        return "video", ext
    if ext in STATIC_EXTS:
        return "image", ext
    return "image", ext



def make_return_object(*, lowres_url: str, highres_url: str, page_url: str, author: str, tags: str, score: str) -> ReturnObject:
    media_type, file_ext = infer_media_type(highres_url)
    return ReturnObject(
        lowres_url=lowres_url,
        highres_url=highres_url,
        page_url=page_url,
        author=author,
        tags=tags,
        score=str(score),
        media_type=media_type,
        file_ext=file_ext,
    )



def get_booru(base, parms):
    parms['page'] = 'dapi'
    parms['s'] = 'post'
    parms['q'] = 'index'
    parms['limit'] = LIMIT
    parms['pid'] = 1
    parms['json'] = 1
    data = get(base, parms)
    posts = data["post"] if isinstance(data, dict) and "post" in data else data
    if not posts:
        raise RuntimeError("No posts returned (check tags/auth).")
    if not isinstance(posts, list):
        print(posts)
        raise RuntimeError(f"Unexpected format (check tags/auth): {posts}")
    req = random.choice(posts)
    return make_return_object(
        lowres_url=req['preview_url'],
        highres_url=req['file_url'],
        page_url=f"https://{urllib.parse.urlparse(base).netloc}/index.php?page=post&s=view&id={req['id']}",
        author=req.get('owner', 'unknown'),
        tags=req.get('tags', ''),
        score=req.get('score', '0'),
    )



def get_e621(parms):
    parms['limit'] = LIMIT
    base_url = "https://e621.net/posts.json/"
    resp = get(base_url, parms)['posts']
    if not resp:
        raise RuntimeError("No posts found.")
    req = random.choice(resp)
    file_url = req["file"]["url"]
    return make_return_object(
        lowres_url=req["preview"]["url"],
        highres_url=file_url,
        page_url=f"https://e621.net/posts/{req['id']}",
        author=' '.join(req["tags"]["artist"]),
        tags=' '.join(req["tags"]["general"] + req["tags"]["character"] + req["tags"]["species"]),
        score=req["score"]["total"],
    )



def download(url: str) -> bytes:
    resp = requests.get(url, headers={"User-Agent": "goonfetch/0.1.x"})
    resp.raise_for_status()
    return resp.content



def download_to_file(url: str, suffix: str) -> str:
    resp = requests.get(url, headers={"User-Agent": "goonfetch/0.1.x"}, stream=True)
    resp.raise_for_status()
    temp_path = save_temp_media(b"", suffix)
    with open(temp_path, 'wb') as handle:
        for chunk in resp.iter_content(chunk_size=1024 * 128):
            if chunk:
                handle.write(chunk)
    return temp_path



def render(ro: ReturnObject, ma, no_ascii: bool, gif_loops: int, video_fps: int, video_loops: int):
    if ro.media_type == "image":
        img_bytes = download(ro.highres_url)
        if not no_ascii:
            return to_ascii(BytesIO(img_bytes), (int(ma[0]), int(ma[1] - 4)))
        if graphics_supported():
            return print_kitty(BytesIO(img_bytes), (int(ma[0] + 3), int(ma[1] - 4)))
        return to_ascii(BytesIO(img_bytes), (int(ma[0]), int(ma[1] - 4)), use_bg=True)

    if ro.media_type == "gif":
        gif_bytes = download(ro.highres_url)
        if no_ascii and graphics_supported():
            return animate_gif(BytesIO(gif_bytes), (int(ma[0] + 3), int(ma[1] - 4)), loops=gif_loops)
        return to_ascii(BytesIO(gif_bytes), (int(ma[0]), int(ma[1] - 4)))

    if ro.media_type == "video":
        temp_path = download_to_file(ro.highres_url, ro.file_ext)
        try:
            if no_ascii and graphics_supported():
                return play_video(temp_path, (int(ma[0] + 3), int(ma[1] - 4)), fps=video_fps, loops=video_loops)
            frame_bytes = extract_video_first_frame(temp_path)
            return to_ascii(BytesIO(frame_bytes), (int(ma[0]), int(ma[1] - 4)))
        except FileNotFoundError as exc:
            raise MediaPlaybackError(
                "Video playback requires ffmpeg/ffprobe to be installed and available on PATH."
            ) from exc
        finally:
            Path(temp_path).unlink(missing_ok=True)

    raise MediaPlaybackError(f"Unsupported media type: {ro.media_type}")



def config_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "goonfetch" / "config.toml"



def mode_config(cfg: dict, source: str) -> dict | None:
    if source == "rule34":
        rule34 = cfg.get("rule34")
        if isinstance(rule34, Mapping):
            return dict(rule34)

        top_level = {
            key: value
            for key, value in cfg.items()
            if key not in {"default", "e621", "gelbooru", "rule34"} and not isinstance(value, Mapping)
        }
        return top_level or None

    conf = cfg.get(source)
    if isinstance(conf, Mapping):
        return dict(conf)
    return None



def has_auth(conf: dict, source: str) -> bool:
    if conf.get("auth"):
        return True
    if source == "e621":
        return bool(conf.get("api_key") and conf.get("login"))
    return bool(conf.get("api_key") and conf.get("user_id"))



def confparse():
    size = shutil.get_terminal_size(fallback=(60, 24))
    path = config_path()
    if not path.exists():
        raise FileNotFoundError(
            f"No configuration file found at {path}. Create ~/.config/goonfetch/config.toml."
        )

    cfg = tomllib.loads(path.read_text())
    parser = argparse.ArgumentParser(
        description="A rule34 fetching tool. Requires a config.toml to exist. For more information go to https://github.com/glacier54/goonfetch"
    )
    parser.add_argument('--max-columns', '-c', type=int, default=size.columns, help='Max character columns. Defaults to terminal width.')
    parser.add_argument('--max-rows', '-r', type=int, default=size.lines - 7, help='Max character rows. Defaults to terminal height.')
    parser.add_argument('--no-ascii', action='store_true', required=False, help='Use kitty graphics/pixel output when available. Required for animated GIFs and inline video playback.')
    parser.add_argument('--gif-loops', type=int, default=0, help='How many times to loop animated GIFs in graphics mode. 0 loops forever, default: 0.')
    parser.add_argument('--video-fps', type=int, default=12, help='Max FPS for inline video playback in graphics mode, default: 12.')
    parser.add_argument('--video-loops', type=int, default=0, help='How many times to loop videos in graphics mode. 0 loops forever, default: 0.')
    parser.add_argument('--mode', choices=["rule34", "e621", "gelbooru"], default=cfg.get("default", "rule34"), help='Set API provider.')
    parser.add_argument('additional_tags', nargs='*', help="Add rule34 tags.")
    args = parser.parse_args()

    if not isinstance(args.mode, str):
        raise ValueError("Invalid 'default' value in config.toml. Expected one of: rule34, e621, gelbooru.")

    conf = mode_config(cfg, args.mode)
    return conf, args



def print_post(data: ReturnObject, ma, no_ascii: bool, gif_loops: int, video_fps: int, video_loops: int):
    w, h = render(data, ma, no_ascii, gif_loops, video_fps, video_loops)
    print(data.page_url)
    print(data.author)
    print(ellips(data.tags, w + 3))
    print(f"score: {data.score}")
    if data.media_type != "image":
        print(f"media: {data.media_type}{data.file_ext}")


if __name__ == '__main__':
    conf, args = confparse()
    if not conf:
        raise ValueError(f"No config found for mode '{args.mode}' in ~/.config/goonfetch/config.toml.")
    if not has_auth(conf, args.mode):
        raise ValueError("No auth found. You can create an api-key and find your user id/username in the mode's user settings page.")
    if conf.get('auth'):
        conf.update({key: values[0] for key, values in urllib.parse.parse_qs(conf['auth']).items()})
        conf.pop("auth", None)
    tags = conf.get("tags", "")
    if args.additional_tags:
        conf['tags'] = (tags + " " + " ".join(args.additional_tags)).strip()

    match args.mode:
        case 'rule34':
            data = get_booru('https://rule34.xxx/index.php', conf)
        case 'e621':
            data = get_e621(conf)
        case 'gelbooru':
            data = get_booru('https://gelbooru.com/index.php', conf)

    print_post(data, (args.max_columns, args.max_rows + 4), args.no_ascii, args.gif_loops, args.video_fps, args.video_loops)
