import os
import re
import urllib
from urllib.parse import urlparse
import urllib.request
import urllib.error
import itertools

import requests

USER_AGENT = "AYON-launcher"


class RemoteFileHandler:
    """Download file from url, might be GDrive shareable link"""

    @staticmethod
    def download_url(
        url,
        root,
        filename=None,
        max_redirect_hops=3,
        headers=None
    ):
        """Download a file from url and place it in root.

        Args:
            url (str): URL to download file from
            root (str): Directory to place downloaded file in
            filename (str, optional): Name to save the file under.
                If None, use the basename of the URL
            max_redirect_hops (Optional[int]): Maximum number of redirect
                hops allowed
            headers (Optional[dict[str, str]]): Additional required headers
                - Authentication etc..
        """

        root = os.path.expanduser(root)
        if not filename:
            filename = os.path.basename(url)
        fpath = os.path.join(root, filename)

        os.makedirs(root, exist_ok=True)

        # expand redirect chain if needed
        url = RemoteFileHandler._get_redirect_url(
            url, max_hops=max_redirect_hops, headers=headers)

        # check if file is located on Google Drive
        file_id = RemoteFileHandler._get_google_drive_file_id(url)
        if file_id is not None:
            return RemoteFileHandler.download_file_from_google_drive(
                file_id, root, filename)

        # download the file
        try:
            print(f"Downloading {url} to {fpath}")
            RemoteFileHandler._urlretrieve(url, fpath, headers=headers)
        except (urllib.error.URLError, IOError) as exc:
            if url[:5] != "https":
                raise exc

            url = url.replace("https:", "http:")
            print((
                "Failed download. Trying https -> http instead."
                f" Downloading {url} to {fpath}"
            ))
            RemoteFileHandler._urlretrieve(url, fpath, headers=headers)

    @staticmethod
    def download_file_from_google_drive(file_id, root, filename=None):
        """Download a Google Drive file from  and place it in root.
        Args:
            file_id (str): id of file to be downloaded
            root (str): Directory to place downloaded file in
            filename (str, optional): Name to save the file under.
                If None, use the id of the file.
        """
        # Based on https://stackoverflow.com/questions/38511444/python-download-files-from-google-drive-using-url # noqa

        url = "https://docs.google.com/uc?export=download"

        root = os.path.expanduser(root)
        if not filename:
            filename = file_id
        fpath = os.path.join(root, filename)

        os.makedirs(root, exist_ok=True)

        # TODO validate checksum of existing file and download
        #   only if incomplete.
        if os.path.isfile(fpath):
            os.remove(fpath)

        session = requests.Session()

        response = session.get(url, params={"id": file_id}, stream=True)
        token = RemoteFileHandler._get_confirm_token(response)

        if token:
            params = {"id": file_id, "confirm": token}
            response = session.get(url, params=params, stream=True)

        response_content_generator = response.iter_content(32768)
        first_chunk = None
        while not first_chunk:  # filter out keep-alive new chunks
            first_chunk = next(response_content_generator)

        if RemoteFileHandler._quota_exceeded(first_chunk):
            msg = (
                f"The daily quota of the file {filename} is exceeded and "
                f"it can't be downloaded. This is a limitation of "
                f"Google Drive and can only be overcome by trying "
                f"again later."
            )
            raise RuntimeError(msg)

        RemoteFileHandler._save_response_content(
            itertools.chain((first_chunk, ),
                            response_content_generator), fpath)
        response.close()

    @staticmethod
    def _urlretrieve(url, filename, chunk_size=None, headers=None):
        final_headers = {"User-Agent": USER_AGENT}
        if headers:
            final_headers.update(headers)

        chunk_size = chunk_size or 8192
        with open(filename, "wb") as fh:
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=final_headers)
            ) as response:
                for chunk in iter(lambda: response.read(chunk_size), ""):
                    if not chunk:
                        break
                    fh.write(chunk)

    @staticmethod
    def _get_redirect_url(url, max_hops, headers=None):
        initial_url = url
        final_headers = {"Method": "HEAD", "User-Agent": USER_AGENT}
        if headers:
            final_headers.update(headers)
        for _ in range(max_hops + 1):
            with urllib.request.urlopen(
                urllib.request.Request(url, headers=final_headers)
            ) as response:
                if response.url == url or response.url is None:
                    return url

                return response.url
        else:
            raise RecursionError(
                f"Request to {initial_url} exceeded {max_hops} redirects. "
                f"The last redirect points to {url}."
            )

    @staticmethod
    def _get_confirm_token(response):
        for key, value in response.cookies.items():
            if key.startswith("download_warning"):
                return value

        # handle antivirus warning for big zips
        found = re.search("(confirm=)([^&.+])", response.text)
        if found:
            return found.groups()[1]

        return None

    @staticmethod
    def _save_response_content(
        response_gen, destination,
    ):
        with open(destination, "wb") as f:
            for chunk in response_gen:
                if chunk:  # filter out keep-alive new chunks
                    f.write(chunk)

    @staticmethod
    def _quota_exceeded(first_chunk):
        try:
            return "Google Drive - Quota exceeded" in first_chunk.decode()
        except UnicodeDecodeError:
            return False

    @staticmethod
    def _get_google_drive_file_id(url):
        parts = urlparse(url)

        if re.match(r"(drive|docs)[.]google[.]com", parts.netloc) is None:
            return None

        match = re.match(r"/file/d/(?P<id>[^/]*)", parts.path)
        if match is None:
            return None

        return match.group("id")
