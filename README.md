# goonfetch
Cli rule34 fetching tool

I added an aur repo, but I can't guarantee it'll work right away `yay goonfetch`

How to use:
create `config.toml` in `~/.config/goonfetch/`

example:
```toml
# ~/.config/goonfetch/config.toml
default = "rule34" # default api supplier
# get api key from i.e. https://rule34.xxx/index.php?page=account&s=options, after making an account, keep in mind you need a different api key per supplier
tags = "-ai_generated score:>10 -beastiality -loli -rape -scat -young"
api_key = "[API_KEY]"
user_id = "[USER_ID]"
# or: auth = "api_key=[API_KEY]&user_id=[USER_ID]"
[e621]
api_key = "[API_KEY]"
login = "[USERNAME]"
# or: auth = "api_key=[API_KEY]&login=[USERNAME]"
tags = "-young -shota -loli -scat -watersports -gore score:>10"
[gelbooru]
api_key = "[API_KEY]"
user_id = "[USER_ID]"
# or: auth = "api_key=[API_KEY]&user_id=[USER_ID]"
tags = "-young -shota -loli -scat -watersports -gore score:>10"

```
Build:
```
git clone https://github.com/glacier54/goonfetch
cd goonfetch
uv sync
```

Media support:
- static images render in ascii by default
- `--no-ascii` uses kitty graphics protocol when supported (kitty, Ghostty)
- animated GIFs play inline with direct kitty graphics protocol updates
- videos (`webm`, `mp4`, etc.) play inline with direct kitty graphics protocol updates driven by `ffmpeg`
- without `--no-ascii`, GIFs fall back to a still frame and videos fall back to an ascii first-frame preview

Examples:
```
uv run main.py --no-ascii --gif-loops 2
uv run main.py --no-ascii --video-fps 12
```

Notes:
- inline video playback requires `ffmpeg` and `ffprobe` on your PATH
- if you want more videos/GIFs, do not exclude `-video`, `-webm`, or `-animated` in your tags
If you want to be able to run it as a command, create this file in `/usr/bin/goonfetch`:
```
#!/usr/bin/env bash
cd [full path to your goonfetch folder] || exit 1
poetry run python main.py "$@"
```
and run `sudo chmod +x /usr/bin/goonfetch` for execution perms.
