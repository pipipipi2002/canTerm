from textual.app import App, ComposeResult
from textual.containers import ScrollableContainer, Horizontal, Container
from textual.widgets import Header, Footer, Button, Static, Input, SelectionList, DataTable, Label
from textual.widgets.selection_list import Selection
from textual.reactive import reactive
from textual.message import Message
from textual.validation import Function
from typing import  List
from canine import CANineBus
import can, asyncio, datetime


def is_convertible_to_integer(value):
    # Check if value is a valid integer
    try:
        int(value)
        return True
    except ValueError:
        pass

    # Check if value is a valid hexadecimal string
    if value.startswith("0x"):
        try:
            int(value, 16)
            return True
        except ValueError:
            pass

    return False

def convert_to_integer(value):
    try:
        return int(value)
    except ValueError:
        pass

    if value.startswith("0x"):
        try: 
            return int(value, 16)
        except ValueError:
            pass

    return None

def is_data_valid(value: str):
    items = value.split()
    if (len(items) == 0 or len(items) > 8):
        return False
    for item in items:
        if item.startswith("0x"):
            try: 
                value = int(item, 16)
                if not 0 <= value <= 255:
                    return False
            except ValueError:
                return False
        else:
            try:
                value = int(item)
                if not 0 <= value <= 255:
                    return False
            except ValueError:
                return False
    return True


class FilterPane(Static):
    
    filter_ids:set = set()
    BORDER_TITLE = "Filter Pane"

    class FilterChanged(Message):
        def __init__(self, filter_ids: List[int]):
            super().__init__()
            self.filter_ids = filter_ids

    def compose(self) -> ComposeResult:
        with Horizontal(id="f_top"):
            yield Input(placeholder="ID", 
                        classes="filter", 
                        id="f_input",
                        validate_on=["submitted"],
                        validators=[Function(is_convertible_to_integer, "ID Invalid")])
            yield Button("Add", classes="filter", id="f_addbutton")
        yield ScrollableContainer(
            SelectionList(
                id="f_sellist"
            ), id="f_filterContainer")
        yield Button("Clear All", classes="filter", id="f_clrbutton")

    def on_mount(self) -> None: 
        self.filter_list = self.query_one("#f_sellist")
        self.input = self.query_one("#f_input")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if (event.input.id == "f_input" and event.validation_result.is_valid):
            id = convert_to_integer(event.value)
            if(id in self.filter_ids):
                return
            
            self.filter_ids.add(id)
            self.filter_list.add_option(Selection(event.value, id, True))
            self.input.action_delete_left_all()
            self.input.action_delete_right_all()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        button_id = event.button.id
        if (button_id == "f_addbutton"):
            await self.input.action_submit()
        elif (button_id == "f_clrbutton"):
            self.filter_list.deselect_all()
            self.filter_list.clear_options()
            self.filter_ids.clear()

    def on_selection_list_selected_changed(self, event: SelectionList.SelectedChanged) -> None:
        event.stop()
        self.post_message(self.FilterChanged(self.filter_list.selected))


class InputPane(Static):
    BORDER_TITLE = "Input Pane"

    class SendData(Message):
        def __init__(self, id: int, data: List[int]):
            super().__init__()
            self.id = id
            self.data = data

    def compose(self) -> ComposeResult:
        with Container(id="input_pane"):
            yield Input(placeholder="ID", 
                        id="i_input_id",
                        validate_on=["submitted"],
                        validators=[Function(is_convertible_to_integer, "ID Invalid")])
            yield Input(placeholder="Data", 
                        id="i_input_data",
                        validate_on=["submitted"],
                        validators=[Function(is_data_valid, "Data Invalid")])
            yield Button("Send", id="i_sendbutton")

    def on_mount(self) -> None:
        self.inputData = self.query_one("#i_input_data")
        self.inputId = self.query_one("#i_input_id")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        if (event.validation_result.is_valid):
            if (is_data_valid(self.inputId.value) and is_data_valid(self.inputData.value)):
                id = int(self.inputId.value, 16) if self.inputId.value.startswith("0x") else int(self.inputId.value)
                raws = self.inputData.value.split()
                data: List[int] = list()
                for raw in raws:
                    if (raw.startswith("0x")):
                        data.append(int(raw, 16))
                    else:
                        data.append(int(raw))

            self.post_message(self.SendData(id, data))
            self.inputData.action_delete_left_all()
            self.inputData.action_delete_right_all()

    async def on_button_pressed(self, event: Button.Pressed) -> None:
        event.stop()
        if (event.button.id == "i_sendbutton"):
            await self.inputData.action_submit()

class ScreenHeader(Static):
    def __init__ (self, timestamp, canid, length, datas):
        self.timestamp = timestamp
        self.canid = canid
        self.length = length
        self.datas = datas
        super().__init__()
    
    def compose(self) -> ComposeResult:
        with Horizontal(classes="canline canHeader"):
            yield Label(self.timestamp, classes="timestamp")
            yield Label(self.canid, classes="canid")
            yield Label(self.length, classes="canlength")
            for i in range(8):
                yield Label(self.datas[i], classes="candata")


class ScreenLine(Static):

    def __init__ (self, timestamp, canid, length, datas, classes=None):
        self.timestamp = timestamp
        self.canid = canid
        self.length = length
        self.datas = datas
        super().__init__(classes=classes)

    def compose(self) -> ComposeResult:
        with Horizontal(classes="canline"):
            yield Label(self.timestamp, classes="timestamp")
            yield Label(str(self.canid), classes="canid")
            yield Label(str(self.length), classes="canlength")
            for i in range(self.length):
                yield Label(str(self.datas[i]), classes="candata")
                    
            for j in range(self.length, 8):
                yield Label(str("--"), classes="candata")

        
class ScreenPane(Static):
    filterapplied: List[int] = reactive([])
    running:bool = reactive(True)

    BORDER_TITLE = "Screen"
    HEADER_DATA = ["D0", "D1", "D2", "D3", "D4", "D5", "D6", "D7"]
    SAMPLE = [0x11, 0x22, 0x33, 0x44, 0x55, 0x66]

    BINDINGS = []

    def __init__(self, reader, classes, id):
        self.reader:can.BufferedReader = reader
        super().__init__(classes=classes, id=id)
        

    def compose(self) -> ComposeResult:
        datas = [11,22,33,44,55,66,77,88]
        yield ScreenHeader("Timestamp", "ID", "Len", self.HEADER_DATA)
        yield ScrollableContainer(id="screenlines")

    def on_mount(self) -> None:
        self.container = self.query_one("#screenlines")
        self.rxworker = self.run_worker(self.getCanMessage(), exclusive=True)

    def watch_filterapplied(self, filterlist: List[int]) -> None:
        if (len(filterlist) == 0):
            for line in self.query(ScreenLine):
                line.styles.display = "block"
            return

        for line in self.query(ScreenLine):
            line.styles.display = "none"

        for id in filterlist:
            filter_class = ".can-" + str(id)
            for line in self.query(filter_class):
                line.styles.display = "block"

    def watch_running(self, running:bool):
        if (running):
            self.rxworker = self.run_worker(self.getCanMessage(), exclusive=True)
        else:
            self.rxworker.cancel()


    async def getCanMessage(self) -> None:
        while True:
            msg:can.Message = await self.reader.get_message()
            ts = datetime.datetime.fromtimestamp(msg.timestamp).strftime("%H:%M:%S")
            id = msg.arbitration_id
            len = msg.dlc
            data = list(msg.data)
            newline = ScreenLine(ts, id, len, data, classes="can-"+str(id))
            if ((id in self.filterapplied) or not self.filterapplied):
                newline.styles.display = "block"
            else:
                newline.styles.display = "none"
            self.container.mount(newline)
            newline.scroll_visible()
            await asyncio.sleep(0.1)


class canTerm(App):
    BINDINGS = [
        ("d", "toggle_dark", "Toggle Dark Mode"),
        ("p", "pause_recv", "Pause Receive"), 
        ("r", "resume_recv", "Resume Receive")
    ]

    CSS_PATH = "main.tcss"

    def __init__(self, reader:can.BufferedReader, bus: can.Bus):
        self.reader = reader
        self.bus = bus
        super().__init__()

    def compose(self) -> ComposeResult:
        yield Header()
        yield Footer()
        yield FilterPane(classes="box", id="filter_pane")
        yield ScrollableContainer(ScreenPane(reader=self.reader, classes="box", id="monitor_pane"))
        yield InputPane(classes="box", id="transmit_pane")

    def action_pause_recv(self) -> None:
        screen = self.query_one(ScreenPane)
        screen.running = False

    def action_resume_recv(self) -> None:
        screen = self.query_one(ScreenPane)
        screen.running = True
    
    def action_toggle_dark(self) -> None:
        self.dark = not self.dark

    def on_filter_pane_filter_changed(self, event: FilterPane.FilterChanged) -> None:
        """ Get latest filter list from filter pane """
        dest = self.query_one(ScreenPane)
        dest.filterapplied = event.filter_ids

    def on_input_pane_send_data(self, event: InputPane.SendData) -> None:
        """ TX data from input pane """
        id:int = event.id
        data:List[int] = event.data
        
        msg = can.Message(arbitration_id=id, data=data, is_extended_id=False)
        try:
            self.bus.send(msg)
        except can.CanError:
            print("Message Failed to Send")

async def main_app():
    with can.Bus(interface='canine', bitrate=1000000) as bus:
        reader = can.AsyncBufferedReader()
        notifier = can.Notifier(bus, [reader], loop=asyncio.get_running_loop())
        app = canTerm(reader, bus)
        
        await app.run_async()


if __name__ == "__main__":
    asyncio.run(main_app())