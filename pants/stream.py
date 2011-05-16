###############################################################################
#
# Copyright 2011 Chris Davis
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
###############################################################################

###############################################################################
# Imports
###############################################################################

import socket

from pants.channel import Channel
from pants.engine import Engine


###############################################################################
# Logging
###############################################################################

import logging
log = logging.getLogger("pants")


###############################################################################
# Stream Class
###############################################################################

class Stream(Channel):
    """
    A TCP stream channel class.
    
    ==========  ============
    Arguments   Description
    ==========  ============
    kwargs      Keyword arguments to be passed through to :obj:`Channel`
    ==========  ============
    """
    def __init__(self, **kwargs):
        if "type" not in kwargs:
            kwargs["type"] = socket.SOCK_STREAM
        
        Channel.__init__(self, **kwargs)
        
        # I/O attributes
        self.read_delimiter = None
        self._recv_buffer = ""
        self._send_buffer = ""
        
        # Internal state
        self._connected = False
        self._connecting = False
        self._listening = False
    
    ##### Status Methods ######################################################
    
    def active(self):
        """
        Check if the channel is active - either connected or listening.
        
        Returns True if the channel is active, False otherwise.
        """
        return self._socket is not None and (self._listening or
                self._connected or self._connecting)
    
    def connected(self):
        """
        Check if the channel is connected or connecting to a remote socket.
        
        Returns True if the channel is connected, False otherwise.
        """
        return self._connected or self._connecting
    
    def listening(self):
        """
        Check if the channel is listening for connections.
        
        Returns True if the channel is listening, False otherwise.
        """
        return self._listening
    
    ##### Control Methods #####################################################
    
    def connect(self, host, port):
        """
        Connect the channel to a remote socket.
        
        Returns the channel.
        
        ==========  ============
        Arguments   Description
        ==========  ============
        host        The remote host to connect to.
        port        The port to connect on.
        ==========  ============
        """
        if self.active():
            raise RuntimeError("connect() called on active %s #%d."
                    % (self.__class__.__name__, self.fileno))
        
        if self.closed():
            raise RuntimeError("connect() called on closed %s."
                    % self.__class__.__name__)
        
        self._connecting = True
        
        try:
            connected = self._socket_connect((host, port))
        except socket.error, err:    
            # TODO Raise exception here?
            log.exception("Exception raised in connect() on %s #%d." %
                    (self.__class__.__name__, self.fileno))
            # TODO Close this Stream here?
            self.close()
            return self
        
        if connected:
            self._handle_connect_event()
        
        return self
    
    def listen(self, port=8080, host='', backlog=1024):
        """
        Begin listening for connections made to the channel.
        
        Returns the channel.
        
        ==========  ============
        Arguments   Description
        ==========  ============
        port        *Optional.* The port to listen for connections on. By default, is 8080.
        host        *Optional.* The local host to bind to. By default, is ''.
        backlog     *Optional.* The size of the connection queue. By default, is 1024.
        ==========  ============
        """
        if self.active():
            raise RuntimeError("listen() called on active %s #%d."
                    % (self.__class__.__name__, self.fileno))
        
        if self.closed():
            raise RuntimeError("listen() called on closed %s."
                    % self.__class__.__name__)
        
        try:
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except AttributeError:
            pass
        
        try:
            self._socket_bind((host, port))
            self._socket_listen(backlog)
        except socket.error, err:    
            # TODO Raise exception here?
            log.exception("Exception raised in listen() on %s #%d." %
                    (self.__class__.__name__, self.fileno))
            # TODO Close this Stream here?
            self.close()
            return self
        
        self._listening = True
        self._update_addr()
        
        return self
    
    def close(self):
        """
        Close the channel.
        """
        if self.closed():
            return
        
        self.read_delimiter = None
        self._recv_buffer = ""
        self._send_buffer = ""
        self._connected = False
        self._connecting = False
        self._listening = False
        self._update_addr()
        
        Channel.close(self)
    
    ##### I/O Methods #########################################################
    
    def write(self, data, buffer_data=False):
        """
        Overridable wrapper for :meth:`_send`.
        """
        self._send(data, buffer_data)
    
    def _send(self, data, buffer_data):
        """
        Send data over the channel.
        
        ============  ============
        Arguments     Description
        ============  ============
        data          A string of data to send over the channel.
        buffer_data   If True, the data will be buffered and sent later.
        ============  ============
        """
        if self._socket is None:
            log.warning("Attempted to write to closed %s #%d." %
                    (self.__class__.__name__, self.fileno))
            return
        
        if not self._connected:
            log.warning("Attempted to write to disconnected %s #%d." %
                    (self.__class__.__name__, self.fileno))
            return
        
        if buffer_data or self._send_buffer:
            self._send_buffer += data
            # NOTE _wait_for_write_event is normally set by _socket_send()
            #      when no more data can be sent. We set it here because
            #      _socket_send() will not be called.
            self._wait_for_write_event = True
            return
        
        try:
            bytes_sent = self._socket_send(data)
        except socket.error, err:
            # TODO Raise an exception here?
            log.exception("Exception raised in write() on %s #%d." %
                    (self.__class__.__name__, self.fileno))
            # TODO Close this Stream here?
            self.close()
            return
        
        if len(data[bytes_sent:]) > 0:
            self._send_buffer += data[bytes_sent:]
        else:
            self._safely_call(self.on_write)
    
    ##### Internal Methods ####################################################
    
    def _update_addr(self):
        """
        Update the channel's attr:`remote_addr` and attr:`local_addr`
        attributes.
        """
        if self._connected:
            self.remote_addr = self._socket.getpeername()
            self.local_addr = self._socket.getsockname()
        elif self._listening:  
            self.remote_addr = (None, None)
            self.local_addr = self._socket.getsockname()
        else:
            self.remote_addr = (None, None)
            self.local_addr = (None, None)
    
    ##### Internal Event Handler Methods ######################################
    
    def _handle_read_event(self):
        """
        Handle a read event raised on the channel.
        """
        if self._listening:
            self._handle_accept_event()
            return
        
        while True:
            try:
                data = self._socket_recv()
            except socket.error, err:
                log.exception("Exception raised by recv() on %s #%d." %
                        (self.__class__.__name__, self.fileno))
                # TODO Close this Stream here?
                self.close()
                return
            
            if not data:
                break
            
            self._recv_buffer += data
        
        self._process_recv_buffer()
    
    def _handle_write_event(self):
        """
        Handle a write event raised on the channel.
        """
        if self._listening:
            log.warning("Received write event for listening %s #%d." %
                    (self.__class__.__name__, self.fileno))
            return
        
        if not self._connected:
            self._handle_connect_event()
        
        if not self._send_buffer:
            return
        
        try:
            bytes_sent = self._socket_send(self._send_buffer)
        except socket.error, err:
            log.exception("Exception raised by send() on %s #%s." %
                    (self.__class__.__name__, self.fileno))
            # TODO Close this Stream here?
            self.close()
            return
        self._send_buffer = self._send_buffer[bytes_sent:]
        
        if not self._send_buffer:
            self._safely_call(self.on_write)
    
    def _handle_accept_event(self):
        """
        Handle an accept event raised on the channel.
        """
        while True:
            try:
                sock, addr = self._socket_accept()
            except socket.error, err:
                log.exception("Exception raised by accept() on %s #%d." %
                        (self.__class__.__name__, self.fileno))
                try:
                    sock.close()
                except socket.error, err:
                    pass
                # TODO Close this Stream here?
                return
            
            if sock is None:
                return
            
            self._safely_call(self.on_accept, sock, addr)
    
    def _handle_connect_event(self):
        """
        Handle a connect event raised on the channel.
        """
        err, srrstr = self._get_socket_error()
        if err != 0:
            raise socket.error(err, errstr)
        
        self._connected = True
        self._connecting = False
        self._update_addr()
        self._safely_call(self.on_connect)
    
    ##### Internal Processing Methods #########################################    
    
    def _process_recv_buffer(self):
        """
        Process the :attr:`_recv_buffer`, passing chunks of data to
        :meth:`on_read`.
        """
        while self._recv_buffer:
            delimiter = self.read_delimiter
            
            if delimiter is None:
                data = self._recv_buffer
                self._recv_buffer = ""
                self._safely_call(self.on_read, data)
            
            elif isinstance(delimiter, (int, long)):
                if len(self._recv_buffer) < delimiter:
                    break
                data = self._recv_buffer[:delimiter]
                self._recv_buffer = self._recv_buffer[delimiter:]
                self._safely_call(self.on_read, data)
            
            elif isinstance(delimiter, basestring):
                mark = self._recv_buffer.find(delimiter)
                if mark == -1:
                    break
                data = self._recv_buffer[:mark]
                self._recv_buffer = self._recv_buffer[mark+len(delimiter):]
                self._safely_call(self.on_read, data)
            
            else:
                log.warning("Invalid read_delimiter on %s #%d." %
                        (self.__class__.__name__, self.fileno))
                break
            
            if self._socket is None or not self._connected:
                break
