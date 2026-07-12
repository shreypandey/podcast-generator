// Generates a small WAV data URI so the mock backend's audio player is actually playable
// (a soft low tone, ~seconds long) without shipping a binary asset. Real mode streams the
// backend's episode.wav instead.

function base64FromBytes(bytes: Uint8Array): string {
  let bin = "";
  const chunk = 0x8000;
  for (let i = 0; i < bytes.length; i += chunk) {
    bin += String.fromCharCode(...bytes.subarray(i, i + chunk));
  }
  return btoa(bin);
}

export function makeToneWavDataUri(seconds = 8, freq = 174): string {
  const rate = 8000;
  const n = Math.floor(seconds * rate);
  const dataLen = n * 2; // 16-bit mono
  const buf = new ArrayBuffer(44 + dataLen);
  const dv = new DataView(buf);
  const wr = (off: number, s: string) => {
    for (let i = 0; i < s.length; i++) dv.setUint8(off + i, s.charCodeAt(i));
  };
  wr(0, "RIFF");
  dv.setUint32(4, 36 + dataLen, true);
  wr(8, "WAVE");
  wr(12, "fmt ");
  dv.setUint32(16, 16, true);
  dv.setUint16(20, 1, true); // PCM
  dv.setUint16(22, 1, true); // mono
  dv.setUint32(24, rate, true);
  dv.setUint32(28, rate * 2, true);
  dv.setUint16(32, 2, true);
  dv.setUint16(34, 16, true);
  wr(36, "data");
  dv.setUint32(40, dataLen, true);
  for (let i = 0; i < n; i++) {
    // gentle amplitude envelope + very low volume so it's unobtrusive
    const env = Math.sin((Math.PI * i) / n);
    const v = Math.sin((2 * Math.PI * freq * i) / rate) * env * 0.12;
    dv.setInt16(44 + i * 2, v * 32767, true);
  }
  return "data:audio/wav;base64," + base64FromBytes(new Uint8Array(buf));
}
