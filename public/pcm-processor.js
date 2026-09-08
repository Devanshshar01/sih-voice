// Runs on the Web Audio rendering thread. Accumulates incoming Float32
// audio samples (mono) into fixed-size frames and posts each completed
// frame back to the main thread, where it's sent over the WebSocket as raw
// PCM bytes -- matching the backend's HOP_SAMPLES (0.5s @ 16kHz = 8000).
class PCMChunkProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const chunkSize = options?.processorOptions?.chunkSize ?? 8000;
    this.chunkSize = chunkSize;
    this.buffer = new Float32Array(chunkSize);
    this.writeIndex = 0;
  }

  process(inputs) {
    const input = inputs[0];
    const channel = input && input[0];
    if (channel) {
      for (let i = 0; i < channel.length; i++) {
        this.buffer[this.writeIndex++] = channel[i];
        if (this.writeIndex >= this.chunkSize) {
          this.port.postMessage(this.buffer.slice(0));
          this.writeIndex = 0;
        }
      }
    }
    return true;
  }
}

registerProcessor("pcm-chunk-processor", PCMChunkProcessor);
