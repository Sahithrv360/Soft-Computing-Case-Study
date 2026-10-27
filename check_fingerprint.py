from serial.tools import list_ports

print("Detected serial devices:\n")

for port in list_ports.comports():
    print("Port:", port.device)
    print("Description:", port.description)
    print("Hardware ID:", port.hwid)
    print("-" * 40)