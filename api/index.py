from http.server import BaseHTTPRequestHandler

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        response = '{"status": "online", "message": "Server Stats API is live"}'
        self.wfile.write(response.encode('utf-8'))
        return
