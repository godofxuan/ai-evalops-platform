import asyncio

import httpx


async def test_httpx_exposes_actual_server_address_on_response_stream() -> None:
    async def handle_request(
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
    ) -> None:
        try:
            await reader.readuntil(b"\r\n\r\n")
            writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}")
            await writer.drain()
        finally:
            writer.close()
            await writer.wait_closed()

    server = await asyncio.start_server(handle_request, "127.0.0.1", 0)
    try:
        socket = server.sockets[0]
        port = int(socket.getsockname()[1])
        async with (
            httpx.AsyncClient(trust_env=False) as client,
            client.stream(
                "GET",
                f"http://127.0.0.1:{port}/peer-contract",
            ) as response,
        ):
            stream = response.extensions["network_stream"]
            assert stream.get_extra_info("server_addr") == ("127.0.0.1", port)
            await response.aread()
    finally:
        server.close()
        await server.wait_closed()
