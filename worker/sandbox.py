from __future__ import annotations

import asyncio
import json
import logging
import resource
import sys
import tempfile

from shared.types import ExtractionError, ExtractionResult

logger = logging.getLogger("unigest.sandbox")

# Template that wraps the generated extractor code
SANDBOX_WRAPPER = '''
import json
import sys

{code}

async def _main():
    import httpx
    url = sys.argv[1]
    async with httpx.AsyncClient() as client:
        result = await extract(url, client, None)
        print(json.dumps({{"text": result.text, "metadata": result.metadata}}))

import asyncio
asyncio.run(_main())
'''


async def run_in_sandbox(
    code: str,
    url: str,
    timeout: int = 30,
    memory_mb: int = 512,
) -> ExtractionResult:
    """Execute generated extractor code in a sandboxed subprocess."""
    wrapper = SANDBOX_WRAPPER.format(code=code)

    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(wrapper)
        script_path = f.name

    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, script_path, url,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={
                "PATH": "/usr/bin:/usr/local/bin",
                "HOME": "/tmp",
                "TMPDIR": "/tmp",
            },
        )

        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            raise ExtractionError("sandbox_timeout", f"Sandbox timed out after {timeout}s")

        if proc.returncode != 0:
            raise ExtractionError(
                "sandbox_error",
                stderr.decode(errors="replace")[:1000],
            )

        output = stdout.decode().strip()
        if not output:
            raise ExtractionError("sandbox_empty", "Sandbox produced no output")

        data = json.loads(output)
        return ExtractionResult(
            text=data["text"],
            metadata=data.get("metadata", {}),
        )

    finally:
        import os
        os.unlink(script_path)
