import os
import threading
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, HTTPServer

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))


def get_resource_path(resource):
    return os.path.join(CURRENT_DIR, "res", resource)


class LoginServerHandler(BaseHTTPRequestHandler):
    """Login server handler."""

    def do_GET(self):
        """Override to handle requests ourselves."""
        if self.path == "/index.css":
            filepath = get_resource_path("index.css")
            with open(filepath, "rb") as stream:
                content = stream.read()
            content_type = "text/css"
        elif self.path == "/favicon.ico":
            filepath = get_resource_path("favicon.ico")
            with open(filepath, "rb") as stream:
                content = stream.read()
            content_type = "image/x-icon"
        else:
            parsed_path = urlparse(self.path)
            query = parse_qs(parsed_path.query)
            tokens = query.get("token")
            access_token = None
            if tokens:
                access_token = tokens[0]
            self.server.set_token(access_token)

            content_type = "text/html"
            if access_token:
                filepath = get_resource_path("success.html")
            else:
                filepath = get_resource_path("failed.html")
            with open(filepath, "rb") as stream:
                content = stream.read()

        # Set header with content type
        self.send_response(200)
        self.send_header("Content-type", content_type)
        self.end_headers()
        self.wfile.write(content)


class LoginHTTPServer(HTTPServer):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._token = None

    def set_token(self, token):
        self._token = token

    def get_token(self):
        return self._token


class LoginServerListener:
    def __init__(self, ayon_url):
        self._server = LoginHTTPServer(
            ("localhost", 0),
            LoginServerHandler
        )
        self._thread = threading.Thread(target=self._server.serve_forever)
        self._token = None
        self._is_running = False
        self._started = False

    @property
    def port(self):
        return self._server.server_port

    def start(self):
        if self._started:
            return
        self._started = True
        self._is_running = True
        self._thread.start()

    def get_token(self):
        return self._server.get_token()

    def stop(self):
        if not self._is_running:
            return
        self._is_running = False
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()
