import os
import threading
from urllib.parse import urlparse, parse_qs
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))


def get_resource_path(resource):
    return os.path.join(CURRENT_DIR, "res", resource)


class LoginServerHandler(BaseHTTPRequestHandler):
    """Login server handler."""

    # Browsers may open speculative (preconnect) connections which never
    #   send a request. Do not let them block a request handler forever.
    timeout = 10

    def do_GET(self):
        """Override to handle requests ourselves."""
        access_token = None
        if self.path not in ("/index.css", "/favicon.ico"):
            tokens = parse_qs(urlparse(self.path).query).get("token")
            if tokens:
                access_token = tokens[0]

        try:
            self._send_response(access_token)
        finally:
            # Store the token after the response was sent (or failed to be
            #   sent), the login window may close the server right after it
            #   receives the token.
            # Never clear an already received token, browsers can send
            #   additional requests (e.g. icons or repeated page loads).
            if access_token:
                self.server.set_token(access_token)

    def _send_response(self, access_token):
        if self.path == "/index.css":
            filepath = get_resource_path("index.css")
            content_type = "text/css"
        elif self.path == "/favicon.ico":
            filepath = get_resource_path("favicon.ico")
            content_type = "image/x-icon"
        else:
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
        self.wfile.flush()

    def log_message(self, *args, **kwargs):
        # Callback URLs contain access tokens; never write them to stderr.
        pass


class LoginHTTPServer(ThreadingHTTPServer):
    # Handle each connection in its own thread, an idle connection kept
    #   open by the browser must not block the callback request.
    daemon_threads = True
    block_on_close = False

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
        # Daemon thread so a not yet stopped server never keeps the process
        #   alive (stop is called asynchronously by the login window).
        self._thread = threading.Thread(
            target=self._server.serve_forever, daemon=True
        )
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
