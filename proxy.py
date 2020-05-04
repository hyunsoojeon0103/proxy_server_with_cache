#!/usr/bin/env python
from socket import *
import os
import sys
import time
from _thread import *
import threading
from datetime import datetime
from threading import Thread, Lock

# it keeps track of the previous domain for favicon
prevDomain = ""


#A class that parses through the HTTP request,
#extracts the field names and data and stores
#them in a dictionary

class HttpRequest:
    # if empty, return false
    def parse(self, request):
        if request == '':
            return False

        global prevDomain

        lines = request.split('\r\n')
        
        # if not 3, something must be wrong
        firstLine = lines[0].split(' ')
        if len(firstLine) != 3:
            return False

        # Below is to extract field names and data
        # and store them in a dictionary

        if firstLine[1][-1] == '/':
            firstLine[1]+="index.html"
        
        self.fields = {}

        if "favicon" in firstLine[1]:
            self.fields['domain'] = prevDomain
            self.fields['path'] = "/favicon.ico"
        else:
            slash = firstLine[1].find('/',1)
            self.fields['domain'] = firstLine[1][1:slash]
            self.fields['path'] = firstLine[1][slash:] 

        self.fields['method'] = firstLine[0]
        self.fields['http'] = firstLine[2] 

        prevDomain = self.fields['domain']

        for line in lines[1:]:
            if len(line) > 0:
                idx = line.find(':')
                self.fields[line[:idx]] = line[idx+2:]

        return True

    # if the field exists in the dictionary
    # it returns the data or else nothing
    def getField(self, field):
        if field in self.fields:
            return self.fields[field]
        return ''


# As with the http request class above
# it parses the server response and
# stores field names and data in a dictionary

class HttpResponse:    
    def __init__(self, response):
        self.response = response
        response = response.decode(errors="ignore")
        headerEnd = response.find("\r\n\r\n")
        response = response[:headerEnd]
        response = response.split("\r\n")
        
        self.fields = {}
        firstLine = response[0].split(" ")
        self.fields['http'] = firstLine[0]
        self.fields['status'] = firstLine[1]
        for line in response[1:]:
            if len(line) > 0:
                idx = line.find(':')
                self.fields[line[:idx]] = line[idx+2:]

    def getField(self,field):
        if field in self.fields:
            return self.fields[field]
        return ''

# A server class that waits on clients(browser)
class Server:
    def __init__(self, name, portNum, bufSize = 4096):
        self.name = name
        self.portNum = portNum
        self.bufSize = bufSize
        self.socket = socket(AF_INET, SOCK_STREAM)
    
    def bind(self):
        self.socket.bind((self.name,self.portNum))
    
    def listen(self, maxNum):
        self.socket.listen(maxNum)
        print('The server is ready to receive')
    
    def accept(self):
        return self.socket.accept()
    
    def closeConnection():
        self.connectionSocket.close()
    
    def close(self):
        self.socket.close()

# A client class that connects to the backend server
class Client:
    def __init__(self, servPort, bufSize = 4096):
        self.servPort = servPort
        self.bufSize = bufSize
        self.connected = False

    def connect(self,servName):
        self.socket = socket(AF_INET, SOCK_STREAM)
        self.socket.connect((servName,self.servPort))
        self.connected = True

    def send(self, msg):
        self.socket.send(msg.encode())

    # some data is greater than buffer size
    # so, it recieves data till the end
    def receive(self):
        res = b''
        while True:
            data = self.socket.recv(self.bufSize)
            if not data: 
                break
            res+=data
        return res

    def close(self):
        self.socket.close()
        self.connected = False

# A proxy class that handles both client and server
# as it is itself a client to the backend server 
# and a server to the clients(browser) 
class Proxy:
    def __init__(self, portNum = 8080, name ='', servPort = 80, bufSize= 4096):
        self.server = Server(name, portNum, bufSize)
        self.client = Client(servPort, bufSize)

    def connectToServ(self,servName):
        self.client.connect(servName)

    def sendToServ(self, msg):
        msg = "GET " + msg + " HTTP/1.0\r\n\r\n"
        self.client.send(msg)

    def recvFromServ(self):
        return self.client.receive()

    def clientClose(self):
        # close the socket only if it is open
        if self.client.connected:
            self.client.close()

    def bind(self):
        self.server.bind()

    def listen(self, maxNum = 5):
        self.server.listen(maxNum)

    def accept(self):
        return self.server.accept()

    def servClose(self):
        self.server.close()
    
    def close(self):
        self.clientClose()
        self.servClose()

# A class that handles caching and
# handles race conditions with a lock
class Cache:
    def __init__(self):
        self.lock = Lock()

    def exist(self,domain,path):
        completePath = "./" + domain + path
        return os.path.exists(completePath) and os.path.isfile(completePath)
    
    # a thread must acquire a lock to write a file
    def cache(self,domain,path,data):
        self.lock.acquire()
        completePath = "./" + domain + path
        slash = completePath.rfind("/")
        dirPath = completePath[:slash]

        if not os.path.exists(dirPath):
            os.makedirs(dirPath)

        with open(completePath, "wb") as w:
            stamp = datetime.timestamp(datetime.now())
            stamp = datetime.fromtimestamp(stamp).isoformat() + "\r\n"
            stamp = stamp.encode()
            stamp += data
            w.write(stamp)
        self.lock.release()
    
    # a thread does not need a lock to access data
    def retrieve(self, domain, path):
        completePath = "./" + domain + path
        res = b''
        with open(completePath, "rb") as r:
            next(r)
            res = r.read()
        return res

# a function that a thread calls to handle a request
def serve(proxy,cache,connectionSocket):
    
    request = HttpRequest() 
    # check if the request is valid 
    if request.parse(connectionSocket.recv(4096).decode()):
        
        domain = request.getField("domain")
        path = request.getField("path")
        # check if the cache exists 
        if cache.exist(domain,path):
            res = cache.retrieve(domain,path)
        else:
            status301 = True
            # serve the request and cache the result
            try:
                while status301:
                    proxy.connectToServ(domain)
                    proxy.sendToServ(path)
                    res = HttpResponse(proxy.recvFromServ())
                    if res.getField("status") == "301":
                        # fix the path according to referal
                        proxy.clientClose()
                        path = res.getField("Location")
                        idx = path.find(domain)
                        path = path[idx + len(domain):]
                        if path[-1] == '/':
                            path += "index.html"
                    else:
                        status301 = False
                if not cache.exist(domain,path):
                    cache.cache(domain,path,res.response)
                res = res.response
            except Exception as err:
                # if an error occured, then return this result
                res = "HTTP/1.0 202 NO CONTENT\r\n\r\n".encode()

        connectionSocket.send(res)

    connectionSocket.close()
    proxy.close()

if __name__ == "__main__":

    if len(sys.argv) != 2:
        print("usage: python3 proxy.py [port_num]")
        sys.exit(2)
    if not sys.argv[1].isnumeric():
        print(sys.argv[1],"is not a valid port number")
        sys.exit(2)

    proxy = Proxy(int(sys.argv[1]))
    proxy.bind()
    proxy.listen() 

    cache = Cache()
    
    while True:
        connectionSocket, addr = proxy.accept()
        worker = Proxy()
        start_new_thread(serve, (worker,cache,connectionSocket,))
        
    proxy.servClose()
