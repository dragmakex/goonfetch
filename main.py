#!/usr/bin/env python
from to_ascii import main as to_ascii
from to_kitty import print_kitty as to_kitty
import requests
import random
import shutil
import os, tomllib, PIL
from io import BytesIO
from pathlib import Path
from platformdirs import user_config_dir
import argparse
import base64
import urllib.parse
from dataclasses import dataclass
from collections.abc import Mapping


def b64(s: str) -> str:
    return base64.b64encode(s.encode("ascii")).decode("ascii")

# https://github.com/ClaustAI/r34-api/blob/main/app.py
def ellips(s, mx):
    if len(s) > mx:
        return s[:mx-3]+'...'
    return s

@dataclass
class ReturnObject:
    lowres_url: str
    highres_url: str
    page_url: str
    author: str
    tags: str
    score: str
LIMIT = 100

def raise_reqfail(resp, **text):
    if not 'info' in text:
        text['info']="API call returned unexpected response"
    text['statuscode'] = resp.status_code
    text['response'] = resp.text[:300]
    text['url_used'] = resp.url        # super useful
    print(text)
    raise RuntimeError(text['info']+" (see console output above error)")

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

def get_booru(base, parms):
    parms['page'] = 'dapi'
    parms['s'] = 'post'
    parms['q'] = 'index'
    parms['limit'] = LIMIT
    parms['pid'] = 1
    parms['json'] = 1
    url = base
    data = get(url, parms)
    posts = data["post"] if isinstance(data, dict) and "post" in data else data
    if not posts:
        raise RuntimeError("No posts returned (check tags/auth).")
    if not isinstance(posts, list):
        print(posts)
        raise RuntimeError(f"Unexpected format (check tags/auth): {posts}")
    req = random.choice(posts)
    ret = ReturnObject(
        lowres_url=req['preview_url'],
        highres_url=req['file_url'],
        page_url=f"https://{urllib.parse.urlparse(base).netloc}/index.php?page=post&s=view&id={req['id']}",
        author=req['owner'],
        tags=req['tags'],
        score=req['score']

    )
    return ret

def get_e621(parms):
    parms['limit'] = LIMIT
    base_url = "https://e621.net/posts.json/"
    resp = get(base_url, parms)['posts']
    if not resp:
        raise RuntimeError("No posts found.")
    req = random.choice(resp)
    ret = ReturnObject(
        lowres_url=req["preview"]["url"],
        highres_url=req["file"]["url"],
        page_url=f"https://e621.net/posts/{req["id"]}",
        author=' '.join(req["tags"]["artist"]),
        tags=" ".join(req["tags"]["general"] + req["tags"]["character"] + req["tags"]["species"]),
        score=req["score"]["total"]
    )
    return ret
def render(ro, ma, no_ascii):
    img_bytes = requests.get(ro.highres_url).content
    if not no_ascii:
        return to_ascii(BytesIO(img_bytes), (int(ma[0]), int(ma[1]-4)))
    if "KITTY_WINDOW_ID" in os.environ:
        w, h = to_kitty(BytesIO(img_bytes), (int(ma[0]+3), int(ma[1]-4)))
    else:
        w, h = to_ascii(BytesIO(img_bytes), (int(ma[0]), int(ma[1]-4)), use_bg=True)
    return w,h

def config_path() -> Path:
    base = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
    return base / "goonfetch" / "config.toml"


def mode_config(cfg: dict, source: str) -> dict | None:
    if source == "rule34":
        rule34 = cfg.get("rule34")
        if isinstance(rule34, Mapping):
            return dict(rule34)

        # Support the README format where the default provider lives at top level.
        top_level = {
            key: value for key, value in cfg.items()
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
    parser = argparse.ArgumentParser(description=f"A rule34 fetching tool. Requires a config.toml to exist. For more information go to https://github.com/glacier54/goonfetch")
    parser.add_argument('--max-columns', '-c', type=int, default=size.columns, help='Max character columns. Defaults to terminal width.')
    parser.add_argument('--max-rows', '-r', type=int, default=size.lines-7, help='Max character rows. Defaults to terminal height.')
    parser.add_argument('--no-ascii', action='store_true', required=False, help='Use either kitty image protocol (when available) or a pixelated image instead of ascii.')
    parser.add_argument('--mode', choices=["rule34", "e621", "gelbooru"], default=cfg.get("default", "rule34"), help='Set API provider.')
    parser.add_argument('additional_tags', nargs='*', help="Add rule34 tags.")
    args = parser.parse_args()

    if not isinstance(args.mode, str):
        raise ValueError("Invalid 'default' value in config.toml. Expected one of: rule34, e621, gelbooru.")

    source = args.mode
    conf = mode_config(cfg, source)
    return conf, args

def main(data, ma, protocol):
    w,h = render(data, ma, protocol)
    print(data.page_url)
    print(data.author)
    print(ellips(data.tags, w+3))
    print(f"score: {data.score}")
if __name__ == '__main__':
    conf, args = confparse()
    if not conf:
        raise ValueError(f"No config found for mode '{args.mode}' in ~/.config/goonfetch/config.toml.")
    if not has_auth(conf, args.mode):
        raise ValueError("No auth found. You can create an api-key and find your user id/username in the mode's user settings page.")
    if conf.get('auth'):
        conf.update(urllib.parse.parse_qs(conf['auth']))
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

    main(data, (args.max_columns, args.max_rows+4), args.no_ascii)
