class Capture extends AudioWorkletProcessor {
  process(inputs) {
    const x = inputs[0]?.[0];
    if (x) {
      const out = new Int16Array(x.length);
      for (let i = 0; i < x.length; i++)
        out[i] = Math.round(Math.max(-1, Math.min(1, x[i])) * 32767);
      this.port.postMessage(out.buffer, [out.buffer]);
    }
    return true;
  }
}
registerProcessor("capture", Capture);
