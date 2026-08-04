import re
from dataclasses import dataclass

command_map = {
    "^A": {
        "format": "^Afo,h,w,d:f.x",
        "description": "Select a scalable or bitmap font for the field",
    },
    "^A@": {"format": "o,h,w,d:f.x", "description": "Select a font by stored file name"},
    "^B0": {"format": "a,b,c,d,e,f,g", "description": "Configure Aztec symbol options"},
    "^B1": {"format": "o,e,h,f,g", "description": "Draw a Code 11 barcode"},
    "^B2": {"format": "o,h,f,g,e,j", "description": "Draw an Interleaved 2 of 5 barcode"},
    "^B3": {"format": "o,e,h,f,g", "description": "Draw a Code 39 barcode"},
    "^B4": {"format": "o,h,f,m", "description": "Draw a Code 49 stacked barcode"},
    "^B5": {"format": "o,h,f,g", "description": "Draw a PLANET postal barcode"},
    "^B7": {"format": "o,h,s,c,r,t", "description": "Draw a PDF417 2D barcode"},
    "^B8": {"format": "o,h,f,g", "description": "Draw an EAN-8 barcode"},
    "^B9": {"format": ",h,f,g,e", "description": "Draw a UPC-E barcode"},
    "^BA": {"format": "o,h,f,g,e", "description": "Draw a Code 93 barcode"},
    "^BB": {"format": "o,h,s,c,r,m", "description": "Draw a CODABLOCK stacked barcode"},
    "^BC": {
        "format": "o,h,f,g,e,m",
        "description": "Draw a Code 128 barcode using subset A, B or C",
    },
    "^BD": {"format": "m,n,t", "description": "Draw a MaxiCode 2D barcode"},
    "^BE": {"format": "o,h,f,g", "description": "Draw an EAN-13 barcode"},
    "^BF": {"format": "o,h,m", "description": "Draw a MicroPDF417 barcode"},
    "^BI": {"format": "o,h,f,g", "description": "Draw an Industrial 2 of 5 barcode"},
    "^BJ": {"format": "o,h,f,g", "description": "Draw a Standard 2 of 5 barcode"},
    "^BK": {"format": "o,e,h,f,g,k,l", "description": "Draw a Codabar barcode"},
    "^BL": {"format": "o,h,g", "description": "Draw a LOGMARS barcode"},
    "^BM": {"format": "o,e,h,f,g,e2", "description": "Draw an MSI barcode"},
    "^BO": {"format": "a,b,c,d,e,f,g", "description": "Configure Aztec symbol options"},
    "^BP": {"format": "o,e,h,f,g", "description": "Draw a Plessey barcode"},
    "^BQ": {"format": "a,b,c,d,e", "description": "Draw a QR Code symbol"},
    "^BR": {"format": "a,b,c,d,e,f", "description": "Draw a GS1 DataBar symbol"},
    "^BS": {"format": "o,h,f,g", "description": "Draw a UPC/EAN supplemental barcode"},
    "^BT": {"format": "o,w1,r1,h1,w2,h2", "description": "Draw a TLC39 composite barcode"},
    "^BU": {"format": "o,h,f,g,e", "description": "Draw a UPC-A barcode"},
    "^BX": {"format": "o,h,s,c,r,f,g,a", "description": "Draw a Data Matrix 2D barcode"},
    "^BY": {
        "format": "w,r,h",
        "description": "Set the default bar width, ratio and height for later barcodes",
    },
    "^BZ": {"format": "o,h,f,g,t", "description": "Draw a POSTNET or postal barcode"},
    "^CC": {"format": "x", "description": "Redefine the caret prefix character"},
    "~CC": {"format": "x", "description": "Redefine the caret prefix character"},
    "^CD": {"format": "a", "description": "Redefine the parameter delimiter character"},
    "~CD": {"format": "a", "description": "Redefine the parameter delimiter character"},
    "^CF": {"format": "f,h,w", "description": "Set the default font used by text fields"},
    "^CI": {
        "format": "a,s1,d1,s2,d2,...",
        "description": "Select the character set and remap individual characters",
    },
    "^CM": {
        "format": "a,b,c,d",
        "description": "Reassign the drive letters used for stored objects",
    },
    "^CN": {"format": "a", "description": "Trigger the cutter immediately"},
    "^CO": {"format": "a,b,c", "description": "Configure the font cache"},
    "^CP": {"format": "a", "description": "Discard the label held in the buffer"},
    "^CT": {"format": "a", "description": "Redefine the tilde prefix character"},
    "~CT": {"format": "a", "description": "Redefine the tilde prefix character"},
    "^CV": {"format": "a", "description": "Enable barcode content validation"},
    "^CW": {
        "format": "a,d:o.x",
        "description": "Assign a single-letter alias to a stored font",
    },
    "~DB": {
        "format": "d:o.x,a,h,w,base,space,#char,©,data",
        "description": "Transfer a bitmap font into printer storage",
    },
    "~DE": {
        "format": "d:o.x,s,data",
        "description": "Transfer an encoding table into printer storage",
    },
    "^DF": {"format": "d:o.x", "description": "Store the incoming label format by name"},
    "~DG": {
        "format": "d:o.x,t,w,data",
        "description": "Transfer a graphic image into printer storage",
    },
    "~DN": {"format": "", "description": "Cancel an in-progress graphic transfer"},
    "~DS": {
        "format": "d:o.x,s,data",
        "description": "Transfer a scalable font into printer storage",
    },
    "~DT": {
        "format": "d:o.x,s,data",
        "description": "Transfer a bounded TrueType font into printer storage",
    },
    "~DU": {
        "format": "d:o.x,s,data",
        "description": "Transfer an unbounded TrueType font into printer storage",
    },
    "~DY": {
        "format": "d:f,b,x,t,w,data",
        "description": "Transfer an arbitrary object into printer storage",
    },
    "~EG": {"format": "", "description": "Delete every stored graphic"},
    "^EG": {"format": "", "description": "Delete every stored graphic"},
    "^FB": {
        "format": "a,b,c,d,e",
        "description": "Wrap field text into a block of a given width and line count",
    },
    "^FC": {
        "format": "a,b,c",
        "description": "Set the placeholders used for clock substitution in field data",
    },
    "^FD": {"format": "a", "description": "Supply the literal contents of the field"},
    "^FH": {"format": "a", "description": "Allow hex escapes in the following field data"},
    "^FL": {"format": "ext,base,link", "description": "Chain a fallback font to a base font"},
    "^FM": {
        "format": "x1,y1,x2,y2,...",
        "description": "List the origin points used when a format repeats fields",
    },
    "^FN": {"format": "#a", "description": "Tag the field with a number for later substitution"},
    "^FO": {"format": "x,y,z", "description": "Position the field relative to label home"},
    "^FP": {
        "format": "d,g",
        "description": "Set character spacing and print direction within the field",
    },
    "^FR": {"format": "", "description": "Print the field inverted against its background"},
    "^FS": {"format": "", "description": "End the current field definition"},
    "^FT": {"format": "x,y,z", "description": "Position the field by its text baseline"},
    "^FV": {"format": "a", "description": "Supply data for a numbered field in a recalled format"},
    "^FW": {"format": "r,z", "description": "Set the default rotation and justification for fields"},
    "^FX": {"format": "c", "description": "Insert a comment that produces no output"},
    "^GB": {"format": "w,h,t,c,r", "description": "Draw a rectangle or straight line"},
    "^GC": {"format": "d,t,c", "description": "Draw a circle"},
    "^GD": {"format": "w,h,t,c,o", "description": "Draw a diagonal line"},
    "^GE": {"format": "w,h,t,c", "description": "Draw an ellipse"},
    "^GF": {
        "format": "a,b,c,d,data",
        "description": "Draw an inline bitmap supplied as field data",
    },
    "^GS": {"format": "o,h,w", "description": "Draw a glyph from the built-in symbol font"},
    "~HB": {"format": "", "description": "Report the battery state to the host"},
    "~HD": {"format": "", "description": "Report printhead temperature and diagnostics"},
    "^HF": {"format": "d,o,x", "description": "Send a stored label format back to the host"},
    "^HG": {"format": "d:o.x", "description": "Send a stored graphic back to the host"},
    "^HH": {"format": "", "description": "Send the current configuration to the host as text"},
    "~HI": {"format": "", "description": "Report the model and firmware version to the host"},
    "~HM": {"format": "", "description": "Report available memory to the host"},
    "~HQ": {
        "format": "query-type",
        "description": "Answer a specific status or configuration query",
    },
    "~HS": {"format": "", "description": "Report the status strings describing printer state"},
    "~HU": {"format": "", "description": "Report the configured network alert destinations"},
    "^HV": {
        "format": "#,n,h,t,a",
        "description": "Send the contents of a numbered field back to the host",
    },
    "^HW": {"format": "d:o.x", "description": "List the objects stored on a drive"},
    "^HY": {"format": "d:o.x", "description": "Send a stored graphic to the host as an image"},
    "^HZb": {"format": "b", "description": "Report stored object descriptions to the host"},
    "^HZ0": {
        "format": "O,d:o.x,l",
        "description": "Report stored label format descriptions to the host",
    },
    "^ID": {"format": "d:o.x", "description": "Delete a stored object"},
    "^IL": {"format": "d:o.x", "description": "Load a stored image as the label background"},
    "^IM": {"format": "d:o.x", "description": "Place a stored image at the current origin"},
    "^IS": {"format": "d:o.x,p", "description": "Save the rendered label to storage as an image"},
    "~JA": {"format": "", "description": "Discard every queued and in-progress label"},
    "^JB": {"format": "a", "description": "Format flash storage"},
    "~JB": {"format": "", "description": "Reset the optional memory module"},
    "~JC": {"format": "", "description": "Run media sensor calibration"},
    "~JD": {"format": "", "description": "Echo incoming data for communication diagnostics"},
    "~JE": {"format": "", "description": "Leave diagnostic echo mode"},
    "~JF": {"format": "p", "description": "Choose how the printer reacts to a low battery"},
    "~JG": {"format": "", "description": "Calibrate the sensors and print the resulting profile"},
    "^JH": {
        "format": "a,b,c,d,e,f,g,h,i,j",
        "description": "Configure early-warning supply thresholds",
    },
    "^JI": {
        "format": "d:o.x,b,c,d",
        "description": "Start the embedded BASIC interpreter from a stored program",
    },
    "~JI": {"format": "", "description": "Start the embedded BASIC interpreter"},
    "^JJ": {"format": "a,b,c,d,e,f", "description": "Configure the auxiliary applicator port"},
    "~JL": {"format": "", "description": "Measure and store the label length"},
    "^JM": {"format": "n", "description": "Halve or restore the print resolution"},
    "~JN": {"format": "", "description": "Treat printhead test failures as fatal"},
    "~JO": {"format": "", "description": "Treat printhead test failures as non-fatal"},
    "~JP": {"format": "", "description": "Pause the printer and drop the current format"},
    "~JQ": {"format": "", "description": "Stop the embedded BASIC interpreter"},
    "~JR": {"format": "", "description": "Restart the printer as if power-cycled"},
    "^JS": {"format": "a", "description": "Choose which media sensor is used"},
    "~JS": {"format": "b", "description": "Set when backfeed happens relative to printing"},
    "^JT": {
        "format": "####,a,b,c",
        "description": "Set how often the printhead self-test runs",
    },
    "^JU": {"format": "a", "description": "Save, restore or reset the active configuration"},
    "^JW": {"format": "t", "description": "Set the ribbon tension"},
    "~JX": {"format": "", "description": "Discard a format that was only partly received"},
    "^JZ": {"format": "a", "description": "Choose whether a label is reprinted after an error"},
    "~KB": {"format": "", "description": "Put the battery into discharge mode"},
    "^KD": {
        "format": "a",
        "description": "Choose the date and time layout used by clock fields",
    },
    "^KL": {"format": "a", "description": "Set the control panel language"},
    "^KN": {"format": "a,b", "description": "Set the printer name and description"},
    "^KP": {"format": "a,b", "description": "Set the control panel password"},
    "^KV": {"format": "a,b,c,d,e", "description": "Configure kiosk printing behaviour"},
    "^LF": {"format": "", "description": "Print a label listing the current font links"},
    "^LH": {
        "format": "x,y",
        "description": "Set the origin that field positions are measured from",
    },
    "^LL": {"format": "y", "description": "Set the label length in dot rows"},
    "^LR": {"format": "a", "description": "Invert the entire label"},
    "^LS": {"format": "a", "description": "Shift every field horizontally"},
    "^LT": {"format": "x", "description": "Shift the label vertically"},
    "^MA": {
        "format": "type,print,threshold,frequency,units",
        "description": "Configure maintenance alert thresholds and reporting",
    },
    "^MC": {"format": "a", "description": "Choose whether the bitmap is cleared after printing"},
    "^MD": {"format": "a", "description": "Adjust darkness relative to the current setting"},
    "^MF": {"format": "p,h", "description": "Set media handling at power-up and after head close"},
    "^MI": {
        "format": "type,message",
        "description": "Set the text shown alongside a maintenance alert",
    },
    "^ML": {"format": "a", "description": "Set the longest label length used when calibrating"},
    "^MM": {"format": "a,b", "description": "Select tear-off, peel, cutter or similar mode"},
    "^MN": {"format": "a,b", "description": "Describe how labels are separated on the media"},
    "^MP": {"format": "a", "description": "Lock individual control panel settings"},
    "^MT": {"format": "a", "description": "Select direct thermal or thermal transfer media"},
    "^MU": {
        "format": "a,b,c",
        "description": "Set the units used by later position and size values",
    },
    "^MW": {"format": "a", "description": "Override the cold printhead warning"},
    "^NC": {"format": "a", "description": "Choose the primary network interface"},
    "~NC": {"format": "###", "description": "Connect to a printer by network ID"},
    "^ND": {
        "format": "a,b,c,d,e,f,g,h,i,j",
        "description": "Change the network interface settings",
    },
    "^NI": {"format": "###", "description": "Assign the printer a network ID"},
    "~NR": {
        "format": "",
        "description": "Put every printer on the network into transparent mode",
    },
    "^NS": {
        "format": "a,b,c,d,e,f,g,h,i",
        "description": "Change the wired network address settings",
    },
    "~NT": {"format": "", "description": "Put the connected printer into transparent mode"},
    "^PA": {"format": "a,b,c,d", "description": "Configure advanced text layout options"},
    "^PF": {"format": "#", "description": "Feed the media a number of dot rows"},
    "^PH": {"format": "", "description": "Feed the media to the next label home position"},
    "~PH": {"format": "", "description": "Feed the media to the next label home position"},
    "~PL": {"format": "a", "description": "Add extra feed distance when presenting a label"},
    "^PM": {"format": "a", "description": "Print the label mirrored"},
    "^PN": {"format": "a", "description": "Present the current label immediately"},
    "^PO": {"format": "a", "description": "Rotate the whole label 180 degrees"},
    "^PP": {"format": "", "description": "Pause once the current label finishes"},
    "~PP": {"format": "", "description": "Pause once the current label finishes"},
    "^PQ": {"format": "q,p,r,o,e", "description": "Set how many labels and sets to print"},
    "~PR": {"format": "", "description": "Reprint the last label for the applicator"},
    "^PR": {"format": "p,s,b", "description": "Set the print, slew and backfeed speeds"},
    "~PS": {"format": "", "description": "Resume printing after a pause"},
    "^PW": {"format": "a", "description": "Set the printable width in dots"},
    "~RO": {"format": "c", "description": "Reset a maintenance counter"},
    "^SC": {
        "format": "a,b,c,d,e,f",
        "description": "Set the serial port baud rate, parity and framing",
    },
    "~SD": {"format": "##", "description": "Set the absolute print darkness"},
    "^SE": {"format": "d:o.x", "description": "Select a stored encoding table"},
    "^SF": {"format": "a,b", "description": "Increment field data automatically on each label"},
    "^SI": {"format": "a,b", "description": "Set the media sensor intensity"},
    "^SL": {"format": "a,b", "description": "Set the clock mode and language for date fields"},
    "^SN": {
        "format": "v,n,z",
        "description": "Print a run of labels with an incrementing value",
    },
    "^SO": {
        "format": "a,b,c,d,e,f,g",
        "description": "Offset the clock used by date and time fields",
    },
    "^SP": {"format": "#", "description": "Start printing before the format is complete"},
    "^SQ": {"format": "a,b,c", "description": "Stop sending network alerts"},
    "^SR": {"format": "####", "description": "Set the printhead resistance value"},
    "^SS": {
        "format": "w,m,r,l,m2,r2,a,b,c",
        "description": "Set the media sensor thresholds directly",
    },
    "^ST": {"format": "a,b,c,d,e,f,g", "description": "Set the real-time clock"},
    "^SX": {"format": "a,b,c,d,e,f", "description": "Configure where network alerts are sent"},
    "^SZ": {"format": "a", "description": "Select which version of the language is used"},
    "~TA": {"format": "###", "description": "Adjust the rest position used for tear-off"},
    "^TB": {"format": "a,b,c", "description": "Lay out text or a barcode inside a bounded block"},
    "^TO": {"format": "s:o.x,d:o.x", "description": "Copy a stored object to another location"},
    "~WC": {"format": "", "description": "Print a label showing the current configuration"},
    "^WD": {"format": "d:o.x", "description": "Print a label listing stored objects"},
    "~WQ": {
        "format": "query-type",
        "description": "Query printer status or maintenance information",
    },
    "^XA": {"format": "", "description": "Begin a label format"},
    "^XB": {"format": "", "description": "Skip backfeed for this label"},
    "^XF": {"format": "d:o.x", "description": "Recall a stored label format"},
    "^XG": {
        "format": "d:o.x,mx,my",
        "description": "Recall a stored graphic, optionally magnified",
    },
    "^XS": {
        "format": "length,threshold",
        "description": "Configure dynamic media calibration",
    },
    "^XZ": {"format": "", "description": "End the label format and print it"},
    "^ZZ": {"format": "t,b", "description": "Put the printer to sleep after a timeout"},
}
# Longest first, so that a command is not shadowed by another that happens to
# be a prefix of it: "^A@" must win over "^A".
pattern = re.compile(
    "|".join(map(re.escape, sorted(command_map, key=len, reverse=True)))
)


@dataclass
class ZPLCommand:
    command: str
    description: str
    parameters: dict

    def __str__(self) -> str:
        return f"command={self.command} description={self.description} " + " ".join(
            f"{key}={value}" if key != "data" else "data=[data]"
            for key, value in self.parameters.items()
        )


def parse_zpl(zpl: str) -> list[ZPLCommand]:
    commands = []
    matches = list(pattern.finditer(zpl))
    for idx, match in enumerate(matches):
        command = match.group()
        start = match.end()
        next_match = idx + 1
        if next_match < len(matches):
            end = matches[next_match].start()
        else:
            end = len(zpl)
        command_schema = command_map[command]
        command_body = zpl[start:end].strip("\r\n")
        if command_body:
            # Only split off as many parameters as the command declares, so that
            # a comma inside the last one (field data, most often) survives.
            fields = command_schema["format"].split(",")
            parameters = dict(zip(fields, command_body.split(",", len(fields) - 1)))
        else:
            parameters = {}
        commands.append(ZPLCommand(command, command_schema["description"], parameters))
    return commands
