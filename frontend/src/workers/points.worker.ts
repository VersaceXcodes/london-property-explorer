/// <reference lib="webworker" />

import { decodePointsBinary, postcodeAt } from '@schema';

const context = self as DedicatedWorkerGlobalScope;

context.onmessage = (event: MessageEvent<ArrayBuffer>) => {
  try {
    const decoded = decodePointsBinary(event.data);
    const positions = new Float32Array(decoded.length * 2);
    const colors = new Uint8Array(decoded.length * 4);
    const postcodes = new Array<string>(decoded.length);
    for (let index = 0; index < decoded.length; index += 1) {
      positions[index * 2] = decoded.lng[index];
      positions[index * 2 + 1] = decoded.lat[index];
      const price = decoded.price[index];
      const color = price < 400_000 ? [28, 132, 89] : price < 800_000 ? [26, 105, 170] : [190, 63, 51];
      colors.set([...color, 205], index * 4);
      postcodes[index] = postcodeAt(decoded, index);
    }
    context.postMessage(
      {
        ok: true,
        length: decoded.length,
        positions,
        prices: decoded.price,
        dates: decoded.dateDays,
        typeCodes: decoded.typeCode,
        colors,
        postcodes,
      },
      [event.data, positions.buffer, colors.buffer],
    );
  } catch (error) {
    context.postMessage({ ok: false, message: error instanceof Error ? error.message : 'Binary decode failed' });
  }
};

