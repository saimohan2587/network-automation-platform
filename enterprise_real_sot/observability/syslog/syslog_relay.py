import socket
import select
import urllib.request
import json
import time
import re
import threading

LOKI_URL = "http://loki:3100/loki/api/v1/push"
UDP_PORT = 1514
TCP_PORT = 1515

PRIO_REGEX = re.compile(r"^<(\d+)>(?:(\d+):\s*)?(.*)")

SEVERITY_MAP = {
    0: "emergency",
    1: "alert",
    2: "critical",
    3: "error",
    4: "warning",
    5: "notice",
    6: "info",
    7: "debug"
}

IP_HOST_MAP = {
    "10.10.30.2": "sw2_gns3",
    "10.10.30.1": "sw1_gns3",
    "10.10.10.2": "r1_gns3",
    "127.0.0.1": "localhost"
}

def parse_and_push(data_str, src_ip, loki_url=LOKI_URL):
    lines = [l.strip() for l in data_str.splitlines() if l.strip()]
    if not lines:
        return

    streams_dict = {}

    for line in lines:
        prio_match = PRIO_REGEX.match(line)
        prio_val = 189
        body = line
        if prio_match:
            prio_val = int(prio_match.group(1))
            body = prio_match.group(3)
        
        facility = prio_val // 8
        severity = prio_val % 8
        level_str = SEVERITY_MAP.get(severity, "info")
        
        hostname = IP_HOST_MAP.get(src_ip, src_ip)
        if ":" in body:
            prefix = body.split(":", 1)[0].strip()
            if prefix and " " not in prefix and not prefix.startswith("%") and not prefix.startswith("*"):
                hostname = prefix

        key = (hostname, src_ip, level_str)
        
        now_ns = str(time.time_ns())
        if key not in streams_dict:
            streams_dict[key] = []
        streams_dict[key].append([now_ns, body])

    payload_streams = []
    for (hostname, src_ip, level_str), values in streams_dict.items():
        payload_streams.append({
            'stream': {
                'job': 'syslog',
                'hostname': hostname,
                'source_ip': src_ip,
                'level': level_str,
                'service_name': 'syslog'
            },
            'values': values
        })

    payload = {'streams': payload_streams}

    try:
        req = urllib.request.Request(
            loki_url,
            data=json.dumps(payload).encode('utf-8'),
            headers={'Content-Type': 'application/json'}
        )
        urllib.request.urlopen(req, timeout=3.0)
    except Exception as e:
        print(f"[SyslogRelay Error pushing to Loki]: {e}", flush=True)

def handle_tcp_client(conn, addr, loki_url):
    src_ip = addr[0]
    try:
        while True:
            data = conn.recv(4096)
            if not data:
                break
            data_str = data.decode("utf-8", errors="ignore")
            parse_and_push(data_str, src_ip, loki_url)
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass

def main():
    import sys
    loki_host = "loki" if len(sys.argv) > 1 and sys.argv[1] == "--container" else "localhost"
    loki_url = f"http://{loki_host}:3100/loki/api/v1/push"

    udp_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    udp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    udp_sock.bind(("0.0.0.0", UDP_PORT))

    tcp_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    tcp_sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    tcp_sock.bind(("0.0.0.0", TCP_PORT))
    tcp_sock.listen(20)

    print(f"[SyslogRelay] Listening for Cisco Syslog on UDP {UDP_PORT} and TCP {TCP_PORT} (Loki: {loki_url})...", flush=True)

    def listen_udp():
        while True:
            try:
                data, addr = udp_sock.recvfrom(4096)
                if data:
                    data_str = data.decode("utf-8", errors="ignore")
                    parse_and_push(data_str, addr[0], loki_url)
            except Exception as e:
                print(f"[UDP Error]: {e}", flush=True)

    t_udp = threading.Thread(target=listen_udp, daemon=True)
    t_udp.start()

    while True:
        try:
            conn, addr = tcp_sock.accept()
            t_tcp = threading.Thread(target=handle_tcp_client, args=(conn, addr, loki_url), daemon=True)
            t_tcp.start()
        except Exception as e:
            print(f"[TCP Error]: {e}", flush=True)

if __name__ == "__main__":
    main()
