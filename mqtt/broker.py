"""
Lightweight asyncio MQTT 3.1.1 Broker for local development & simulation.
Allows zero-setup running when Eclipse Mosquitto is not installed.
Fully supports CONNECT, CONNACK, PUBLISH (QoS 0/1), PUBACK, SUBSCRIBE, SUBACK, PINGREQ, PINGRESP, DISCONNECT.
"""

import asyncio
import logging
import struct
from typing import Dict, Set

logger = logging.getLogger("mqtt_broker")


def match_topic(filter_topic: str, topic: str) -> bool:
    """Matches MQTT topic filters including + (single level) and # (multi level) wildcards."""
    f_parts = filter_topic.split("/")
    t_parts = topic.split("/")

    i = 0
    while i < len(f_parts):
        f = f_parts[i]
        if f == "#":
            return True
        if i >= len(t_parts):
            return False
        if f != "+" and f != t_parts[i]:
            return False
        i += 1
    return i == len(t_parts)


class MQTTClientSession:
    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, broker: "MiniBroker"):
        self.reader = reader
        self.writer = writer
        self.broker = broker
        self.client_id = ""
        self.subscriptions: Set[str] = set()
        self.closed = False

    async def send_packet(self, packet: bytes):
        if self.closed:
            return
        try:
            self.writer.write(packet)
            await self.writer.drain()
        except Exception:
            self.closed = True

    async def handle(self):
        try:
            while not self.closed:
                # Read fixed header byte 1
                b1 = await self.reader.read(1)
                if not b1:
                    break
                packet_type = b1[0] >> 4
                flags = b1[0] & 0x0F

                # Read remaining length (variable length encoding)
                multiplier = 1
                rem_len = 0
                while True:
                    lb = await self.reader.read(1)
                    if not lb:
                        return
                    byte_val = lb[0]
                    rem_len += (byte_val & 127) * multiplier
                    multiplier *= 128
                    if (byte_val & 128) == 0:
                        break

                # Read variable header + payload
                payload = await self.reader.readexactly(rem_len) if rem_len > 0 else b""

                if packet_type == 1:  # CONNECT
                    # Parse client_id
                    proto_len = struct.unpack("!H", payload[:2])[0]
                    idx = 2 + proto_len + 1  # proto_name + version
                    connect_flags = payload[idx]
                    idx += 1 + 2  # flags + keepalive
                    if idx < len(payload):
                        cid_len = struct.unpack("!H", payload[idx : idx + 2])[0]
                        self.client_id = payload[idx + 2 : idx + 2 + cid_len].decode("utf-8", "ignore")
                    else:
                        self.client_id = f"client-{id(self)}"

                    logger.info(f"MQTT Client connected: {self.client_id}")
                    # Send CONNACK (0x20 0x02 0x00 0x00) -> session present 0, rc 0 (accepted)
                    await self.send_packet(bytes([0x20, 0x02, 0x00, 0x00]))

                elif packet_type == 3:  # PUBLISH
                    dup = (flags >> 3) & 1
                    qos = (flags >> 1) & 3
                    retain = flags & 1

                    topic_len = struct.unpack("!H", payload[:2])[0]
                    topic = payload[2 : 2 + topic_len].decode("utf-8", "ignore")
                    idx = 2 + topic_len

                    msg_id = None
                    if qos > 0:
                        msg_id = struct.unpack("!H", payload[idx : idx + 2])[0]
                        idx += 2

                    msg_data = payload[idx:]
                    logger.debug(f"Publish topic='{topic}', qos={qos}, len={len(msg_data)}")

                    if qos == 1 and msg_id is not None:
                        # Send PUBACK
                        ack = bytes([0x40, 0x02]) + struct.pack("!H", msg_id)
                        await self.send_packet(ack)

                    # Forward to subscribers
                    await self.broker.broadcast(topic, msg_data, qos)

                elif packet_type == 8:  # SUBSCRIBE
                    msg_id = struct.unpack("!H", payload[:2])[0]
                    idx = 2
                    return_codes = []
                    while idx < len(payload):
                        t_len = struct.unpack("!H", payload[idx : idx + 2])[0]
                        t_name = payload[idx + 2 : idx + 2 + t_len].decode("utf-8", "ignore")
                        req_qos = payload[idx + 2 + t_len]
                        idx += 2 + t_len + 1
                        self.subscriptions.add(t_name)
                        return_codes.append(min(req_qos, 1))
                        logger.info(f"Client {self.client_id} subscribed to '{t_name}'")

                    # SUBACK
                    rem = bytes([0x90, 2 + len(return_codes)]) + struct.pack("!H", msg_id) + bytes(return_codes)
                    await self.send_packet(rem)

                elif packet_type == 10:  # UNSUBSCRIBE
                    msg_id = struct.unpack("!H", payload[:2])[0]
                    idx = 2
                    while idx < len(payload):
                        t_len = struct.unpack("!H", payload[idx : idx + 2])[0]
                        t_name = payload[idx + 2 : idx + 2 + t_len].decode("utf-8", "ignore")
                        idx += 2 + t_len
                        self.subscriptions.discard(t_name)
                    # UNSUBACK
                    ack = bytes([0xB0, 0x02]) + struct.pack("!H", msg_id)
                    await self.send_packet(ack)

                elif packet_type == 12:  # PINGREQ
                    # PINGRESP
                    await self.send_packet(bytes([0xD0, 0x00]))

                elif packet_type == 14:  # DISCONNECT
                    break
        except (asyncio.IncompleteReadError, ConnectionResetError):
            pass
        except Exception as e:
            logger.debug(f"Session error {self.client_id}: {e}")
        finally:
            self.closed = True
            try:
                self.writer.close()
                await self.writer.wait_closed()
            except Exception:
                pass
            self.broker.remove_session(self)
            logger.info(f"MQTT Client disconnected: {self.client_id}")


class MiniBroker:
    def __init__(self, host: str = "127.0.0.1", port: int = 1883):
        self.host = host
        self.port = port
        self.sessions: Set[MQTTClientSession] = set()
        self.server = None

    def remove_session(self, session: MQTTClientSession):
        self.sessions.discard(session)

    async def broadcast(self, topic: str, data: bytes, qos: int = 0):
        # Encode PUBLISH packet for QoS 0 (or QoS matching subscription)
        topic_bytes = topic.encode("utf-8")
        rem_len = 2 + len(topic_bytes) + len(data)

        # encode remaining length
        rem_bytes = bytearray()
        x = rem_len
        while True:
            encoded_byte = x % 128
            x = x // 128
            if x > 0:
                encoded_byte |= 128
            rem_bytes.append(encoded_byte)
            if x == 0:
                break

        packet = bytes([0x30]) + rem_bytes + struct.pack("!H", len(topic_bytes)) + topic_bytes + data

        for s in list(self.sessions):
            if any(match_topic(sub, topic) for sub in s.subscriptions):
                asyncio.create_task(s.send_packet(packet))

    async def _handle_conn(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        session = MQTTClientSession(reader, writer, self)
        self.sessions.add(session)
        await session.handle()

    async def start(self):
        self.server = await asyncio.start_server(self._handle_conn, self.host, self.port)
        logger.info(f"MiniBroker listening on {self.host}:{self.port}")

    async def stop(self):
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for s in list(self.sessions):
            s.closed = True
            try:
                s.writer.close()
            except Exception:
                pass


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


async def main():
    import argparse

    parser = argparse.ArgumentParser(description="Mini MQTT Broker")
    parser.add_argument("--host", default="127.0.0.1", help="Bind host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=1883, help="Port (default: 1883)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    broker = MiniBroker(host=args.host, port=args.port)
    await broker.start()
    print(f"MQTT Broker running on {args.host}:{args.port}. Press Ctrl+C to stop.")
    try:
        while True:
            await asyncio.sleep(3600)
    except (asyncio.CancelledError, KeyboardInterrupt):
        pass
    finally:
        await broker.stop()


if __name__ == "__main__":
    asyncio.run(main())
