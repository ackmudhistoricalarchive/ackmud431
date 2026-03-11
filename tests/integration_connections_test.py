import base64
import hashlib
import os
import random
import socket
import struct
import subprocess
import time
import unittest


REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SRC_DIR = os.path.join(REPO_ROOT, "src")


def find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def wait_for_port(port: int, timeout: float = 20.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.25):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"server did not listen on port {port}")


class TelnetSession:
    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.buffer = ""

    def send_line(self, text: str) -> None:
        self.sock.sendall(text.encode("utf-8") + b"\r\n")

    def read_until_any(self, needles: list[str], timeout: float = 5.0) -> str:
        deadline = time.time() + timeout
        lowered = [n.lower() for n in needles]
        while time.time() < deadline:
            hay = self.buffer.lower()
            if any(n in hay for n in lowered):
                return self.buffer
            try:
                chunk = self.sock.recv(8192)
            except socket.timeout:
                continue
            if not chunk:
                break
            self.buffer += chunk.decode("latin1", errors="ignore")
        raise AssertionError(f"did not observe any of {needles!r}; got tail={self.buffer[-400:]!r}")


class WebSocketSession:
    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.text_buffer = ""

    def send_line(self, text: str) -> None:
        payload = text.encode("utf-8")
        mask = b"\x11\x22\x33\x44"

        frame = bytearray([0x81])
        if len(payload) < 126:
            frame.append(0x80 | len(payload))
        elif len(payload) < 65536:
            frame.append(0x80 | 126)
            frame.extend(struct.pack("!H", len(payload)))
        else:
            frame.append(0x80 | 127)
            frame.extend(struct.pack("!Q", len(payload)))

        frame.extend(mask)
        frame.extend(bytes(b ^ mask[i % 4] for i, b in enumerate(payload)))
        self.sock.sendall(frame)

    def _recv_frame(self) -> tuple[int, bytes]:
        header = self.sock.recv(2)
        if len(header) < 2:
            raise RuntimeError("incomplete websocket header")

        b1, b2 = header
        opcode = b1 & 0x0F
        payload_len = b2 & 0x7F

        if payload_len == 126:
            payload_len = struct.unpack("!H", self.sock.recv(2))[0]
        elif payload_len == 127:
            payload_len = struct.unpack("!Q", self.sock.recv(8))[0]

        payload = b""
        while len(payload) < payload_len:
            payload += self.sock.recv(payload_len - len(payload))

        return opcode, payload

    def read_until_any(self, needles: list[str], timeout: float = 6.0) -> str:
        deadline = time.time() + timeout
        lowered = [n.lower() for n in needles]
        while time.time() < deadline:
            hay = self.text_buffer.lower()
            if any(n in hay for n in lowered):
                return self.text_buffer
            try:
                opcode, payload = self._recv_frame()
            except socket.timeout:
                continue
            if opcode == 0x1:
                self.text_buffer += payload.decode("latin1", errors="ignore")
            elif opcode == 0x8:
                break
        raise AssertionError(f"did not observe any of {needles!r}; got tail={self.text_buffer[-400:]!r}")


def login_new_character(session, name: str, password: str) -> None:
    try:
        session.read_until_any(["name", "Name:", "What is your name", "By what"], timeout=2.0)
    except AssertionError:
        pass

    session.send_line(name)

    text = session.read_until_any(["Did I get that right", "Password:", "Give me a password", "Illegal name", "Name:"], timeout=10.0)
    if "illegal name" in text.lower():
        raise AssertionError("test generated an illegal login name")
    if "password:" in text.lower() and "did i get that right" not in text.lower() and "give me a password" not in text.lower():
        session.send_line(password)
    else:
        session.send_line("Y")
        session.read_until_any(["password"])
        session.send_line(password)
        session.read_until_any(["Please retype password", "Retype password"])
        session.send_line(password)

        session.read_until_any(["Character Creation Menu"])

        session.send_line("1")
        session.read_until_any(["Please Select M/F/N", "Gender"])
        session.send_line("M")
        session.read_until_any(["Character Creation Menu"])

        session.send_line("2")
        session.read_until_any(["Race", "Hmn"])
        session.send_line("Hmn")
        session.read_until_any(["Character Creation Menu"])

        session.send_line("3")
        session.read_until_any(["Accept", "Reroll", "Please Select"])
        session.send_line("A")
        session.read_until_any(["Character Creation Menu"])

        session.send_line("4")
        session.read_until_any(["class", "Order"])
        session.send_line("Mag Cle Thi War Psi")
        session.read_until_any(["Character Creation Menu"])

        session.send_line("5")
        session.send_line("")  # advance CON_READ_MOTD -> CON_PLAYING
    session.read_until_any(["Welcome to", "mutated", "points are needed"], timeout=12.0)


class ConnectionIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        subprocess.run(["make", "-j4"], cwd=SRC_DIR, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def setUp(self) -> None:
        self.port = find_free_port()
        self.server = subprocess.Popen(
            ["./ack", str(self.port)],
            cwd=SRC_DIR,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        wait_for_port(self.port)

    def tearDown(self) -> None:
        if self.server.poll() is None:
            self.server.terminate()
            try:
                self.server.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.server.kill()
                self.server.wait(timeout=3)

    def test_telnet_connection_full_login(self) -> None:
        name = "I" + "".join(random.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(7))
        password = "pw12345"

        with socket.create_connection(("127.0.0.1", self.port), timeout=2) as sock:
            sock.settimeout(2)
            session = TelnetSession(sock)
            login_new_character(session, name, password)
            session.send_line("quit")

    def test_websocket_upgrade_and_full_login(self) -> None:
        name = "V" + "".join(random.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(7))
        password = "pw12345"
        ws_key = "dGhlIHNhbXBsZSBub25jZQ=="

        with socket.create_connection(("127.0.0.1", self.port), timeout=2) as sock:
            sock.settimeout(2)
            request = (
                "GET / HTTP/1.1\r\n"
                "Host: localhost\r\n"
                "Upgrade: websocket\r\n"
                "Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {ws_key}\r\n"
                "Sec-WebSocket-Version: 13\r\n\r\n"
            ).encode("ascii")
            sock.sendall(request)

            response = b""
            while b"\r\n\r\n" not in response:
                response += sock.recv(4096)

            self.assertIn(b"101 Switching Protocols", response)
            accept = base64.b64encode(
                hashlib.sha1((ws_key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11").encode("ascii")).digest()
            )
            self.assertIn(b"Sec-WebSocket-Accept: " + accept, response)

            session = WebSocketSession(sock)
            login_new_character(session, name, password)
            session.send_line("quit")


if __name__ == "__main__":
    unittest.main()
