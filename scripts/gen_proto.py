"""Compile proto/neutron/v1/*.proto into neutron_rpc/ package."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from grpc_tools import protoc


def _find_plugin(name: str) -> str:
    scripts_dir = Path(sys.executable).resolve().parent
    suffix = ".exe" if os.name == "nt" else ""
    local_candidate = scripts_dir / f"{name}{suffix}"
    if local_candidate.exists():
        return str(local_candidate)
    found = shutil.which(name)
    if found:
        return found
    raise FileNotFoundError(f"Protoc plugin '{name}' not found next to {sys.executable} or in PATH.")


def main() -> int:
    root = Path(__file__).resolve().parent.parent
    proto_root = root / "proto"
    out_dir = root / "neutron_rpc"
    out_dir.mkdir(parents=True, exist_ok=True)

    py_plugin = _find_plugin("protoc-gen-py")
    connect_plugin = _find_plugin("protoc-gen-connectrpc")
    proto_file = proto_root / "neutron" / "v1" / "neutron.proto"

    args = [
        "grpc_tools.protoc",
        f"-I{proto_root}",
        f"--plugin=protoc-gen-py={py_plugin}",
        f"--plugin=protoc-gen-connectrpc={connect_plugin}",
        f"--py_out={out_dir}",
        f"--connectrpc_out={out_dir}",
        str(proto_file),
    ]
    exit_code = protoc.main(args)
    if exit_code != 0:
        return exit_code

    for pkg in [out_dir, out_dir / "neutron", out_dir / "neutron" / "v1"]:
        init_file = pkg / "__init__.py"
        if not init_file.exists():
            init_file.write_text('"""Generated ConnectRPC & Protobuf package."""\n', encoding="utf-8")

    print(f"Generated ConnectRPC stubs cleanly in {out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

