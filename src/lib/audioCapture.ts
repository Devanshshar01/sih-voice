/**
 * Captures the operator's microphone, resamples to 16kHz mono (via the
 * AudioContext's own sampleRate option), and delivers fixed-size Float32
 * PCM chunks matching the backend's hop size (8000 samples = 0.5s @ 16kHz).
 *
 * Also exposes an AnalyserNode wired to the same source so the UI can draw
 * a real, live frequency trace -- not a decorative animation.
 */
const SAMPLE_RATE = 16000;
const CHUNK_SAMPLES = 8000;

export class LiveAudioCapture {
  private audioContext: AudioContext | null = null;
  private mediaStream: MediaStream | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private workletNode: AudioWorkletNode | null = null;
  private analyser: AnalyserNode | null = null;
  private silentSink: GainNode | null = null;

  async start(onChunk: (chunk: Float32Array) => void): Promise<AnalyserNode> {
    this.mediaStream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
    });

    this.audioContext = new AudioContext({ sampleRate: SAMPLE_RATE });
    await this.audioContext.audioWorklet.addModule("/pcm-processor.js");

    this.source = this.audioContext.createMediaStreamSource(this.mediaStream);

    this.analyser = this.audioContext.createAnalyser();
    this.analyser.fftSize = 256;
    this.analyser.smoothingTimeConstant = 0.75;

    this.workletNode = new AudioWorkletNode(this.audioContext, "pcm-chunk-processor", {
      processorOptions: { chunkSize: CHUNK_SAMPLES },
    });
    this.workletNode.port.onmessage = (event: MessageEvent<Float32Array>) => {
      onChunk(event.data);
    };

    // Silent sink keeps the graph alive without looping the operator's own
    // voice back out of their speakers.
    this.silentSink = this.audioContext.createGain();
    this.silentSink.gain.value = 0;

    this.source.connect(this.analyser);
    this.source.connect(this.workletNode);
    this.workletNode.connect(this.silentSink);
    this.silentSink.connect(this.audioContext.destination);

    return this.analyser;
  }

  setMuted(muted: boolean): void {
    this.mediaStream?.getAudioTracks().forEach((track) => {
      track.enabled = !muted;
    });
  }

  stop(): void {
    this.workletNode?.port.close();
    this.workletNode?.disconnect();
    this.analyser?.disconnect();
    this.source?.disconnect();
    this.silentSink?.disconnect();
    this.mediaStream?.getTracks().forEach((track) => track.stop());
    void this.audioContext?.close();

    this.workletNode = null;
    this.analyser = null;
    this.source = null;
    this.silentSink = null;
    this.mediaStream = null;
    this.audioContext = null;
  }
}

/**
 * Generates a synthetic 8000-sample silent-ish frame for demo mode, where
 * there is no live microphone. It exists purely to advance the backend's
 * sliding window on a realistic cadence; the acoustic score in demo mode is
 * driven entirely by the `force_acoustic_score` WebSocket hook, not by this
 * content.
 */
export function buildDemoFrame(): Float32Array {
  return new Float32Array(CHUNK_SAMPLES);
}

export const AUDIO_CHUNK_SAMPLES = CHUNK_SAMPLES;
export const AUDIO_SAMPLE_RATE = SAMPLE_RATE;
