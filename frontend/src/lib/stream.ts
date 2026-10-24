import { API_BASE, ApiError, CLIENT_HEADER, toApiError } from "./api";
import type { AskEvent } from "./types";

/**
 * POST /ask and yield parsed server-sent events. EventSource can't POST,
 * so we read fetch's body stream and split on blank-line frame boundaries.
 */
export async function* askStream(
  body: { question: string; conversation_id?: string },
  signal?: AbortSignal,
): AsyncGenerator<AskEvent> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}/ask`, {
      method: "POST",
      credentials: "include",
      headers: { ...CLIENT_HEADER, "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body),
      signal,
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") return;
    throw new ApiError(0, "network", "Can't reach the Inquira server.");
  }
  if (!res.ok || !res.body) throw await toApiError(res);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let boundary: number;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const frame = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const parsed = parseFrame(frame);
      if (parsed) yield parsed;
    }
  }
  const tail = parseFrame(buffer);
  if (tail) yield tail;
}

function parseFrame(frame: string): AskEvent | null {
  let event = "message";
  const data: string[] = [];
  for (const line of frame.split("\n")) {
    if (!line || line.startsWith(":")) continue;
    const idx = line.indexOf(":");
    const field = idx === -1 ? line : line.slice(0, idx);
    const value = idx === -1 ? "" : line.slice(idx + 1).replace(/^ /, "");
    if (field === "event") event = value;
    else if (field === "data") data.push(value);
  }
  if (!data.length) return null;
  try {
    return { event, data: JSON.parse(data.join("\n")) } as AskEvent;
  } catch {
    return null;
  }
}
