import json
import shlex


def parse_curl(command):
    for continuation in ("\\\n", "^\n", "`\n"):
        command = command.replace(continuation, " ")
    tokens = shlex.split(command.strip())
    if tokens and tokens[0].lower() in ("curl", "curl.exe"):
        tokens = tokens[1:]

    method, url, headers, body = None, None, [], ""
    value_flags = {
        "-X", "--request", "-H", "--header", "--url",
        "-d", "--data", "--data-raw", "--data-binary",
    }
    index = 0
    while index < len(tokens):
        token = tokens[index]
        value = tokens[index + 1] if token in value_flags and index + 1 < len(tokens) else None
        if token in ("-X", "--request") and value is not None:
            method = value.upper()
        elif token in ("-H", "--header") and value is not None:
            key, separator, header_value = value.partition(":")
            if separator:
                headers.append({"key": key.strip(), "value": header_value.strip()})
        elif token == "--url" and value is not None:
            url = value
        elif token in ("-d", "--data", "--data-raw", "--data-binary") and value is not None:
            body = value
        elif not token.startswith("-") and url is None:
            url = token
        index += 2 if value is not None else 1

    if not url:
        raise ValueError("No URL was found in the cURL command.")

    token_value = ""
    remaining_headers = []
    for header in headers:
        if header["key"].lower() == "authorization_token":
            token_value = header["value"]
        else:
            remaining_headers.append(header)

    return {
        "method": method or ("POST" if body else "GET"),
        "url": url,
        "headers": remaining_headers,
        "params": [],
        "body": body,
        "body_type": body_type_for(body),
        "token": token_value,
    }


def body_type_for(body):
    if not body:
        return "none"
    try:
        json.loads(body)
        return "json"
    except ValueError:
        return "text"
