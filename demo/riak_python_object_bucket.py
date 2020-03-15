# riak_python_object_bucket.py
"""Provides abstraction of Riak bucket storing arbitrary Python objects."""

from typing import Any
import pickle
import socket

import riak


class RiakPythonObjectBucket:
    """Abstraction of Riak bucket storing arbitrary Python objects.

    Attributes:
        bucket: A string naming the bucket.
    """

    def __init__(self,
                 bucket: str,
                 host=socket.gethostbyname(socket.gethostname())) -> None:
        """Initializes RiaKPythonObjectBucket and sets encoder and decoder.

        Args:
            bucket: A string naming the bucket to be initialized.
            host: A string representation of the host's public IP address.
        """
        client = riak.RiakClient(host=host, pb_port=8087, protocol='pbc')
        self.bucket = client.bucket(bucket)
        self.bucket.set_encoder('Python object', pickle.dumps)
        self.bucket.set_decoder('Python object', pickle.loads)

    def put(self, key: str, pyobj: Any) -> None:
        """Sets given pyobject as value of given key."""
        self.bucket.new(key=key,
                        data=pyobj,
                        content_type='Python object').store()

    def get(self, key: str) -> Any:
        """Retrieves value of given key."""
        return self.bucket.get(key).data
