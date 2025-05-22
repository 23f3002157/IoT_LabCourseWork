from flask import Flask, render_template
from flask_socketio import SocketIO, emit
from sense_hat import SenseHat
import requests
import time
import threading
import math
import random

# Initialize Flask and SocketIO
app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret!'
socketio = SocketIO(app)

# Initialize Sense HAT
sense = SenseHat()
sense.clear()

# ThingSpeak configuration
THINK_1_API_KEY = "ENTER_YOUR_API_KEY"
THINK_2_API_KEY = "ENTER_YOUR_API_KEY"
THING_SPEAK_URL = "https://api.thingspeak.com/update"

# Data storage for logging
data_log = []
logging_active = False
logging_thread = None
led_thread = None
led_active = False

# LED Colors
BLUE = [0, 0, 255]
LIGHT_BLUE = [135, 206, 235]
RED = [255, 0, 0]
ORANGE = [255, 165, 0]
WHITE = [255, 255, 255]
BLACK = [0, 0, 0]

def temperature_pulse(temp):
    """Pulsing effect based on temperature."""
    global led_active
    temp = max(0, min(temp, 40))  # Clamp temperature between 0°C and 40°C
    phase = 0
    while led_active:
        # Map temperature to color (blue to red)
        blue = int(255 * (1 - (temp - 0) / 40))
        red = int(255 * (temp - 0) / 40)
        color = [red, 0, blue]
        
        # Pulsing effect
        brightness = (math.sin(phase) + 1) / 2  # 0 to 1
        adjusted_color = [int(c * brightness) for c in color]
        sense.clear(adjusted_color)
        phase += 0.2
        time.sleep(0.1)

def pressure_wave(pressure):
    """Wave pattern based on pressure (950–1050 hPa typical range)."""
    global led_active
    pressure = max(950, min(pressure, 1050))  # Clamp pressure
    speed = (pressure - 950) / 100  # 0 to 1 (faster for higher pressure)
    phase = 0
    while led_active:
        pixels = []
        for y in range(8):
            row = []
            for x in range(8):
                intensity = (y + phase) % 8
                if intensity < 4:
                    row.append(ORANGE)
                else:
                    row.append(BLACK)
            pixels.extend(row)
        sense.set_pixels(pixels)
        phase = (phase + speed) % 8
        time.sleep(0.05)

def humidity_rain(humidity):
    """Raindrop effect based on humidity (0–100%)."""
    global led_active
    pixels = [BLACK] * 64
    while led_active:
        # Clear previous raindrops
        for i in range(len(pixels)):
            if pixels[i] == LIGHT_BLUE and random.random() < 0.5:
                pixels[i] = BLACK

        # Add new raindrops based on humidity
        num_drops = int((humidity / 100) * 5)  # 0 to 5 drops
        for _ in range(num_drops):
            col = random.randint(0, 7)
            pixels[col] = LIGHT_BLUE  # Start at top row

        # Move raindrops down
        for row in range(7, 0, -1):
            for col in range(8):
                idx = row * 8 + col
                prev_idx = (row - 1) * 8 + col
                if pixels[prev_idx] == LIGHT_BLUE and pixels[idx] != LIGHT_BLUE:
                    pixels[idx] = LIGHT_BLUE
                    pixels[prev_idx] = BLACK

        sense.set_pixels(pixels)
        time.sleep(0.2 - (humidity / 100) * 0.15)  # Faster for higher humidity

def led_patterns(temperature, pressure, humidity):
    """Cycle through LED patterns for temperature, pressure, and humidity."""
    global led_active
    led_active = True
    while led_active:
        # Temperature pulse (5 seconds)
        temp_thread = threading.Thread(target=temperature_pulse, args=(temperature,))
        temp_thread.start()
        time.sleep(5)
        led_active = False
        temp_thread.join()
        led_active = True

        # Pressure wave (5 seconds)
        press_thread = threading.Thread(target=pressure_wave, args=(pressure,))
        press_thread.start()
        time.sleep(5)
        led_active = False
        press_thread.join()
        led_active = True

        # Humidity rain (5 seconds)
        humid_thread = threading.Thread(target=humidity_rain, args=(humidity,))
        humid_thread.start()
        time.sleep(5)
        led_active = False
        humid_thread.join()
        led_active = True

def log_data():
    global logging_active, data_log, led_thread
    logging_active = True
    start_time = time.time()
    end_time = start_time + 3600  # 1 hour

    # Start LED patterns in a separate thread
    led_active = True
    latest_data = {'temperature': 25, 'pressure': 1013, 'humidity': 50}  # Initial values
    led_thread = threading.Thread(target=led_patterns, args=(latest_data['temperature'], latest_data['pressure'], latest_data['humidity']))
    led_thread.start()

    while time.time() < end_time and logging_active:
        # Read sensor data
        temperature = round(sense.get_temperature(), 2)
        pressure = round(sense.get_pressure(), 2)
        humidity = round(sense.get_humidity(), 2)

        # Update latest data for LED patterns
        latest_data['temperature'] = temperature
        latest_data['pressure'] = pressure
        latest_data['humidity'] = humidity

        # Current timestamp
        timestamp = time.strftime("%H:%M:%S", time.localtime())

        # Store data
        entry = {
            "timestamp": timestamp,
            "temperature": temperature,
            "pressure": pressure,
            "humidity": humidity
        }
        data_log.append(entry)

        # Send to ThingSpeak (both channels)
        payload = {
            "field1": temperature,
            "field2": pressure,
            "field3": humidity
        }
        try:
            # Send to think_1
            payload["api_key"] = THINK_1_API_KEY
            response = requests.get(THING_SPEAK_URL, params=payload)
            if response.status_code != 200:
                print(f"think_1 failed: {response.status_code}")

            # ThingSpeak requires 15-second intervals in free tier
            if len(data_log) % 30 == 0:  # Every 15 seconds (0.5s * 30)
                payload["api_key"] = THINK_2_API_KEY
                response = requests.get(THING_SPEAK_URL, params=payload)
                if response.status_code != 200:
                    print(f"think_2 failed: {response.status_code}")
        except Exception as e:
            print(f"Error sending to ThingSpeak: {e}")

        # Emit data to front-end
        socketio.emit('new_data', entry)

        # Wait 0.5 seconds
        time.sleep(0.5)

    logging_active = False
    led_active = False
    if led_thread:
        led_thread.join()
    sense.clear()

@app.route('/')
def index():
    return render_template('index_data_logger.html')

@socketio.on('start_logging')
def start_logging():
    global logging_thread, logging_active, data_log
    if not logging_active:
        data_log = []  # Clear previous data
        logging_thread = threading.Thread(target=log_data)
        logging_thread.start()
        emit('logging_status', {'status': 'started'})
    else:
        emit('logging_status', {'status': 'already_running'})

@socketio.on('stop_logging')
def stop_logging():
    global logging_active, led_active
    logging_active = False
    led_active = False
    if logging_thread:
        logging_thread.join()
    if led_thread:
        led_thread.join()
    sense.clear()
    emit('logging_status', {'status': 'stopped'})

@socketio.on('get_log')
def get_log():
    emit('data_log', data_log)

if __name__ == '__main__':
    socketio.run(app, host='0.0.0.0', port=5001)