"""Minimal multipart/form-data reader for one uploaded file.

Stdlib-only: cgi is gone on newer Pythons, and we only need a single file field
plus optional text fields for the analyze endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from email.parser import BytesParser
from email.policy import HTTP


@dataclass
class Upload:
    filename: str
    content_type: str
    data: bytes


@dataclass
class Multipart:
    files: dict[str, Upload] = field(default_factory=dict)
    fields: dict[str, str] = field(default_factory=dict)


def parse(content_type: str, body: bytes) -> Multipart:
    """Parse a multipart body. Raises ValueError on a malformed request."""
    if "multipart/form-data" not in content_type.lower():
        raise ValueError("expected multipart/form-data")
    # email needs a full MIME header block to find the boundary.
    message = BytesParser(policy=HTTP).parsebytes(
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode() + body
    )
    if not message.is_multipart():
        raise ValueError("not a multipart body")
    out = Multipart()
    for part in message.iter_parts():
        disposition = part.get("Content-Disposition", "")
        if "form-data" not in disposition:
            continue
        name = part.get_param("name", header="Content-Disposition")
        if not name:
            continue
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename is not None:
            out.files[name] = Upload(
                filename=filename,
                content_type=part.get_content_type(),
                data=payload,
            )
        else:
            out.fields[name] = payload.decode("utf-8", errors="replace")
    return out
