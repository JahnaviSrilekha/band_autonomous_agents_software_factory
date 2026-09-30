import os

from .server import make_server


def main():
    port = int(os.environ.get("PORT", "8080"))
    httpd = make_server(port)
    httpd.serve_forever()


if __name__ == "__main__":
    main()