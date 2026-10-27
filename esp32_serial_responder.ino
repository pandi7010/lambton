/*
  ESP32 Serial Responder
  
  Baud Rate: 115200
  Communicates with Python Serial UI over USB COM port.
  Listens for incoming messages ending in newline ('\n')
  and sends structured replies back.
*/

#define LED_PIN 2  // Built-in LED on most ESP32 DevKit boards

void setup() {
  Serial.begin(115200);
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, LOW);

  // Small delay to ensure Serial is initialized
  delay(1000);

  // Send initial startup greeting
  Serial.println("[ESP32] Ready! Listening for commands...");
}

void loop() {
  // Check if serial data is available
  if (Serial.available() > 0) {
    // Read command until newline
    String receivedMsg = Serial.readStringUntil('\n');
    receivedMsg.trim(); // Remove trailing '\r' or spaces

    if (receivedMsg.length() > 0) {
      // Blink LED to indicate activity
      digitalWrite(LED_PIN, HIGH);

      // Handle specific commands or generic reply
      if (receivedMsg.equalsIgnoreCase("PING")) {
        Serial.println("[ESP32] PONG! System is healthy.");
      } else if (receivedMsg.equalsIgnoreCase("HELLO")) {
        Serial.println("[ESP32] Hello from ESP32! Communication successful.");
      } else if (receivedMsg.equalsIgnoreCase("STATUS")) {
        unsigned long uptimeSec = millis() / 1000;
        Serial.printf("[ESP32] Status OK | Uptime: %lu s | Free Heap: %d bytes\n", uptimeSec, ESP.getFreeHeap());
      } else {
        // Echo back with acknowledgment
        Serial.print("[ESP32] Received: \"");
        Serial.print(receivedMsg);
        Serial.println("\" - Message processed successfully!");
      }

      delay(50);
      digitalWrite(LED_PIN, LOW);
    }
  }
}
