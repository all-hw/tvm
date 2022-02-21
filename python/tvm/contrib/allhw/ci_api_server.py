"""
Currently the All-Hardware CI system supports obly "batch" processing: a task is created
with a binary image and an input data file; the image is flashed and run; input data are
put into the board's UART, and output is read from that UART. The output is returned as a
part of task results and the task is destroyed.
Thus, the simplest implementation of ProjectAPIHandler interface is as follows:
- flush method stores the binary image somewhere
- open_transport method does nothing
- write_transport creates a CI task with the image stored earlier and the input data supplied.
   Subsequent calls to this method produce errors.
- read_transport requests task status. If the task is not finished, no data is returned. If it
   is finished, the task's outputis returned, and subsequent calls to this method produce errors.
- close_transport does nothing
The class has defaults for any parameters required, which can be overridden in the "options" 
parameters of the methods (including the constructor). The full list of parameters see in the
implementation of _set_options() 
"""

import base64
import json
import os
import requests
import tempfile
import time
import traceback
import typing

from tvm.micro.project_api import server

class CITransportUsageError(Exception):
    """Raised at various errors of CI transport layer usage."""

class AllHWCIAPIHandlerImpl:

    def __init__(self, options=None):
        self.url = "https://cloud.all-hw.com/ci/usertask"
        self.api_key = "85282cff-fc94-4ed1-8633-6c74637e95e0"
        self.task_timeout = 20
        self.rate = 115200
        self.log = 0
        self.options = None

        self._set_options(options)

        self.task_id = None
        self.closed = True
        self.readpos = 0
        self.readbuf = bytes()
        self.finished = False
        self.firmware = None

    def _set_options(self, options):
        if options is None:
            return

        self.options = options

        if not options.get("url") is None:
            self.url = options["url"]
        if not options.get("api_key") is None:
            self.api_key = options["api_key"]
        if not options.get("task_timeout") is None:
            self.task_timeout = options["task_timeout"]
        if not options.get("rate") is None:
            self.rate = options["rate"]
        if not options.get("log") is None:
            self.log = options["log"]

    def flash(self, options: dict):
        """Program the project onto the device.
        Parameters
        ----------
        options : Dict[str, ProjectOption]
            ProjectOption which may influence the programming process, keyed by option name.
        """
        if not self.closed:
            raise CITransportUsageError()

        # this method is called from Project API Server, which always starts in the project's folder
        self.firmware = os.getcwd() + '/build/zephyr/zephyr.hex'
#        print(f"fw={self.firmware}\n")
        self._set_options(options)
        self.readbuf = bytes()
        self.finished = False
        self.closed = True

    def open_transport(self, options: dict) -> server.TransportTimeouts:
        """Open resources needed for the transport layer.
        This function might e.g. open files or serial ports needed in write_transport or
        read_transport.
        Calling this function enables the write_transport and read_transport calls. If the
        transport is not open, this method is a no-op.
        Parameters
        ----------
        options : Dict[str, ProjectOption]
            ProjectOption which may influence the programming process, keyed by option name.
        Returns
        -------
        TransportTimeouts :
            A structure with transport layer timeouts.
        Raises
        ------
        CITransportUsageError :
            When the transport is already open.
        """
        if not self.closed:
            raise CITransportUsageError()

        self._set_options(options)
        self.readpos = 0
        self.readbuf = bytes()
        self.finished = False
        self.closed = False

        return server.TransportTimeouts(
            session_start_retry_timeout_sec=0,
            session_start_timeout_sec=0,
            session_established_timeout_sec=0,
        )

    def close_transport(self):
        """Close resources needed to operate the transport layer.
        This function might e.g. close files or serial ports needed in write_transport or
        read_transport.
        Calling this function disables the write_transport and read_transport calls. If the
        transport is not open, this method is a no-op.
        """

        self.closed = True
        self.readbuf = bytes()
        self.task_id = None         # TODO force the previous CI task to finish ???? 


    def read_transport(self, n: int, timeout_sec: typing.Union[float, type(None)]) -> bytes:
        """Read data from the transport.
        Parameters
        ----------
        n : int
            The exact number of bytes to read from the transport.
        timeout_sec : Union[float, None]
            Number of seconds to wait for at least one byte to be written before timing out. If
            timeout_sec is 0, write should attempt to service the request in a non-blocking fashion.
            If timeout_sec is None, write should block until all `n` bytes of data can be returned.
        Returns
        -------
        bytes :
            Data read from the channel. Should be exactly `n` bytes long.
        Raises
        ------
        TransportClosedError :
            When the transport layer determines that the transport can no longer send or receive
            data due to an underlying I/O problem (i.e. file descriptor closed, cable removed, etc).
        IoTimeoutError :
            When `timeout_sec` elapses without receiving any data.
        CITransportUsageError :
            When no CI task has been created earlier by calling write_transport()
        """
        """ Some corrections 
        1. timeout_sec: 0 is processed as any other float, no non-blocking stuff
        2. if CI response indicates the CI task is finished, we return just as many bytes as available
        """

        if self.closed:
            raise server.TransportClosedError()
        if self.task_id is None:
            raise CITransportUsageError()

        end_time = None if timeout_sec is None else time.monotonic() + timeout_sec
        ret = bytes()
        while True:
            if len(self.readbuf) <= self.readpos and not self.finished:    # refresh buffer content
                response = requests.get(url=self.url, params={'id':self.task_id})
#                print(response.status_code)
                if response.status_code == 200:
                    try:
                        json = response.json()
                        if json['status'] == 'finished':
                            print(json)
                            self.finished = True
                        output = json['output']
                        if not output is None:
                            self.readbuf = base64.b64decode(bytes(output, 'ascii'))
                    except Exception as e:
                        pass   # malformed response
            if len(self.readbuf) > self.readpos:    # get unread content from the buffer
                portion = self.readbuf[self.readpos : self.readpos + n - len(ret)]
                ret = ret + portion
                self.readpos += len(portion)
            if len(ret) >= n:      # got enough
                break
            if self.finished:
                if len(ret) == 0:  # we will never get any bytes
                    raise server.IoTimeoutError()
                break              # return what managed to get
            if (not end_time is None) and (end_time < time.monotonic()):
                raise server.IoTimeoutError()
            time.sleep(0.5)

        return ret[0:n] if len(ret) > n else ret

    def write_transport(self, data: bytes, timeout_sec: float):
        """Write data to the transport.
        This function should either write all bytes in `data` or raise an exception.
        Parameters
        ----------
        data : bytes
            The data to write over the channel.
        timeout_sec : Union[float, None]
            Number of seconds to wait for all bytes to be written before timing out. If timeout_sec
            is 0, write should attempt to service the request in a non-blocking fashion. If
            timeout_sec is None, write should block until it has written all data.
        Raises
        ------
        TransportClosedError :
            When the transport layer determines that the transport can no longer send or receive
            data due to an underlying I/O problem (i.e. file descriptor closed, cable removed, etc).
        IoTimeoutError :
            When `timeout_sec` elapses without receiving any data.
        """
        """ Some corrections 
        1. timeout_sec: 0 is processed as any other float, no non-blocking stuff
        """

        if self.closed or self.firmware is None:
            raise server.TransportClosedError()

        if not self.task_id is None:
            self.close_transport()
            self.open_transport(self.options)

        # data to input file
        fp = tempfile.TemporaryFile()
        fp.write(data)
        end_time = None if timeout_sec is None else time.monotonic() + timeout_sec
        while True:
            fp.seek(0)
            files = [('firmware', open(self.firmware, 'rb')), ('input', fp)]
            params = {'version':'V3', 'rate':self.rate, 'log':self.log, 
                'timeout':self.task_timeout, 'key':self.api_key, 'binary':'true'
            }
            response = requests.post(url=self.url, params=params, data=None, files=files)
#            print(response.status_code)
            if response.status_code == 200:
                self.task_id = response.text
                print(f"CI task created: {self.task_id}")
                return
            if (not end_time is None) and (end_time < time.monotonic()):
                raise server.IoTimeoutError()
            time.sleep(0.5)

