from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
import threading
import datetime
import time
import requests


LISTENING_INTERFACE = 'localhost'
LISTENING_PORT = 8100
EPILOGG_API_URL = 'https://epilogg.mjerenja.com/api/'
EPILOGG_USER_AGENT = "epi:logg API Client"
EPILOGG_PROXY_USER_AGENT = "epi:logg Proxy"

PROXY_MODE_ONLINE = 0
PROXY_MODE_OFFLINE = 1

MAX_QUEUE_SIZE = -1  # -1 = no limit
DEBUG = False
MAIN_THREAD_SLEEP_TIME = 10  # s
ASYNC_QUEUE = False


try:
    from config_local import *
except ImportError:
    pass


#**************************************************************************************************


class Handler(BaseHTTPRequestHandler):

    #----------------------------------------------------------------------------------------------

    def do_GET(self):
        self.send_response(200)
        self.end_headers()

        if self.path.rstrip('/') == '/ping':
            self.wfile.write(b">>> PONG!\n")

    #----------------------------------------------------------------------------------------------

    def do_POST(self):
        content_len = int(self.headers.get('Content-Length'))

        if not 'User-Agent' in self.headers or self.headers.get('User-Agent') != EPILOGG_USER_AGENT:
            self.send_response(403)  # forbidden
            self.end_headers()
            return

        self.server.proxy.queue_request(
            headers=self.headers,
            content=self.rfile.read(content_len).strip(),
        )

        self.send_response(200)
        self.end_headers()

    #----------------------------------------------------------------------------------------------


#**************************************************************************************************


class ThreadingSimpleServer(ThreadingMixIn, HTTPServer):
    proxy = None

    #----------------------------------------------------------------------------------------------

    def __init__(self, *args, **kwargs):

        if 'proxy' in kwargs:
            self.proxy = kwargs['proxy']
            kwargs.pop('proxy')

        super(ThreadingSimpleServer, self).__init__(*args, **kwargs)

    #----------------------------------------------------------------------------------------------


#**************************************************************************************************


class ProyxRequest:
    headers = None
    content = None
    timestamp = None

    #----------------------------------------------------------------------------------------------

    def __init__(self, headers, content):
        self.headers = headers
        self.content = content
        self.timestamp = datetime.datetime.now()

    #----------------------------------------------------------------------------------------------


#**************************************************************************************************


class EpiloggProxy(threading.Thread):
    mode = PROXY_MODE_ONLINE
    queue = None
    __terminate_request = False
    terminated = False

    #----------------------------------------------------------------------------------------------

    def __init__(self, *args, **kwargs):
        self.queue = list()
        super(EpiloggProxy, self).__init__(*args, **kwargs)

    #----------------------------------------------------------------------------------------------

    def queue_request(self, headers, content):
        hdrs = {
            'X-Proxy': EPILOGG_PROXY_USER_AGENT,
        }

        if DEBUG:
            print("> queue_request")

        if 'Content-Type' in headers:
            hdrs.update({
                'Content-Type': headers.get('Content-Type')
            })
        if 'Authorization' in headers:
            hdrs.update({
                'Authorization': headers.get('Authorization')
            })
        if 'User-Agent' in headers:
            hdrs.update({
                'User-Agent': headers.get('User-Agent')
            })

        request = ProyxRequest(
            headers=hdrs,
            content=content,
        )

        if self.mode == PROXY_MODE_ONLINE and not ASYNC_QUEUE:
            if not self.post_request(request):
                self.mode = PROXY_MODE_OFFLINE
                self.queue.append(request)
        else:
            self.queue.append(request)

        # trim queue if size out of bounds
        if MAX_QUEUE_SIZE != -1:
            while len(self.queue) > MAX_QUEUE_SIZE:
                self.queue.pop(0)
                if DEBUG:
                    print("> Trimming queue, new len {}".format(len(self.queue)))

    #----------------------------------------------------------------------------------------------

    def post_request(self, request):
        try:
            response = requests.post(
                url=EPILOGG_API_URL,
                data=request.content,
                headers=request.headers,
            )
            if DEBUG:
                print("> post_request status_code: {}".format(response.status_code))

            return response.status_code == 200

        except (requests.exceptions.ConnectionError, requests.exceptions.ConnectTimeout):
            if DEBUG:
                print("> post_request: FAIL")
            return False

    #----------------------------------------------------------------------------------------------

    def run(self):
        while not self.__terminate_request:

            while len(self.queue) > 0:
                if DEBUG:
                    print("> attempting to send from queue, queued items: {}".format(len(self.queue)))

                request = self.queue[0]
                if self.post_request(request=request):
                    self.mode = PROXY_MODE_ONLINE
                    self.queue.pop(0)
                    time.sleep(0.1)
                else:
                    self.mode = PROXY_MODE_OFFLINE
                    break

            time.sleep(MAIN_THREAD_SLEEP_TIME)

        print("EpiloggProxy thread terminated.")
        self.terminated = True

    #----------------------------------------------------------------------------------------------

    def terminate(self):
        self.__terminate_request = True

    #----------------------------------------------------------------------------------------------


#**************************************************************************************************


def run():
    print("Starting epi:logg proxy at {interface}:{port}".format(
        interface=LISTENING_INTERFACE,
        port=LISTENING_PORT,
    ))
    print("Using epi:logg server {}".format(EPILOGG_API_URL))

    proxy = EpiloggProxy()
    proxy.setDaemon(True)
    proxy.start()

    server = ThreadingSimpleServer((LISTENING_INTERFACE, LISTENING_PORT), Handler, proxy=proxy)
    try:
        server.serve_forever()
    except (KeyboardInterrupt, SystemExit):
        print("Terminating EpiloggProxy...")

    proxy.terminate()
    while not proxy.terminated:
        time.sleep(0.1)


#**************************************************************************************************


if __name__ == '__main__':
    run()