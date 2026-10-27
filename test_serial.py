import serial

PORT = "COM9"

try:
    with serial.Serial(
        port=PORT,
        baudrate=57600,
        timeout=2
    ) as ser:
        print(f"Successfully opened {PORT}")
        print("Waiting briefly for incoming data...")
        data = ser.read(64)

        if data:
            print("Received bytes:", data.hex(" "))
        else:
            print("No data received.")
            print("This does NOT necessarily mean the sensor is faulty.")

except serial.SerialException as e:
    print("Could not open serial port:", e)
