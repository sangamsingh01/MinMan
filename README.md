# MinMan

A tiny API client that runs locally in your browser. Build and send HTTP requests, organise them in folders, and keep everything as plain JSON files on your own computer. No account, no cloud.

## Install

```
pip install minman
```

Requires Python 3.10+.

## Run

```
minman
```

If `minman` is not found (Python's Scripts folder is not on PATH), run:

```
python -m minman
```

Your browser opens http://127.0.0.1:3326. Stop it with `Ctrl+C`.

Options:
- `--port 5050`: use another port
- `--no-browser`: don't open the browser
- `--logs` / `--no-logs`: show or hide request logs in the terminal (off by default)
- `--data-dir <path>`: where your data is kept (default `~/.minman`, or set `MINMAN_HOME`)
- `--version`: show the version

Example:

```
minman --port 5050 --no-browser
```

## Features

- **Requests**: GET, POST, PUT, PATCH, DELETE with Params, Headers, Auth and Body tabs. Untick a row to keep it but not send it. Params and Headers also have a Raw mode.
- **Collections**: nested folders in the sidebar. Hover an item to duplicate (⧉), rename (✎), move (⇄) or delete (×). Use the search box to filter.
- **Auth**: Token box (default), Bearer, Basic or API key (header or query).
- **Body**: None, JSON, Text, URL-encoded or Form-data with file upload.
- **Environments**: reusable `{{name}}` variables (e.g. `{{base_url}}`) in several environments such as Dev and Prod. Switch between them in the top bar.
- **Token box**: shows when a JWT expires; the eye button shows or hides it. The token stays in your browser and is never written to disk.
- **cURL**: **Import cURL** fills a request from a command; **Export cURL** gives a command to copy or download.
- **Responses**: status, time and size. **Pretty** shows JSON as a collapsible tree, **Raw** shows plain text, **Preview** renders HTML or images, and search highlights matches.
- **Saved versions**: **Save response** stores numbered versions (`_v1`, `_v2`, ...) that you can reopen later.
- **Shortcuts**: `Ctrl+Enter` sends, `Ctrl+S` saves, `Esc` cancels. A ● marks unsaved changes.
- Dark and light themes, resizable panes.
- **About** (ⓘ in the top bar): version, developer, source link and data folder.

## Your data

Everything is stored in `~/.minman`:
- `collections/`: saved requests
- `responses/`: saved response versions
- `variables.json`: environments

MinMan only listens on `127.0.0.1`, so it cannot be reached from other computers.

## Development

```
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -e ".[test]"
pytest
```