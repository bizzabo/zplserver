"""The web interface, driven over real HTTP.

Two traps, both of which cost time to work out the first time:

Blocking HTTP calls against a server on the same event loop deadlock, because the
server never gets to run. The aiohttp test client is async, which avoids it — do
not reach for urllib here.

StateLogHandler is attached by run_ui, not by build_app. A test that builds the
app directly has to attach it too, or every assertion about the log panel
silently sees nothing.
"""

import asyncio
import json
import logging

import pytest
from aiohttp.test_utils import TestClient, TestServer

from zplserver import events, reporting
from zplserver.printer import DPI
from zplserver.server import PrintServer
from zplserver.ui.web import (
    MAX_LABELS,
    State,
    StateLogHandler,
    build_app,
    collect_labels,
)

from .conftest import LABEL, OTHER_LABEL, PNG, POISON, send, settle


class Harness:
    def __init__(self, client, state, server):
        self.client = client
        self.state = state
        self.server = server

    @property
    def port(self):
        return self.server.printer.port

    async def print_label(self, zpl=LABEL):
        before = len(self.state.labels)
        await send(self.port, zpl.encode())
        return await settle(lambda: len(self.state.labels) > before)


@pytest.fixture
async def ui(printer):
    server = PrintServer(printer, host="127.0.0.1")
    state = State(server)
    state.loop = asyncio.get_running_loop()

    handler = StateLogHandler(state)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger = logging.getLogger("zplserver")
    logger.addHandler(handler)
    # The suite silences the logger; the panel needs records to arrive.
    previous = logger.level
    logger.setLevel(logging.INFO)

    tasks = [
        asyncio.ensure_future(reporting.report(printer.bus, open_labels=False)),
        asyncio.ensure_future(collect_labels(state)),
    ]

    client = TestClient(TestServer(build_app(state)))
    await client.start_server()
    try:
        yield Harness(client, state, server)
    finally:
        await client.close()
        for task in tasks:
            task.cancel()
        await server.stop()
        logger.removeHandler(handler)
        logger.setLevel(previous)


class TestPage:
    async def test_index_is_served(self, ui):
        response = await ui.client.get("/")
        assert response.status == 200
        assert "zplserver" in await response.text()

    async def test_the_page_does_not_name_the_vendor(self, ui):
        """The trademark disclaimer lives in the README, not in the interface."""
        assert "zebra" not in (await (await ui.client.get("/")).text()).lower()

    async def test_index_mentions_that_labels_leave_the_machine(self, ui):
        text = " ".join((await (await ui.client.get("/")).text()).split())
        assert "leaves this machine" in text


class TestState:
    async def test_starts_stopped(self, ui):
        body = await (await ui.client.get("/api/state")).json()
        assert body["running"] is False
        assert body["labels"] == []

    async def test_exposes_settings(self, ui):
        body = await (await ui.client.get("/api/state")).json()
        assert body["settings"]["dpi"] == "300"
        assert body["settings"]["width"] == 4
        assert body["settings"]["height"] == 3

    async def test_reflects_a_started_server(self, ui):
        await ui.client.post("/api/server/start")
        body = await (await ui.client.get("/api/state")).json()
        assert body["running"] is True
        assert body["address"]


class TestServerControl:
    async def test_start_then_stop(self, ui):
        started = await (await ui.client.post("/api/server/start")).json()
        assert started["ok"] is True
        assert ui.server.is_running
        stopped = await (await ui.client.post("/api/server/stop")).json()
        assert stopped["ok"] is True
        assert not ui.server.is_running

    async def test_port_in_use_is_reported_as_json(self, ui):
        """This must not raise out of the handler and 500 the request."""
        blocker = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
        taken = blocker.sockets[0].getsockname()[1]
        try:
            await ui.client.post("/api/settings", json={"port": taken})
            body = await (await ui.client.post("/api/server/start")).json()
            assert body["ok"] is False
            assert body["error"]
        finally:
            blocker.close()
            await blocker.wait_closed()

    async def test_still_healthy_after_a_failed_start(self, ui):
        blocker = await asyncio.start_server(lambda r, w: None, "127.0.0.1", 0)
        try:
            await ui.client.post(
                "/api/settings", json={"port": blocker.sockets[0].getsockname()[1]}
            )
            await ui.client.post("/api/server/start")
        finally:
            blocker.close()
            await blocker.wait_closed()
        assert (await ui.client.get("/api/state")).status == 200


class TestLabels:
    async def test_a_printed_label_appears(self, ui):
        await ui.client.post("/api/server/start")
        assert await ui.print_label()
        body = await (await ui.client.get("/api/state")).json()
        assert len(body["labels"]) == 1
        assert body["labels"][0]["bytes"] == len(PNG)

    async def test_two_labels_in_one_write_both_appear(self, ui):
        await ui.client.post("/api/server/start")
        await send(ui.port, (LABEL + OTHER_LABEL).encode())
        assert await settle(lambda: len(ui.state.labels) == 2)

    async def test_png_is_served(self, ui):
        await ui.client.post("/api/server/start")
        assert await ui.print_label()
        label_id = ui.state.labels[0].id
        response = await ui.client.get(f"/labels/{label_id}.png")
        assert response.status == 200
        assert response.headers["Content-Type"] == "image/png"
        assert await response.read() == PNG

    async def test_download_sets_a_filename(self, ui):
        await ui.client.post("/api/server/start")
        assert await ui.print_label()
        label_id = ui.state.labels[0].id
        response = await ui.client.get(f"/labels/{label_id}.png?download=1")
        disposition = response.headers["Content-Disposition"]
        assert "attachment" in disposition
        assert f"label-{label_id}.png" in disposition

    async def test_plain_view_is_not_a_download(self, ui):
        await ui.client.post("/api/server/start")
        assert await ui.print_label()
        response = await ui.client.get(f"/labels/{ui.state.labels[0].id}.png")
        assert "Content-Disposition" not in response.headers

    async def test_detail_carries_zpl_and_decoded_commands(self, ui):
        await ui.client.post("/api/server/start")
        assert await ui.print_label()
        label_id = ui.state.labels[0].id
        body = await (await ui.client.get(f"/api/labels/{label_id}")).json()
        assert body["zpl"] == LABEL
        assert len(body["decoded"]) == 5
        assert any("^FD" in line for line in body["decoded"])

    async def test_missing_label_png_is_a_404(self, ui):
        assert (await ui.client.get("/labels/424242.png")).status == 404

    async def test_missing_label_detail_is_a_404(self, ui):
        assert (await ui.client.get("/api/labels/424242")).status == 404

    async def test_dismiss_removes_one(self, ui):
        await ui.client.post("/api/server/start")
        await send(ui.port, (LABEL + OTHER_LABEL).encode())
        assert await settle(lambda: len(ui.state.labels) == 2)
        first = ui.state.labels[0].id
        body = await (await ui.client.post(f"/api/labels/{first}/dismiss")).json()
        assert body["ok"] is True
        assert [label.id for label in ui.state.labels] != [first]
        assert len(ui.state.labels) == 1

    async def test_dismissing_a_missing_label_is_a_404(self, ui):
        assert (await ui.client.post("/api/labels/424242/dismiss")).status == 404

    async def test_clear_removes_everything(self, ui):
        await ui.client.post("/api/server/start")
        await send(ui.port, (LABEL + OTHER_LABEL).encode())
        assert await settle(lambda: len(ui.state.labels) == 2)
        body = await (await ui.client.post("/api/labels/clear")).json()
        assert body["cleared"] == 2
        assert len(ui.state.labels) == 0

    async def test_a_render_failure_adds_no_label(self, ui):
        await ui.client.post("/api/server/start")
        await send(ui.port, f"^XA^FD{POISON}^FS^XZ".encode())
        assert await settle(
            lambda: any(
                entry["level"] == "ERROR" for entry in ui.state.logs
            )
        )
        assert len(ui.state.labels) == 0

    async def test_oldest_labels_are_evicted(self, ui):
        """The store is capped, so a long session cannot grow without bound."""
        for index in range(MAX_LABELS + 5):
            ui.state.add_label(events.LabelRendered(1, f"^XA^FD{index}^FS^XZ", PNG))
        assert len(ui.state.labels) == MAX_LABELS
        # The survivors are the most recent ones.
        assert "^XA^FD4^FS^XZ" not in [label.zpl for label in ui.state.labels]
        assert ui.state.labels[-1].zpl.endswith(f"^FD{MAX_LABELS + 4}^FS^XZ")

    async def test_ids_are_unique(self, ui):
        for index in range(5):
            ui.state.add_label(events.LabelRendered(1, LABEL, PNG))
        ids = [label.id for label in ui.state.labels]
        assert len(set(ids)) == len(ids)


class TestSettings:
    async def test_applying_settings(self, ui):
        body = await (
            await ui.client.post(
                "/api/settings", json={"width": 6, "height": 4, "dpi": "203"}
            )
        ).json()
        assert body["ok"] is True
        assert ui.server.printer.label_width == 6
        assert ui.server.printer.label_height == 4
        assert ui.server.printer.dpi is DPI.DPI_203

    async def test_dpi_change_reaches_dpmm_and_getvar(self, ui):
        await ui.client.post("/api/settings", json={"dpi": "203"})
        assert ui.server.printer.dpmm == 8
        assert ui.server.printer.vars["head.resolution.in_dpi"] == "203"

    async def test_an_invalid_dpi_is_rejected(self, ui):
        body = await (await ui.client.post("/api/settings", json={"dpi": "999"})).json()
        assert body["ok"] is False
        assert ui.server.printer.dpi is DPI.DPI_300

    async def test_an_invalid_width_is_rejected(self, ui):
        body = await (
            await ui.client.post("/api/settings", json={"width": "wide"})
        ).json()
        assert body["ok"] is False

    async def test_a_port_change_rebinds_the_listener(self, ui):
        await ui.client.post("/api/server/start")
        original = ui.port
        await ui.client.post("/api/settings", json={"port": 0})
        assert ui.server.is_running
        assert ui.port != original
        reply = await send(ui.port, b'! U1 getvar "appl.name"\r\n', read_reply=True)
        assert reply.strip() == b"V74.20.22Z"

    async def test_a_port_change_while_stopped_does_not_start_it(self, ui):
        await ui.client.post("/api/settings", json={"port": 0})
        assert not ui.server.is_running

    async def test_settings_survive_a_label(self, ui):
        await ui.client.post("/api/settings", json={"height": 6})
        await ui.client.post("/api/server/start")
        assert await ui.print_label()
        body = await (await ui.client.get("/api/state")).json()
        assert body["settings"]["height"] == 6


class TestEventStream:
    async def read_messages(self, ui, count, timeout=5):
        """Collect *count* SSE payloads, ignoring keepalive comments."""
        messages = []
        response = await ui.client.get("/api/events")

        async def pump():
            async for raw in response.content:
                line = raw.decode().strip()
                if line.startswith("data: "):
                    messages.append(json.loads(line[6:]))
                    if len(messages) >= count:
                        return

        try:
            await asyncio.wait_for(pump(), timeout=timeout)
        except asyncio.TimeoutError:
            pass
        finally:
            response.close()
        return messages

    async def test_a_client_is_registered_and_released(self, ui):
        response = await ui.client.get("/api/events")
        assert await settle(lambda: len(ui.state.clients) == 1)
        response.close()
        assert await settle(lambda: len(ui.state.clients) == 0)

    async def test_status_changes_are_pushed(self, ui):
        response = await ui.client.get("/api/events")
        await settle(lambda: len(ui.state.clients) == 1)
        try:
            await ui.client.post("/api/server/start")
            messages = []

            async def pump():
                async for raw in response.content:
                    line = raw.decode().strip()
                    if line.startswith("data: "):
                        messages.append(json.loads(line[6:]))
                        if any(m.get("type") == "status" for m in messages):
                            return

            await asyncio.wait_for(pump(), timeout=5)
            status = next(m for m in messages if m["type"] == "status")
            assert status["status"]["running"] is True
        finally:
            response.close()

    async def test_a_printed_label_is_pushed(self, ui):
        await ui.client.post("/api/server/start")
        response = await ui.client.get("/api/events")
        await settle(lambda: len(ui.state.clients) == 1)
        try:
            await send(ui.port, LABEL.encode())
            messages = []

            async def pump():
                async for raw in response.content:
                    line = raw.decode().strip()
                    if line.startswith("data: "):
                        messages.append(json.loads(line[6:]))
                        if any(m.get("type") == "label" for m in messages):
                            return

            await asyncio.wait_for(pump(), timeout=5)
            label = next(m for m in messages if m["type"] == "label")
            assert label["label"]["bytes"] == len(PNG)
        finally:
            response.close()

    async def test_a_slow_client_does_not_block_publishing(self, ui):
        """A browser that stops reading must not stall the printer."""
        queue = ui.state.add_client()
        try:
            for _ in range(queue.maxsize + 10):
                ui.state.broadcast({"type": "log", "message": "x"})
        finally:
            ui.state.remove_client(queue)


class TestLogPanel:
    async def test_events_reach_the_log(self, ui):
        await ui.client.post("/api/server/start")
        assert await settle(lambda: any("running on" in e["message"] for e in ui.state.logs))

    async def test_a_render_failure_is_logged_at_error_level(self, ui):
        await ui.client.post("/api/server/start")
        await send(ui.port, f"^XA^FD{POISON}^FS^XZ".encode())
        assert await settle(
            lambda: any(
                entry["level"] == "ERROR" and "could not be rendered" in entry["message"]
                for entry in ui.state.logs
            )
        )

    async def test_the_log_is_capped(self, ui):
        for index in range(ui.state.logs.maxlen + 50):
            ui.state.add_log("INFO", f"line {index}", 0.0)
        assert len(ui.state.logs) == ui.state.logs.maxlen

    async def test_state_includes_recent_logs(self, ui):
        ui.state.add_log("INFO", "hello", 0.0)
        body = await (await ui.client.get("/api/state")).json()
        assert any(entry["message"] == "hello" for entry in body["logs"])

    async def test_the_handler_survives_a_closed_loop(self, ui):
        """Records can arrive while shutting down; that must not raise."""
        handler = StateLogHandler(ui.state)
        ui.state.loop = None
        handler.emit(
            logging.LogRecord("zplserver", logging.INFO, __file__, 1, "x", None, None)
        )
