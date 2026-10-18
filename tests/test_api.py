import json
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer

from nbasim.app import Handler


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(('127.0.0.1',0),Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever,daemon=True)
        cls.thread.start()
        cls.url = f'http://127.0.0.1:{cls.server.server_port}'

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def test_actual_dashboard_and_simulation_request(self):
        with urllib.request.urlopen(self.url) as r:
            self.assertIn('The week,',r.read().decode())
        with urllib.request.urlopen(self.url+'/api/demo') as r:
            dataset=json.load(r)
        request=urllib.request.Request(self.url+'/api/simulate',data=json.dumps({'dataset':dataset}).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(request) as r:
            report=json.load(r)
        self.assertEqual(len(report['games']),49)
        self.assertTrue(all(g['simulations']==1000 for g in report['games']))

    def test_bad_payload_returns_client_error(self):
        request=urllib.request.Request(self.url+'/api/simulate',data=b'{"dataset":null}',headers={'Content-Type':'application/json'})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request)
        self.assertEqual(ctx.exception.code,400)

    def test_cross_origin_rejected(self):
        request=urllib.request.Request(self.url+'/api/simulate',data=b'{}',headers={'Content-Type':'application/json','Origin':'https://example.com'})
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            urllib.request.urlopen(request)
        self.assertEqual(ctx.exception.code,403)


if __name__ == '__main__':
    unittest.main()
