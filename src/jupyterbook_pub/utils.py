import socket


def random_port():
    """
    Get a single random port likely to be available for listening in.
    """
    sock = socket.socket()
    sock.bind(("", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def url_path_join(*pieces):
    """Join components of url into a relative url.

    Use to prevent double slash when joining subpath. This will leave the
    initial and final / in place.
    Empty trailing items are ignored.

    Based on `notebook.utils.url_path_join`.

    Vendored from https://github.com/jupyterhub/jupyterhub/blob/main/jupyterhub/utils.py
    """
    pieces = list(pieces)
    while pieces and not pieces[-1]:
        del pieces[-1]
    if not pieces:
        return ""
    initial = pieces[0].startswith("/")
    final = pieces[-1].endswith("/")
    stripped = [s.strip("/") for s in pieces]
    result = "/".join(s for s in stripped if s)

    if initial:
        result = "/" + result
    if final:
        result = result + "/"
    if result == "//":
        result = "/"

    return result
