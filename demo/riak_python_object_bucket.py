# riak_python_object_bucket.py
"""docstring"""

from typing import Any
import pickle
import socket

import riak


class RiakPythonObjectBucket:
    """docstring"""
    def __init__(self,
                 bucket: str,
                 host = socket.gethostbyname(socket.gethostname())) -> None:
        """docstring"""
        client = riak.RiakClient(host=host, pb_port=8087, protocol='pbc')
        self.bucket = client.bucket(bucket)
        self.bucket.set_encoder('Python object', pickle.dumps)
        self.bucket.set_decoder('Python object', pickle.loads)

    def put(self, key: str, pyobj: Any) -> None:
        """docstring"""
        self.bucket.new(key=key,
                        data=pyobj,
                        content_type='Python object').store()

    def get(self, key: str) -> Any:
        """docstring"""
        return self.bucket.get(key).data
