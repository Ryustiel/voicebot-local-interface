from typing import List
from pydub import AudioSegment, playback
import asyncio
import websockets
import json
import io
import pyaudio

WEBHOOK_URI = "ws://127.0.0.1:8080/socket/"
# WEBHOOK_URI = "ws://api-checkin-acc-hvhmdbbpfbhphda4.westeurope-01.azurewebsites.net/webhooks/socket/"

CALL_PARAMETERS = {
    "language": "fr",
    "sector": "acier",
    "simulation": True,
    "ARRIVAL_TIME": "11h00",
}

default_device_info = pyaudio.PyAudio().get_default_input_device_info()

print(f"Default input device is: {default_device_info['name']}")

# Parameters for recording audio
MIC_FRAME_RATE = int(default_device_info['defaultSampleRate'])
FORMAT = pyaudio.paInt16
CHUNK = 16000  # Chunk size for recording (in frames)

SERVER_AUDIO_N_CHANNELS = 1       # Mono audio
SERVER_AUDIO_SAMPLEWIDTH = 2        # 2 bytes per sample (16-bit PCM audio)
SERVER_AUDIO_FRAMERATE = 16000    # 16 kHz sample rate


async def send_audio(websocket, packet_size, stop_event, recorded_audio_data: io.BytesIO):
    """
    Record audio from the microphone and send it in packets over the WebSocket.
    The audio data is split into packets of the specified size and sent at the rate
    appropriate to maintain real-time transmission. Stop on event trigger.
    Additionally, the recorded audio is appended to recorded_audio_data buffer.
    """
    
    # Audio stream configuration
    FORMAT = pyaudio.paInt16  # Example: 16-bit PCM
    MIC_FRAME_RATE = 16000    # Example: 16kHz
    CHUNK = 1024              # Read in chunks of 1024 samples
    SERVER_AUDIO_N_CHANNELS = 1  # Example: Mono audio
    
    audio = pyaudio.PyAudio()
    audio_buffer = b""

    # Open the audio stream for recording
    stream = audio.open(format=FORMAT,
                        channels=SERVER_AUDIO_N_CHANNELS,
                        rate=MIC_FRAME_RATE,
                        input=True,
                        frames_per_buffer=CHUNK)

    try:
        while not stop_event.is_set():
            # Read a chunk of audio data from the stream
            data = stream.read(CHUNK)
            
            # Append the data to the audio buffer
            audio_buffer += data

            # If the buffer size reaches or exceeds the packet size, send it
            while len(audio_buffer) >= packet_size:
                packet = audio_buffer[:packet_size]
                await websocket.send(packet)
                recorded_audio_data.write(packet)
                
                # Remove the sent packet from the buffer
                audio_buffer = audio_buffer[packet_size:]
            
            # Prevent tight loop, let the event loop breathe
            await asyncio.sleep(0.001)

    except websockets.exceptions.ConnectionClosed:
        print("Connection closed, finished sending audio.")

    finally:
        # Clean up audio stream
        stream.stop_stream()
        stream.close()
        audio.terminate()

    print("Finished sending and recording audio.")


async def receive_audio(websocket, received_audio_data: io.BytesIO, stop_event):
    """
    Receive audio data from the WebSocket server, append to the received_audio_data buffer,
    and play the audio immediately upon receipt. Exit when stop_event is set.
    """
    first_bip = True  # wait for 10 secs upon receiving the first packet because 1st dialog line from AI not being sent

    try:
        async for audio_data in websocket:
            if stop_event.is_set():
                break

            # Calculate the number of frames (samples) in the received packet
            num_samples = len(audio_data) // SERVER_AUDIO_SAMPLEWIDTH

            # Calculate the duration of the received audio packet in seconds
            duration_seconds = num_samples / SERVER_AUDIO_FRAMERATE

            # Print size and duration of the audio packet
            print(f"Received audio data of size: {len(audio_data)} bytes")
            print(f"Duration of this audio packet: {duration_seconds:.4f} seconds")

            # Write the received audio data to the storage buffer
            received_audio_data.write(audio_data)

            # Create an AudioSegment from the received audio data for immediate playback
            received_audio_segment = AudioSegment(
                data=audio_data,                   # The raw byte data received from the server
                sample_width=SERVER_AUDIO_SAMPLEWIDTH,  # Sample width (2 bytes = 16-bit audio)
                frame_rate=SERVER_AUDIO_FRAMERATE,     # Frame rate (samples per second)
                channels=SERVER_AUDIO_N_CHANNELS       # Number of audio channels
            )

            if first_bip:
                first_bip = False
                await asyncio.sleep(13) # Wait a couple secs secs upon receiving the first audio : AI delay
                print("Done waiting")
            # Play the received audio immediately
            playback.play(received_audio_segment)

            # Yield control to ensure event loop responsiveness
            await asyncio.sleep(0.01)

    except websockets.exceptions.ConnectionClosed:
        print("Connection closed, finished receiving audio.")


async def websocket_client():
    uri = WEBHOOK_URI

    # Create a stop event to signal when to stop audio recording and receiving
    stop_event = asyncio.Event()
    # Prepare an in-memory buffer for storing the recorded audio
    recorded_audio_data = io.BytesIO()

    # Connect to WebSocket server
    async with websockets.connect(uri) as websocket:
        # Send initial metadata package
        initial_package = {
            "phone_number": "+33782938351",
            "call_parameters": CALL_PARAMETERS,
            "flow_id": ""  # Placeholder for flow ID
        }
        await websocket.send(json.dumps(initial_package))
        
        # Receive response from the server
        response = await websocket.recv()
        
        # Prepare audio data for transmission
        packet_size = 640  # Fixed packet size from server logic
        
        # Prepare a byte buffer to store the received audio data
        received_audio_data = io.BytesIO()

        # Send and receive audio concurrently
        await asyncio.gather(
            send_audio(websocket, packet_size, stop_event, recorded_audio_data),
            receive_audio(websocket, received_audio_data, stop_event)
        )

        # Create an AudioSegment from the raw byte data (for recorded audio)
        recorded_audio_segment = AudioSegment(
            data=recorded_audio_data.getvalue(),    # The raw byte data from the microphone
            sample_width=SERVER_AUDIO_SAMPLEWIDTH,      # Sample width (2 bytes = 16-bit audio)
            frame_rate=SERVER_AUDIO_FRAMERATE,        # Frame rate (samples per second)
            channels=SERVER_AUDIO_N_CHANNELS          # Number of audio channels
        )

        # Export the recorded audio to a file (e.g., "recorded_audio.wav")
        recorded_audio_segment.export("recorded_audio.wav", format="wav")

        # If needed, create an AudioSegment from the received audio
        received_audio_segment = AudioSegment(
            data=received_audio_data.getvalue(),    # The raw byte data received from the server
            sample_width=SERVER_AUDIO_SAMPLEWIDTH,      # Sample width (2 bytes = 16-bit audio)
            frame_rate=SERVER_AUDIO_FRAMERATE,        # Frame rate (samples per second)
            channels=SERVER_AUDIO_N_CHANNELS          # Number of audio channels
        )

        # Export the received audio to a file (e.g., "received_audio.wav")
        received_audio_segment.export("received_audio.wav", format="wav")


# Run the client
if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(websocket_client())
