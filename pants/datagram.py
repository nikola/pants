###############################################################################
#
# Copyright 2011 Stendec <stendec365@gmail.com>
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
# Datagram Class
###############################################################################

class Datagram(Channel):
    def __init__(self, **kwargs):
        if kwargs.setdefault("type", socket.SOCK_DGRAM) != socket.SOCK_DGRAM:
            raise TypeError("Cannot create a %s with a type other than SOCK_DGRAM."
                    % self.__class__.__name__)
        
        Channel.__init__(self, **kwargs)
        
        # Socket
        self.remote_addr = (None, None)
        self.local_addr = (None, None)
        
        # I/O attributes
        self.read_delimiter = None
        self._recv_buffer = {}
        self._send_buffer = []
        
        # Internal state
        self.active = False
        self.listening = False
    
    ##### Control Methods #####################################################
    
    def listen(self, port=8080, host=''):  
        """
        Begin listening for packets sent to the channel.
        
        Returns the channel.
        
        ==========  ============
        Arguments   Description
        ==========  ============
        port        *Optional.* The port to listen for packets on. By default, is 8080.
        host        *Optional.* The local host to bind to. By default, is ''.
        ==========  ============
        """
        if self.active:
            raise RuntimeError("listen() called on active %s #%d."
                    % (self.__class__.__name__, self.fileno))
        
        if self._socket is None:
            raise RuntimeError("listen() called on closed %s."
                    % self.__class__.__name__)
        
        try:
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        except AttributeError:
            pass
        
        try:
            self._socket_bind((host, port))
        except socket.error, err:
            self.close()
            raise
        
        self.active = True
        self.listening = True
        self._update_addr()
        
        return self
    
    def close(self):
        """
        Close the channel.
        """
        if self._socket is None:
            return
        
        self.read_delimiter = None
        self._recv_buffer = {}
        self._send_buffer = []
        self.active = False
        self.listening = False
        self._update_addr()
        
        Channel.close(self)
    
    ##### I/O Methods #########################################################
    
    def write(self, data, addr=None, buffer_data=False):
        """
        Write data to the channel.
        
        ============  ============
        Arguments     Description
        ============  ============
        data          A string of data to write to the channel.
        addr          The remote address to write the data to.
        buffer_data   If True, the data will be buffered and written later.
        ============  ============
        """
        if self._socket is None:
            log.warning("Attempted to write to closed %s #%d." %
                    (self.__class__.__name__, self.fileno))
            return
        
        if addr is None:
            addr = self.remote_addr
            if addr[0] is None:
                log.warning("Attempted to write to %s #%d with no remote address." %
                        (self.__class__.__name__, self.fileno))
                return
        
        self.active = True
        self._send_buffer.append((data, addr))
        if not buffer_data:
            self._process_send_buffer()
    
    ##### Private Methods #####################################################
    
    def _update_addr(self):
        """
        Update the channel's :attr:`local_addr` attribute.
        """
        if self.listening:
            self.local_addr = self._socket.getsockname()
        else:
            self.local_addr = (None, None)
    
    ##### Internal Event Handler Methods ######################################
    
    def _handle_read_event(self):
        """
        Handle a read event raised on the channel.
        """
        if self._socket is None:
            log.warning("Received read event for closed %s #%d." %
                    (self.__class__.__name__, self.fileno))
            return
        
        if not self.listening:
            log.warning("Received read event for non-listening %s #%d." %
                    (self.__class__.__name__, self.fileno))
            return
        
        while True:
            try:
                data, addr = self._socket_recvfrom()
            except socket.error, err:
                log.exception("Exception raised by recvfrom() on %s #%d." %
                        (self.__class__.__name__, self.fileno))
                # TODO Close this Datagram here?
                self.close()
                return
            
            if not data:
                break
            
            self._recv_buffer[addr] = self._recv_buffer.get(addr, '') + data
        
        self._process_recv_buffer()
    
    def _handle_write_event(self):
        """
        Handle a write event raised on the channel.
        """
        if self._socket is None:
            log.warning("Received write event for closed %s #%d." %
                    (self.__class__.__name__, self.fileno))
            return
        
        self._process_send_buffer()
    
    ##### Internal Processing Methods #########################################
    
    def _process_recv_buffer(self):
        """
        Process the :attr:`_recv_buffer`, passing chunks of data to
        :meth:`on_read`.
        """
        for addr in self._recv_buffer.keys()[:]:
            buf = self._recv_buffer[addr]
            self.remote_addr = addr
            
            while buf:
                delimiter = self.read_delimiter
                
                if delimiter is None:
                    self._safely_call(self.on_read, buf)
                    buf = ""
                
                elif isinstance(delimiter, (int, long)):
                    if len(buf) < delimiter:
                        break
                    data = buf[:delimiter]
                    buf = buf[delimiter:]
                    self._safely_call(self.on_read, data)
                
                elif isinstance(delimiter, basestring):
                    mark = buf.find(delimiter)
                    if mark == -1:
                        break
                    data = buf[:mark]
                    buf = buf[mark+len(delimiter):]
                    self._safely_call(self.on_read, data)
                
                else:
                    log.warning("Invalid read_delimiter on %s #%d." %
                            (self.__class__.__name__, self.fileno))
                    break
                
                if not self.active:
                    break
            
            self.remote_addr = (None, None)
            
            if buf:
                self._recv_buffer[addr] = buf
            else:
                del self._recv_buffer[addr]
            
            if not self.active:
                break
    
    def _process_send_buffer(self):
        while self._send_buffer:
            data, addr = self._send_buffer.pop(0)
            
            while data:
                bytes_sent = self._socket_sendto(data, addr)
                if bytes_sent == 0:
                    break
                data = data[bytes_sent:]
            
            if data:
                self._send_buffer.insert(0, (data, addr))
                break
        
        if not self._send_buffer:
            self.active = False
            self._safely_call(self.on_write)


###############################################################################
# sendto Function
###############################################################################

_datagram = None

def sendto(data, host, port):
    """
    Send a packet to a remote socket.
    
    =========  ============
    Argument   Description
    =========  ============
    data       A string of data to be sent.
    host       The remote host to send the data to.
    port       The port to send the data on.
    =========  ============
    """
    global _datagram
    
    if _datagram is None:
        _datagram = Datagram()
    
    _datagram.write(data, (host, port))
