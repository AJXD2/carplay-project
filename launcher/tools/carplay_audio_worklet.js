"use strict";
// Patched by carplay-pi launcher/tools/patch_carplay_audio.py. Adds a jitter
// buffer: wait for PREFILL_MS of audio before (re)starting, instead of
// playing the instant 128 frames exist. If the buffer's *minimum* level over
// a WINDOW_S window stays SLACK_MS above PREFILL (slow clock drift, not a
// burst),
// the unused excess is dropped once so latency can't creep up on long drives.
const Q = 128, PREFILL_MS = 120, SLACK_MS = 60, WINDOW_S = 3;
class Ring {
  constructor(sab) {
    this.s = new Int16Array(sab, 8, (sab.byteLength - 8) / 2);
    this.w = new Uint32Array(sab, 0, 1);
    this.r = new Uint32Array(sab, 4, 1);
  }
  avail() {
    const n = this.s.length;
    return (Atomics.load(this.w, 0) + n - Atomics.load(this.r, 0)) % n;
  }
  skip(k) {
    Atomics.store(this.r, 0, (Atomics.load(this.r, 0) + k) % this.s.length);
  }
  readTo(out) {
    const n = this.s.length, p = Atomics.load(this.r, 0);
    for (let i = 0; i < out.length; i++) out[i] = this.s[(p + i) % n];
    this.skip(out.length);
  }
}
class PCMWorkletProcessor extends AudioWorkletProcessor {
  constructor(o) {
    super();
    const { sab, channels } = o.processorOptions;
    this.ch = channels;
    this.ring = new Ring(sab);
    this.buf = new Int16Array(Q * channels);
    const cap = this.ring.s.length / 2;
    const ms = (m) => Math.min(cap, Math.round(sampleRate * m / 1000) * channels);
    this.prefill = ms(PREFILL_MS);
    this.slack = ms(SLACK_MS);
    this.window = Math.round(sampleRate * WINDOW_S / Q);
    this.seen = 0;
    this.low = Infinity;
    this.waiting = true;
  }
  process(_, outputs) {
    const out = outputs[0], need = this.buf.length;
    let a = this.ring.avail();
    if (this.waiting) {
      if (a < this.prefill) return true;
      this.waiting = false;
    }
    if (a < need) {
      console.debug("UNDERFLOW", a);
      this.waiting = true;
      return true;
    }
    if (a < this.low) this.low = a;
    if (++this.seen >= this.window) {
      if (this.low > this.prefill + this.slack) {
        const drop = this.low - this.prefill;
        this.ring.skip(drop - (drop % this.ch));
        a -= drop - (drop % this.ch);
        console.debug("TRIM", drop);
      }
      this.seen = 0;
      this.low = Infinity;
    }
    this.ring.readTo(this.buf);
    for (let i = 0; i < Q; i++) {
      for (let c = 0; c < this.ch; c++) {
        out[c][i] = this.buf[i * this.ch + c] / 32768;
      }
    }
    return true;
  }
}
registerProcessor("pcm-worklet-processor", PCMWorkletProcessor);
