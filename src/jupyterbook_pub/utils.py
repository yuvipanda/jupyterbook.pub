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
