"""Wire framing and message schemas for the collaboration link.

Every frame is length-prefixed and hard-capped (anti-DoS). Control payloads are
JSON validated by strict pydantic models (unknown fields rejected, lengths
bounded). Binary frames carry raw media/file bytes.
"""

import json
import struct

from pydantic import BaseModel, ConfigDict, Field

from . import security

HEADER = struct.Struct(">IB")  # (total_len_including_type, type_code)

# type name -> code
TYPES = {
    "HELLO": 1, "ACCEPT": 2, "REJECT": 3, "CAPS": 4, "PING": 5, "PONG": 6, "BYE": 7,
    "CHALLENGE": 8,
    "CHAT_MSG": 10, "CHAT_TYPING": 11, "CHAT_READ": 12,
    "FILE_OFFER": 20, "FILE_ACCEPT": 21, "FILE_CHUNK": 22, "FILE_DONE": 23, "FILE_CANCEL": 24,
    "AUDIO_FRAME": 30, "VIDEO_FRAME": 31, "MEDIA_CTRL": 32,
    "PROJECT_SYNC": 40, "PROJECT_STATE_VEC": 41,
    "LLM_TASK": 50, "LLM_RESULT": 51, "LLM_ERROR": 52, "LLM_CANCEL": 53,
}
CODES = {v: k for k, v in TYPES.items()}
BINARY_TYPES = {"AUDIO_FRAME", "VIDEO_FRAME", "PROJECT_SYNC", "PROJECT_STATE_VEC"}


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Hello(_Strict):
    proto: str = Field(default="K1", max_length=8)
    callsign: str = Field(max_length=security.MAX_CALLSIGN_LEN)
    display_name: str = Field(default="", max_length=64)
    fp: str = Field(default="", max_length=64)
    capabilities: list[str] = Field(default_factory=list, max_length=32)
    cert: str = Field(default="", max_length=4096)
    sig: str = Field(default="", max_length=256)


class Challenge(_Strict):
    nonce: str = Field(max_length=128)


class Accept(_Strict):
    sas: str = Field(default="", max_length=8)


class Reject(_Strict):
    reason: str = Field(default="", max_length=200)


class Caps(_Strict):
    capabilities: list[str] = Field(default_factory=list, max_length=32)


class ChatMsg(_Strict):
    text: str = Field(max_length=8000)


class Typing(_Strict):
    on: bool = True


class FileOffer(_Strict):
    transfer_id: str = Field(max_length=64)
    name: str = Field(max_length=200)
    size: int = Field(ge=0, le=2 * 1024 * 1024 * 1024)
    sha256: str = Field(default="", max_length=64)


class FileAccept(_Strict):
    transfer_id: str = Field(max_length=64)
    accept: bool = True


class FileChunk(_Strict):
    transfer_id: str = Field(max_length=64)
    seq: int = Field(ge=0)
    data: str = Field(max_length=400000)  # base64 of <=256KB chunk


class FileDone(_Strict):
    transfer_id: str = Field(max_length=64)
    sha256: str = Field(default="", max_length=64)


class FileCancel(_Strict):
    transfer_id: str = Field(default="", max_length=64)
    reason: str = Field(default="", max_length=200)


class MediaCtrl(_Strict):
    audio: bool = False
    video: bool = False


class LlmTask(_Strict):
    task_id: str = Field(max_length=64)
    prompt: str = Field(max_length=16000)
    context: str = Field(default="", max_length=16000)
    mode: str = Field(default="council", max_length=16)


class LlmResult(_Strict):
    task_id: str = Field(max_length=64)
    text: str = Field(max_length=32000)
    model: str = Field(default="", max_length=120)


class LlmError(_Strict):
    task_id: str = Field(max_length=64)
    error: str = Field(max_length=1000)


class Ping(_Strict):
    ts: float = 0.0


CONTROL_MODELS = {
    "HELLO": Hello, "ACCEPT": Accept, "REJECT": Reject, "CAPS": Caps,
    "CHALLENGE": Challenge,
    "CHAT_MSG": ChatMsg, "CHAT_TYPING": Typing, "CHAT_READ": _Strict,
    "FILE_OFFER": FileOffer, "FILE_ACCEPT": FileAccept, "FILE_CHUNK": FileChunk,
    "FILE_DONE": FileDone, "FILE_CANCEL": FileCancel, "MEDIA_CTRL": MediaCtrl,
    "LLM_TASK": LlmTask, "LLM_RESULT": LlmResult, "LLM_ERROR": LlmError,
    "PING": Ping, "PONG": Ping, "BYE": _Strict,
}


def validate_control(type_name: str, obj: dict):
    model = CONTROL_MODELS.get(type_name)
    if model is None:
        raise ValueError(f"Unknown/unsupported control type '{type_name}'.")
    return model.model_validate(obj)


async def write_binary(writer, type_name: str, data: bytes):
    total = 1 + len(data)
    security.check_frame_size(len(data))
    writer.write(HEADER.pack(total, TYPES[type_name]))
    writer.write(data)
    await writer.drain()


async def write_control(writer, type_name: str, obj):
    payload = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    await write_binary(writer, type_name, payload)


async def read_frame(reader):
    """Return (type_name, payload_bytes). Raises on malformed/oversized frames."""
    header = await reader.readexactly(HEADER.size)
    total, code = HEADER.unpack(header)
    if total < 1:
        raise ValueError("Invalid frame length.")
    security.check_frame_size(total - 1)
    type_name = CODES.get(code)
    if type_name is None:
        raise ValueError(f"Unknown frame type code {code}.")
    payload = await reader.readexactly(total - 1)
    return type_name, payload


def parse_control(type_name: str, payload: bytes):
    obj = json.loads(payload.decode("utf-8", errors="strict"))
    if not isinstance(obj, dict):
        raise ValueError("Control payload must be an object.")
    return validate_control(type_name, obj)