import requests
from indigo.drivers.base import StorageDriver

class FileSystemDriver(StorageDriver):

    chunk_size = 1024 * 1024 * 1

    def chunk_content(self):
        """
        Yields the content for the driver's URL, if any
        a chunk at a time.  The value yielded is the size of
        the chunk and the content chunk itself.

        The data for this file is most likely to come from
        an agent that is configured to serve the data - this
        comes from the IP address specified in the URL.
        """
        parts = self.url.split('/')
        ip = parts[0]

        source = "http://{}:9000/get/{}".format(ip, '/'.join(parts[1:]))

        r = requests.get(source, stream=True)
        for chunk in r.iter_content(chunk_size=1024):
            if chunk:
                yield chunk
