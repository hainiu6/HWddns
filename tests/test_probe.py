import socket
from contextlib import nullcontext
from unittest.mock import patch
import unittest

from probe import scan_tcp_ports, tcp_reachable


class ProbeTests(unittest.TestCase):
    def test_tcp_port_reachability(self):
        server = socket.socket()
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        port = server.getsockname()[1]
        try:
            reachable, _ = tcp_reachable("127.0.0.1", port, attempts=1, timeout=0.5)
            self.assertTrue(reachable)
        finally:
            server.close()
        unreachable, _ = tcp_reachable("127.0.0.1", port, attempts=1, timeout=0.5)
        self.assertFalse(unreachable)

    def test_failed_connection_retries_once_and_can_recover(self):
        with patch("probe.socket.create_connection",
                   side_effect=[TimeoutError("first attempt timed out"), nullcontext()]) as connect, \
                patch("probe.time.sleep") as wait:
            reachable, detail = tcp_reachable("service.example.com", 58611, attempts=2, timeout=3)
            self.assertTrue(reachable)
            self.assertEqual(detail, "TCP 连接成功")
            self.assertEqual(connect.call_count, 2)
            self.assertTrue(all(call.kwargs["timeout"] == 3 for call in connect.call_args_list))
            wait.assert_called_once_with(1)

        with patch("probe.socket.create_connection", side_effect=OSError("unreachable")) as connect, \
                patch("probe.time.sleep") as wait:
            reachable, _ = tcp_reachable("service.example.com", 58611, attempts=2, timeout=3)
            self.assertFalse(reachable)
            self.assertEqual(connect.call_count, 2)
            wait.assert_called_once_with(1)

    def test_range_retries_failed_ports_without_retrying_success(self):
        attempts = {}
        def connect(address, timeout):
            _, port = address
            attempts[port] = attempts.get(port, 0) + 1
            self.assertEqual(timeout, 3)
            if port == 58611 or (port == 58610 and attempts[port] == 1):
                raise TimeoutError("unreachable")
            return nullcontext()

        with patch("probe.socket.create_connection", side_effect=connect), patch("probe.time.sleep"):
            results = scan_tcp_ports("service.example.com", 58610, 58612)
        self.assertEqual([(port, reachable) for port, reachable, _ in results],
                         [(58610, True), (58611, False), (58612, True)])
        self.assertEqual(attempts, {58610: 2, 58611: 2, 58612: 1})

    def test_tcp_port_range_results_stay_in_order(self):
        with socket.socket() as server:
            server.bind(("127.0.0.1", 0))
            server.listen(2)
            port = server.getsockname()[1]
            start = port - 1 if port > 1 else port
            results = scan_tcp_ports("127.0.0.1", start, port)
            self.assertEqual([item[0] for item in results], list(range(start, port + 1)))
            self.assertTrue(results[-1][1])


if __name__ == "__main__":
    unittest.main()
