import { API_BASE } from "./api";
import { authHeaders } from "../auth/stytch";
import type { V1Event } from "../store/types";

// fetch-based SSE reader. Unlike native EventSource, this lets us set the
// Last-Event-ID header on a fresh connection so a refresh mid-run resumes at
// offset+1 (no duplicated history). Returns a stop() function.

export interface StreamHandle {
  stop: () => void;
}

export function openRunStream(
  runId: string,
  lastEventId: number | null,
  onEvent: (ev: V1Event) => void,
  onClose?: () => void
): StreamHandle {
  const controller = new AbortController();
  let stopped = false;

  (async () => {
    // Bearer + session token ride along with the resume cursor. This is why
    // the reader is fetch-based rather than EventSource: EventSource can't
    // set either header.
    const headers: Record<string, string> = { ...authHeaders() };
    if (lastEventId != null && lastEventId >= 0) headers["Last-Event-ID"] = String(lastEventId);

    let res: Response;
    try {
      res = await fetch(`${API_BASE}/runs/${encodeURIComponent(runId)}/stream`, {
        headers,
        signal: controller.signal,
      });
    } catch {
      if (!stopped) onClose?.();
      return;
    }
    if (!res.ok || !res.body) {
      onClose?.();
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";

    try {
      for (;;) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });

        // Split on SSE record boundary (blank line).
        let sep: number;
        while ((sep = buf.indexOf("\n\n")) !== -1) {
          const record = buf.slice(0, sep);
          buf = buf.slice(sep + 2);
          let data = "";
          for (const line of record.split("\n")) {
            if (line.startsWith("data:")) data += line.slice(5).trim();
          }
          if (data) {
            try {
              onEvent(JSON.parse(data) as V1Event);
            } catch {
              /* ignore malformed record */
            }
          }
        }
      }
    } catch {
      /* aborted or network error */
    } finally {
      if (!stopped) onClose?.();
    }
  })();

  return {
    stop: () => {
      stopped = true;
      controller.abort();
    },
  };
}
